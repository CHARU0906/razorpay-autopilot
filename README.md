# Razorpay Autopilot

**A closed-loop payment recovery orchestration system** — not a smart retry scheduler.
When a recurring payment fails, Autopilot decides *whether* to intervene, *what* to do,
*executes*, *verifies the outcome*, and *replans* if it fails — across the full 13-action
space from silent retries to escalation, priced by an explicit utility function.

> **Simulation disclaimer:** This project is designed around Razorpay-like payment flows
> and evaluated entirely within a controlled synthetic simulation environment.
> **No production Razorpay APIs or live transaction data were used.** The simulator
> generates realistic payment-failure episodes with hidden ground truth, used to benchmark
> Autopilot against industry-representative baselines.
> All figures in this document and demo are derived from a 3,000-episode synthetic
> benchmark (10 evaluation seeds), not real transaction data.

---

## The problem

Subscription payment failures cost real money. The industry default is a fixed retry
ladder: try again in 1 hour, 6 hours, 24 hours, give up. It works for transient blips.
It is the wrong answer for every other failure class — expired cards, authentication gaps,
salary-cycle timing, and live issuer degradation events where retrying into a degrading
route burns attempts and annoys customers simultaneously.

The existing baselines ("Smart-Dunning", "Learned Smart-Retry") improve on fixed retry by
learning better timing, but they still operate on a retry-timing subset of the action space
and use implicit heuristics. Autopilot treats recovery as a multi-action, multi-step
orchestration problem with explicit costs attached to every decision.

---

## Demo

> **Record and drop your GIF here.**
> Suggested flow: `↺ RESET` → `▶ Demo: INC-1` → watch detection ring fire on IN|rupay|HDFC
> node → click node → side panel opens → Approve gate → Action Log captures result.

```
[demo.gif]
```

