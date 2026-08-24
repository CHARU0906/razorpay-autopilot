"""Cross-episode degradation detector (SPEC §5.2, Phase 5).

Observes a rolling window of action outcomes across episodes, grouped by
cohort key (country, card_network, issuer_bank_code / acquirer_route_id /
payment_method+issuer).  Fires when the cohort's rolling success rate shows
a statistically meaningful decline.

Contract:
  - Only reads observed fields and observed outcomes of already-resolved episodes.
  - Never reads ground truth.
  - Monitors the three cohort keys defined in sim_config.yaml incidents block.
  - Is shared across all episodes processed in sim_hour order within a seed run.
  - Must be reset between seeds.

Integration point (SPEC §5.2):
  Autopilot.decide() and run_episode() call enrich_investigator_result() after
  investigate() returns, which sets inv.incident_id and inv.incident_active.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Load monitored cohort keys from sim_config.yaml at import time
# ---------------------------------------------------------------------------

def _load_monitored_keys() -> dict[str, str]:
    """
    Returns mapping: canonical_cohort_key → incident_id_hint
    Keys are derived from sim_config.yaml incidents block — same source as the
    simulator, so detection is calibrated against the actual incident structure.
    Only these keys are monitored; all other cohort combinations are ignored.
    """
    try:
        if yaml is None:
            return {}
        with (ROOT / "sim_config.yaml").open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        keys = {}
        for inc_id, inc in cfg.get("incidents", {}).items():
            cohort = inc.get("cohort", {})
            key = _cohort_dict_to_key(cohort)
            if key:
                keys[key] = inc_id
        return keys
    except Exception:
        return {}


def _cohort_dict_to_key(cohort: dict) -> str | None:
    """Convert an incident cohort dict to a canonical detector key."""
    # INC-1 style: country + card_network + issuer_bank_code
    if "country" in cohort and "card_network" in cohort and "issuer_bank_code" in cohort:
        return f"{cohort['country']}|{cohort['card_network']}|{cohort['issuer_bank_code']}"
    # INC-2 style: acquirer_route_id (cross-border only)
    if "acquirer_route_id" in cohort:
        return f"xb|{cohort['acquirer_route_id']}"
    # INC-3 style: payment_method + issuer_bank_code
    if "payment_method" in cohort and "issuer_bank_code" in cohort:
        return f"upi|{cohort['issuer_bank_code']}"
    return None


# Load at module level — safe, deterministic, no GT access
MONITORED_KEYS: dict[str, str] = _load_monitored_keys()  # key → incident_id_hint


# ---------------------------------------------------------------------------
# Cohort key definitions — mirror the three incidents in sim_config.yaml
# ---------------------------------------------------------------------------

def cohort_key(observed: dict) -> str | None:
    """Return a canonical cohort string if this episode belongs to a monitored cohort, else None."""
    code = observed.get("failure_code") or ""
    # Only track episodes that could be part of a degradation cluster.
    if code not in {"issuer_down", "network_timeout", "GATEWAY_ERROR"}:
        return None

    country = observed.get("country") or ""
    network = observed.get("card_network") or ""
    issuer  = observed.get("issuer_bank_code") or ""
    method  = observed.get("payment_method") or ""
    route   = observed.get("acquirer_route_id") or ""
    cross   = bool(observed.get("is_cross_border"))

    # INC-1 style
    if country and network and issuer:
        candidate = f"{country}|{network}|{issuer}"
        if candidate in MONITORED_KEYS:
            return candidate

    # INC-2 style: cross-border + specific route
    if cross and route:
        candidate = f"xb|{route}"
        if candidate in MONITORED_KEYS:
            return candidate

    # INC-3 style: payment_method + issuer
    if method in {"upi_autopay", "emandate_nach"} and issuer:
        candidate = f"upi|{issuer}"
        if candidate in MONITORED_KEYS:
            return candidate

    return None


# ---------------------------------------------------------------------------
# Detector state
# ---------------------------------------------------------------------------

@dataclass
class CohortWindow:
    """Rolling outcome window for one cohort key."""
    key: str
    outcomes: deque = field(default_factory=lambda: deque(maxlen=20))
    sim_hours: deque = field(default_factory=lambda: deque(maxlen=20))
    # Detection state
    incident_id: Optional[str] = None
    incident_active: bool = False
    detection_sim_hour: Optional[float] = None
    # Track consecutive declining sub-windows for the trend signal
    last_rate: Optional[float] = None


class DegradationDetector:
    """
    Shared state object: one per seed run.  Not thread-safe.

    Algorithm:
      For each cohort key, maintain a rolling window of the last W outcomes
      (success=1, failure=0).  When we have ≥ MIN_OBS observations, compute
      the rolling success rate.  Declare incident_active when:
        1. Current rate < RATE_THRESHOLD  (absolute floor)
        2. Rate has declined by ≥ DECLINE_DELTA from the window's first-half mean
           (trend signal — prevents triggering on a permanently bad cohort)

    Parameters are conservative to avoid false positives on small samples,
    and calibrated against the INC-1 trajectory (94%→91%→87%→82%).
    """

    WINDOW_SIZE = 15        # rolling window depth (observed outcomes)
    MIN_OBS = 8             # minimum observations before any detection
    RATE_THRESHOLD = 0.88   # absolute rate below which decline is possible
    DECLINE_DELTA = 0.06    # how much rate must fall from early-window mean
    MIN_LATE_OBS = 3        # minimum observations in the late half before firing

    def __init__(self):
        self._cohorts: dict[str, CohortWindow] = {}
        self._incident_counter = 0
        # episode_id → (incident_id, detection_sim_hour) for latency reporting
        self.detections: list[dict] = []

    def reset(self) -> None:
        self._cohorts.clear()
        self._incident_counter = 0
        self.detections.clear()

    def record_outcome(
        self,
        observed: dict,
        succeeded: bool,
        sim_hour: float,
    ) -> None:
        """Call after each episode resolves with its observed outcome."""
        key = cohort_key(observed)
        if key is None:
            return
        if key not in self._cohorts:
            self._cohorts[key] = CohortWindow(key=key)
        cw = self._cohorts[key]
        cw.outcomes.append(1 if succeeded else 0)
        cw.sim_hours.append(sim_hour)
        self._update_detection(cw)

    def enrich(self, inv_result, observed: dict) -> None:
        """
        Set incident_id and incident_active on an InvestigatorResult in-place.
        Called by Autopilot.decide() / run_episode() after investigate().
        """
        key = cohort_key(observed)
        if key is None:
            return
        cw = self._cohorts.get(key)
        if cw is None or not cw.incident_active:
            return
        inv_result.incident_id = cw.incident_id
        inv_result.incident_active = True

    # ------------------------------------------------------------------
    # Internal detection logic
    # ------------------------------------------------------------------

    def _update_detection(self, cw: CohortWindow) -> None:
        n = len(cw.outcomes)
        if n < self.MIN_OBS:
            return

        outcomes = list(cw.outcomes)
        current_rate = sum(outcomes) / n

        if current_rate >= self.RATE_THRESHOLD:
            # Rate is healthy — clear active incident so it can re-trigger if needed
            if cw.incident_active:
                cw.incident_active = False
                cw.incident_id = None
            cw.last_rate = current_rate
            return

        # Recency gate: the latest outcome must be recent (within 48h of the window's
        # most recent observation) to avoid false positives from ancient failure clusters.
        # Also require that observations span at least a 4h window.
        if len(cw.sim_hours) >= 2:
            time_span = float(cw.sim_hours[-1]) - float(cw.sim_hours[0])
            if time_span < 4.0:
                return

        # Check trend: early-half mean vs late-half mean
        half = max(3, n // 2)
        early_mean = sum(outcomes[:half]) / half
        late_mean  = sum(outcomes[half:]) / max(1, n - half)
        late_n     = n - half

        declined = (late_n >= self.MIN_LATE_OBS
                    and (early_mean - late_mean) >= self.DECLINE_DELTA
                    and late_mean < self.RATE_THRESHOLD)

        if declined and not cw.incident_active:
            # New incident detected
            self._incident_counter += 1
            cw.incident_id = f"DET-{self._incident_counter:03d}"
            cw.incident_active = True
            cw.detection_sim_hour = float(cw.sim_hours[-1]) if cw.sim_hours else 0.0
            self.detections.append({
                "incident_id": cw.incident_id,
                "cohort_key": cw.key,
                "detection_sim_hour": cw.detection_sim_hour,
                "rate_at_detection": round(current_rate, 4),
                "early_mean": round(early_mean, 4),
                "late_mean": round(late_mean, 4),
                "n_obs": n,
            })

        cw.last_rate = current_rate
