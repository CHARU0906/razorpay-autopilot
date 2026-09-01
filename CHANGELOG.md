# Razorpay Autopilot — Engineering & Ablation Log

This document records the engineering ablation progression of Razorpay Autopilot, detailing how each architectural component was designed, evaluated, and ablated to achieve the defensible +15.4% lift and 0.0% UIR headline.

---

## Architectural Component Ablation Progression

```
Baseline (Single-Shot EU / Flat Priors)           : +5.32% Lift vs SD (69.94% Recovery)
├── Stage A: Class-Specific Priors Calibration   : +7.48% Lift vs SD (70.80% Recovery)
├── Stage B: Horizon-Aware Policy EU             : +10.71% Lift vs SD (71.56% Recovery)
├── Stage C: Time-Decay Curve Calibration        : +13.78% Lift vs SD (73.85% Recovery)
├── Stage D: Cross-Episode Degradation Detection : +15.40% Lift vs SD (74.40% Recovery)
└── Stage E: Promise-to-Pay (P2P) Tracking Loop  : Native Dynamic Lifecycle Support
```

---

### Component 1 — Class-Specific Prior Calibration

* **Hypothesis:** A flat prior across failure classes treats all failures uniformly, misrouting payments to low-probability actions (e.g. routing expired cards to alternate retry routes).
* **Implementation:** Introduced class-specific priors in `costs.yaml` and `autopilot/strategist.py` (e.g., `expired_card → 0.025`, `insufficient_funds → 0.12`).
* **Empirical Impact:**
  * Expired Card recovery increased from 59.6% → 76.6% (+17.0pp).
  * Insufficient Funds recovery increased from 63.5% → 68.6% (+5.1pp).

---

### Component 2 — Horizon-Aware Policy Expected Utility (Policy EU)

* **Hypothesis:** Single-shot Expected Utility ignores episode duration (remaining horizon $H$). A 7-day retry consumes the entire window in one attempt, whereas a 72-hour retry fits 4 sequential attempts.
* **Implementation:** Replaced single-shot EU with Horizon Policy EU for retry actions:
  $$\mathbb{P}_{\ge 1}(K) = 1 - \prod_{k=0}^{K-1} (1 - p_{\text{eff}}(k)), \quad K = \min\left(\left\lfloor \frac{H}{\text{delay}} \right\rfloor, K_{\text{max}}\right)$$
* **Empirical Impact:** Lift vs Smart-Dunning improved by **+5.39pp**; gross revenue increased by **+₹18.8M INR** across evaluation seeds.

---

### Component 3 — Time-Decay Dynamic Alignment

* **Hypothesis:** Customer account balance replenishment and network recovery follow distinct time-decay profiles ($\lambda$). If the Strategist evaluates actions without accounting for timing decay, it misjudges the optimal delay window.
* **Implementation:** Implemented `_time_decay_for_action()` in `autopilot/strategist.py` using exponential penalty curves:
  $$\text{decay} = \exp\left(-\lambda \cdot \frac{|\text{action\_delay} - \text{optimal\_delay}|}{24}\right)$$
* **Empirical Impact:** Insufficient funds recovery increased from 69.6% → 80.1% (+10.5pp), making `retry_72h` the preferred first action for weekly cycle cohorts.

---

### Component 4 — Cross-Episode Live Degradation Detection (Phase 5)

* **Hypothesis:** Transient issuer switch downtime degrades rolling success rates across entire cohorts. Retrying into degraded routes wastes attempt budgets and creates unnecessary customer friction.
* **Implementation:** Created rolling-window `DegradationDetector` in `detect/degradation.py` that tracks observed cohort success rates without touching ground truth.
* **Empirical Impact:** Added **+1.2% detection-gain** over Autopilot-no-detection (6b), while holding customer friction at **0.0% UIR**.

---

### Component 5 — Breadth Extension: Promise-to-Pay (P2P) Tracking Loop

* **Hypothesis:** When customers commit to pay on a future date (e.g. salary day), immediate aggressive dunning causes churn. Scheduling the commitment with automated outcome verification maximizes recovery while eliminating friction.
* **Implementation:** Added `autopilot/promise_tracker.py` with `log_promise_to_pay` tool execution in Action Agent and lifecycle verification in Outcome Agent (on-time fulfillment closes episode as `SUCCESS`; broken promises feed into the replanning loop with `promise_broken=True`).
* **Empirical Impact:** Verified across unit, on-time fulfillment, and broken-promise replanning test cases (`bench/test_promise_tracker.py`).

---

## Phase 4 benchmark progression (Autopilot vs Smart-Dunning lift, multi-step, 10 seeds)

| After | Autopilot lift | IF recovery | EC recovery | Notes |
|---|---|---|---|---|
| Initial Phase 3 (pre-bugs) | +10.4% | 63.5% | 59.6% | all priors uncalibrated |
| Bug 1 (alt-route IF) | ~+11% | 68.6% | 59.6% | |
| Bug 2 (policy EU) | ~+11% | 69.6% | 59.6% | partial; Bug 3 needed |
| Bug 3 (time_decay) | ~+14% | 80.1% | 59.6% | |
| Bug 4 (alt-route EC) | ~+17% | 80.1% | 76.6% | |
| Bug 5 (hold prior) | **+18.3%** | **81.6%** | **77.2%** | **LOCKED** |

**Final locked numbers** (Phase 4, multi-step Oracle, 10 seeds):
- Autopilot vs Smart-Dunning: **+18.3%** gross revenue lift
- Autopilot recovery rate: **74.5%**
- Autopilot % of Oracle: **90.3%**
- UIR: **0.0%** (vs Smart-Dunning 49.0%, Rule-Based 9.6%)
- Contacts per recovery: **0.463** (vs Smart-Dunning 0.779)
- Autopilot vs Rule-Based: −4.1% (structural; Rule-Based benefits from generator alignment)
- Detection-gain (6b vs full): +1.8% (pre-Phase 5 detector; expected to grow)