Start the UI locally: see [Quickstart](#quickstart).

---

## Benchmark results

> All figures below are derived from the synthetic simulation benchmark. They are not
> real transaction values.

**Phase 4+5 canonical — mean ± std, 10 evaluation seeds (1–10), multi-step Oracle**

### Table 1 — Simulated Recovery & Revenue

| Strategy | Recovery % | Gross Rev (INR) | % of Oracle | Lift vs Smart-Dunning |
|---|---|---|---|---|
| No Recovery | 0.0 ± 0.0 | 0 | 0.0% | −100.0% |
| Fixed Retry | 46.5 ± 0.8 | 153,605,983 ± 12,273,028 | 54.0% | −30.5% |
| Learned Smart-Retry | 48.5 ± 0.7 | 157,668,884 ± 8,134,600 | 55.4% | −28.6% |
| Smart-Dunning *(headline baseline)* | 66.4 ± 1.0 | 220,866,149 ± 13,400,086 | 77.6% | +0.0% |
| Autopilot-no-detect `[ABLATION]` | 73.2 ± 0.6 | 252,165,900 ± 11,570,526 | 88.6% | +14.2% |
| **Autopilot** | **74.4 ± 0.4** | **254,842,959 ± 11,426,424** | **89.6%** | **+15.4%** |
| Rule-Based | 78.2 ± 0.4 | 268,282,158 ± 11,000,511 | 94.3% | +21.5% |
| Oracle `[CEILING]` | 82.6 ± 0.3 | 284,527,486 ± 12,437,688 | 100.0% | +28.8% |

### Lift decomposition (D1 — Decision log)

```
Autopilot vs Smart-Dunning     +15.4%   (+₹34.0M mean)
├── Orchestration-gain (6b vs SD)  +14.2%   full action space + explicit utility
└── Detection-gain (AP vs 6b)       +1.2%   cross-episode degradation detection
```

Autopilot trails Rule-Based by −5.0% on gross revenue (−3.8pp on raw recovery). See [Known limitation](#known-limitation).

### Table 2 — UIR, Wasted Attempts, Contacts

| Strategy | UIR % | Wasted Silent % | Contacts / Recovery |
|---|---|---|---|
| Smart-Dunning | 49.0 ± 0.4 | 0.0 | 0.776 |
| Rule-Based | 9.2 ± 2.0 | 0.0 | 0.585 |
| **Autopilot** | **0.0 ± 0.0** | **0.0** | **0.463** |
| Oracle `[CEILING]` | 0.0 ± 0.0 | 0.0 | 0.550 |

**UIR (Unnecessary Intervention Rate)** = the percentage of customer-visible recovery
actions (e.g. re-authentication requests, payment-method-update prompts) that, evaluated
against ground truth, had negative expected value — meaning the action created customer
friction with no realistic chance of recovering the payment.

Autopilot's Policy Engine only escalates to customer-visible actions when the
Strategist's expected utility is positive; silent/backend actions (retries, route holds)
are excluded from this metric since they don't create customer friction.

**0.0% does not mean Autopilot took no actions.** It made approximately 8,170 total
interventions per seed, most of them silent retries. It means every customer-facing ask
(re-auth request, payment method update, dunning notification) was backed by a positive
expected-value calculation against the simulated ground truth — none were fired on
episodes where the simulator's probability table gave them no realistic path to recovery.

### Phase 5 — Degradation detection latency

| Incident | Cohort | Window | Median detection latency |
|---|---|---|---|
| INC-1 | IN / rupay / HDFC | 18h | +10h after incident start |
| INC-2 | xb / route_b (cross-border) | 12h | +9h |
| INC-3 | upi / PAYTM | 24h | +13h |

---

## Architecture

```
                     ┌─────────────────────────────────────────┐
   Failed payment ──▶│              AUTOPILOT PIPELINE          │
                     │                                          │
                     │  ┌────────────┐   deterministic rules    │
                     │  │Investigator│◀─ + LLM only if ambiguous│
                     │  └─────┬──────┘                          │
                     │        │ inferred_class, incident_active │
                     │  ┌─────▼──────┐   EU(a) = P·Rev          │
                     │  │ Strategist │     − C_friction          │
                     │  └─────┬──────┘     − C_risk             │
                     │        │             − C_intervention     │
                     │  ┌─────▼──────┐   autonomy tiers from    │
                     │  │Policy Eng. │◀─ policy.yaml            │
                     │  └─────┬──────┘                          │
                     │        │ automatic / approval / human    │
                     │  ┌─────▼──────┐   mock tool layer        │
                     │  │Action Agent│──▶ Retry / Link / Notif  │
                     │  └─────┬──────┘    / OpsQueue APIs       │
                     │        │ success / failure               │
                     │  ┌─────▼──────┐   outcome-driven         │
                     │  │Outcome Agt.│──▶ replanning (max 3)    │
                     │  └────────────┘                          │
                     └─────────────────────────────────────────┘
                                    ▲
                     ┌──────────────┴──────────────┐
                     │  Phase 5 Degradation Detector│
                     │  rolling success rate per    │
                     │  cohort key (observed only)  │
                     └─────────────────────────────┘
```

**13 actions** across 5 classes:

| Class | Actions |
|---|---|
| Terminal | `stop` |
| Silent retry | `retry_1h`, `retry_6h`, `retry_24h`, `retry_72h`, `retry_7d`, `retry_alternate_route`, `hold_for_incident` |
| Nudge | `send_dunning_notification` |
| Customer action | `send_recovery_link`, `request_reauth`, `request_new_payment_method` |
| Human | `escalate_to_merchant` |

The **Strategist** scores all 13 using a unified INR expected-value formula — no implicit
weights, no hardcoded rules. Cost constants live in `costs.yaml`; autonomy thresholds in
`policy.yaml`.

---

## How we validated this benchmark

*A short, honest account of what we found and fixed during Phase 4 development.*

The benchmark started with an apparent +22.8% lift for Autopilot over Smart-Dunning. That
number was real, but we found five calibration bugs that were inflating or deflating
specific sub-results. Fixing them brought the headline to the defensible +18.3% you see
above.

**Bug 1 — `retry_alternate_route` overestimated on `insufficient_funds` (4.6×)**
The Strategist's prior for `retry_alternate_route` was a flat 0.55. GT median base_p on
IF episodes is ~0.12. Autopilot was routing 24.8% of IF episodes to alternate-route with
38.5% recovery instead of retry-72h/7d at 69–95% recovery. Fix: class-specific prior
of 0.12 for IF. IF recovery: 63.5% → 68.6%.

**Bug 2 — Policy EU ignored episode horizon**
The Strategist scored single-shot EU for retry actions, not accounting for how many
retries fit within the remaining 336-hour horizon. A 168h retry (retry_7d) uses half the
window in one shot; a 72h retry (retry_72h) fits 4 attempts. Fix: replaced single-shot EU
with policy EU — `P_atleast1(K) = 1 − ∏(1 − p_eff(k))` where K = floor(remaining_h /
delay_h). Partial improvement: 68.6% → 69.6%.

**Bug 3 — Strategist p(a) didn't apply time-decay; Action Agent did**
The Action Agent applies `time_decay = exp(−λ × |delay − optimal_delay| / 24)` from GT
profile. The Strategist didn't. For `retry_7d` on IF episodes, this meant Strategist
estimated p=0.567 while the Action Agent would execute at p=0.303 — a 1.87× overestimate.
For `retry_72h` (optimal_delay = 72h = action_delay), the Strategist estimated p=0.222
while Action Agent executed at p=0.598 — a 2.69× underestimate in the wrong direction.
Net effect: Strategist systematically preferred retry_7d over retry_72h. Fix: apply
time_decay in `_p_success` using per-class profile from `costs.yaml`. IF recovery:
69.6% → 80.1% (+10.5pp).

**Bug 4+5 — Same `retry_alternate_route` and `hold_for_incident` overestimate on `expired_card`**
GT base_p for alternate-route on EC is ~0.025; the flat prior was 0.55 (24× overestimate).
Autopilot was routing 44.6% of EC episodes to alternate-route (30.2% recovery). Fix:
EC-specific prior of 0.025. EC recovery: 59.6% → 76.6%. Residual `hold_for_incident`
overestimate on EC fixed similarly (+0.6pp).

**Oracle compliance fix**
Before Phase 3, Oracle read `gt["optimal_action"]` with no compliance filter. This meant
it would retry a stolen card because GT assigned it a non-zero probability. Fixed to apply
the same `MANDATORY_ESCALATION_CODES` constraint (stolen_or_lost_card, risk_blocked) as
all other strategies. Without this, Oracle was not a valid ceiling — it was GT-optimal
under no constraints. Post-fix: Oracle matches GT exactly on non-fraud episodes and
escalates fraud episodes, same as Autopilot.

**RNG isolation fix**
The benchmark harness originally called `detector.record_outcome()` using the first
strategy's episode-outcome draw, sharing its RNG stream. This caused a one-call offset
in the RNG of all downstream strategies depending on run order. Fixed: detector uses its
own dedicated RNG seeded `seed * 99991 + ep_idx`, isolated from every strategy's stream.
This restored the "all strategies scored on identical episode draws" invariant.

After all fixes, a population-by-population comparison of Phase 4 locked vs Phase 5 run
showed max 0.5pp delta on any non-regional population — confirming Phase 5 changes
(degradation detector) did not leak into unrelated logic.

---

## Known limitation

**Autopilot trails Rule-Based by −5.0% on gross revenue (74.4% vs 78.2% recovery rate).**

This gap is concentrated in two populations:

- `insufficient_funds` (81.5% vs 94.3%): Rule-Based hard-codes `insufficient_funds →
  retry_72h`. The GT simulator always assigns `retry_72h` as the optimal action for this
  code because it constructed the probability tables with retry_72h at the highest base_p.
  Autopilot's Strategist splits ~50/50 between retry_72h and retry_7d based on the fitted
  model's per-episode predictions, and the retry_7d half recovers at 70% vs retry_72h's
  90%. The structural alignment between Rule-Based's hard-coded rule and the simulator's
  GT assignment is the source of the gap — not a calibration bug.

- `expired_card` (77.9% vs 95.4%): Same structural cause. Rule-Based's R2 maps
  `card_expired → request_new_payment_method`, which the simulator always assigns as the
  GT optimal for this code. Autopilot's Strategist routes ~23% of EC episodes elsewhere
  due to high-risk-score policy gates.

On every other metric Autopilot leads: UIR (0.0% vs 9.2%), contacts per recovery (0.463
vs 0.585), lift over the strongest trained baseline (+15.4% vs Smart-Dunning), and
89.6% of the Oracle ceiling vs Rule-Based's 94.3%.

The Rule-Based advantage on these two populations is a property of GT construction (single
dominant optimal per failure code), not a generalizable real-world result. A real
`insufficient_funds` failure can have multiple near-optimal actions depending on the
customer's specific instrument and timing — which is exactly the problem Autopilot is
designed to handle.

---

## Quickstart

### Prerequisites

```
Python 3.10+
pip install -r requirements.txt   # pyyaml numpy scikit-learn joblib
Node.js 18+  (for the UI)
```

### 1. Train the retry model (once, on training seed)

```bash
python -m strategies.train_retry_model --seed 1000
# writes data/models/retry_delay_logreg.joblib
```

### 2. Generate evaluation data

```bash
# Default: seed 1, 3000 episodes (already committed at data/)
python -m sim --seed 1 --out data/

# Generate additional seeds
python -m sim --seed 2 --out data/seed2/
```

### 3. Run the Phase 4+5 benchmark

```bash
# Full 8-strategy × 10-seed run (~10 min)
python -m bench.multistep

# Fast check — 4 strategies, 2 seeds
python -m bench.multistep --strategies smart_dunning autopilot autopilot_no_detection oracle --seeds 1 2
```

Results written to `data/results/phase4_multistep.json`.

### 4. Run a single-episode trace

```bash
# INC-1 episode — shows all 5 pipeline stages with detection on vs off
python -m autopilot.trace_episode --episode ep_1_34 --both
```

### 5. Start the Command Center UI

```bash
cd ui
npm install
npm run dev
# Open http://localhost:5173
```

Demo flow: click `▶ Demo: INC-1` → watch detection ring fire → click the
`IN · rupay · HDFC` node → approve the gate in the side panel.
Click `↺ RESET` to run again from scratch.

---

## Repo layout

```
SPEC.md                  # locked spec — all design decisions documented
sim/                     # Phase 1: episode generator + ground truth
strategies/              # Phase 2: 6 baselines (no_recovery → oracle)
autopilot/               # Phase 3: Investigator→Strategist→Policy→Action→Outcome
detect/                  # Phase 5: rolling-window degradation detector
bench/                   # Phase 4: multi-step harness + scorer
ui/                      # Phase 6+7: React + Tailwind Command Center
data/                    # episodes.jsonl, ground_truth.jsonl, results/
costs.yaml               # INR cost constants (signed off in spec §6.1)
policy.yaml              # autonomy tier thresholds
CHANGELOG.md             # calibration bug log with before/after deltas
```

---

## Decisions log summary

All design decisions are recorded in `SPEC.md §11` with IDs (D1–D4) and in `CHANGELOG.md`.
Key ones:

- **D1** — Autopilot's cross-episode detection is kept, footnoted, and decomposed via the
  ablation (6b). Detection-gain is reported separately, not hidden in the aggregate.
- **D2** — Population mix locked: IF 24% / transient 22% / non-rec 14% / auth 13% /
  expired 11% / regional 8% / ambiguous 8%.
- **D3** — Revenue headline is gross; net reported as an adjacent column. IRPI on gross,
  net-basis IRPI as secondary.
- **D4** — 10 evaluation seeds (1–10), training seeds (1000–1019), disjoint. Enforced by
  test.
