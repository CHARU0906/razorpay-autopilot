# Razorpay Autopilot

**The hard part of payment recovery isn't detecting failures — it's knowing when not to bother the customer while still getting the money back.**

Autopilot treats recovery as a utility maximization problem: **EU(a) = P(a)·Revenue − C_friction − C_risk − C_intervention**. Every action is scored in INR. Customer-visible actions only win when their expected revenue minus friction cost exceeds the best zero-friction alternative.

**Why this matters — three things a skimmer should know:**

- **0.0% UIR on synthetic benchmark.** ~8,174 interventions per seed, zero customer-visible requests dispatched on episodes where recovery was impossible or a silent retry was equally effective. Not passive — selective.
- **+14.74% gross lift over Smart-Dunning** (Regime A, 10 seeds, synthetic). Rule-Based beats us in homogeneous setups — that's intentional and [explained below](#regime-a-vs-regime-b). The meaningful result is Regime B, where heterogeneous customer cohorts (simulated) break Rule-Based and Autopilot holds.
- **Closed-loop, not single-shot.** Investigator → Strategist → Policy Engine → Action Agent → Outcome Agent. Failed actions trigger replanning. A promise-to-pay commitment schedules a lifecycle check. The system knows when to stop.

> **Synthetic simulation only.** Every number here comes from a simulator we built. No production Razorpay APIs or live transaction data were used. See [Honest Limitations](#honest-limitations) for exactly what real validation would require — stated up front because it's a feature, not a disclaimer.

[![UI Demo](https://img.shields.io/badge/Demo-Command_Center_UI-blue)](http://localhost:5173)
[![Reproduce](https://img.shields.io/badge/Benchmark-One--Shot_Reproduction-green)](#quickstart)

---

## Table of Contents
1. [The One Incident Walkthrough](#the-one-incident-walkthrough)
2. [Second Walkthrough: Promise-to-Pay Tracker](#second-walkthrough-promise-to-pay-tracker)
3. [Regime A vs Regime B](#regime-a-vs-regime-b)
4. [Honest Limitations](#honest-limitations)
5. [Judge FAQ](#judge-faq)
6. [Quickstart](#quickstart)
7. [Appendix: Statistical Suite](#appendix-statistical-suite)

---

## The One Incident Walkthrough

The demo is built around a single real example: **INC-1**, a correlated degradation on the
`IN · rupay · HDFC` cohort at sim_hour ≈ 240.

**Run it:** click `🟡 Demo 2: Watch Degrading Trend` in the UI, then play forward.

**What happens, stage by stage:**

**1. Detection.** The rolling success rate on the HDFC RuPay cohort drops 0.94 → 0.82
across 80 episodes. The detector fires after ~7.5 sim-hours. This is a cross-episode
signal unavailable to per-transaction strategies — the baselines can't see it.

**2. Diagnosis — Stage 1 (Investigator).** Click the node → WHY? tab:
- Signal: `failure_code=issuer_down` on cohort `[IN|rupay|HDFC]`
- Ruled out: customer insolvency, card expiry, 3DS authentication gap
- Confirmed: infrastructure degradation (NOT customer failure)
- Consequence: customer friction actions blocked

**3. Scoring — Stage 2 (Strategist).** Three competing actions, all zero-friction:

```
retry_1h               EU = 7,261.86 INR   P=0.745
retry_alternate_route  EU = 6,969.64 INR   P=0.720
hold_for_incident      EU = 1,167.44 INR   P=0.310
```

EU(a) = P(a)·Revenue − C_friction − C_risk − C_intervention, all in INR.
`retry_1h` wins. No customer contact dispatched regardless of which action wins —
all three are zero-friction by construction on this inferred class.

**4. Policy Gate — Stage 3 (Policy Engine).** `tier=automatic`. No human needed.
Compare: the `ep_1_1406` card (auth-required, `risk_score=0.920 ≥ 0.850`) triggers
`requires-human` — same policy logic, different threshold crossing.

**5. Execution + Replanning — Stages 4–5.** `retry_1h` → MockRetryAPI (simulated, not
a live API). Attempt 1 fails (p_eff=0.407 under incident degradation). Outcome Agent
triggers replanning. Attempt 2 succeeds (p_eff=0.356). **₹9,751.87 recovered.**
(episode `ep_1_34`, `amount_inr=9751.87` in `data/episodes.jsonl`)

**Why this matters vs the baselines:**
- Smart-Dunning dispatches a dunning notification (customer-visible) on the INC-1 cohort
  as a standard step — no cross-episode detection.
- Rule-Based has no replanning loop and no incident detection.
- Autopilot suppresses customer friction because the infrastructure signal makes
  friction-bearing actions EU-negative regardless of their individual recovery probability.

---

## Second Walkthrough: Promise-to-Pay Tracker

The same EU(a) framework applies beyond infrastructure incidents. This walkthrough shows it on a different failure surface: **a monthly subscriber who can't pay today but will pay on salary day**.

**Run it:** `py -m bench.test_promise_tracker` (3/3 passing, verified)

**Episode:** An `insufficient_funds` failure on a monthly recurring subscriber. The retry-delay model scores `retry_7d` as the EU winner after the initial `retry_72h` fails.

**What the EU function sees — after retry_72h fails on replan #1:**

```
retry_7d               EU = 94,541.90 INR   P=0.476   [model-scored]
send_recovery_link     EU = 83,771.73 INR   P=0.418   C_friction=232.75
send_dunning_notif     EU = 66,466.49 INR   P=0.331   C_friction=58.19
```

(Episode `ep_1_8`: amount=₹2,01,316, LTV=₹34,096, billing_cycle=monthly, avg_days_between_txns=39.9d)

**Why send_recovery_link matters here:** When the customer responds to the recovery link and commits to pay on salary day, the Action Agent logs this as `log_promise_to_pay` via MockPromiseAPI — scheduling the commitment with a grace window rather than burning more retry attempts.

**The Promise-to-Pay lifecycle, stage by stage:**

**Case A — Customer fulfills (happy path):**
1. Customer receives recovery link, commits to pay in 72h (salary day)
2. `log_promise_to_pay(due_in_hours=72, channel=whatsapp)` → MockPromiseAPI logs commitment
3. At due timestamp: payment clears → Outcome Agent closes episode as SUCCESS, 0 additional contacts
4. Log: `✓ Promise-to-Pay FULFILLED on time (due_h=72.0h, attempt=1) — recovered`

**Case B — Customer doesn't pay (broken promise):**
1. Grace window expires without settlement
2. Outcome Agent marks `promise_broken=True`, increments `replan_count=1`
3. Strategist replans: `promise_broken` flag raises friction tolerance → escalate or high-urgency recovery link
4. Log: `✗ Promise-to-Pay BROKEN — feeding back into replanning loop (replan #1)`

**Why this is the same architecture, not a separate feature:**

The EU(a) decision to `send_recovery_link` vs `retry_7d` vs `send_dunning_notification` is made by the same Strategist, using the same C_friction cost term (₹232.75 vs ₹58.19 vs ₹0), the same Policy Engine autonomy tiers, and the same Outcome Agent replanning loop. Promise-to-Pay tracking is what happens inside the `send_recovery_link` execution path — it's a downstream lifecycle state machine, not a separate decision system.

**Verified:** `py -m bench.test_promise_tracker` passes 3/3:
- PromiseTracker core lifecycle (register, active, fulfilled, broken)
- Case A: fulfilled promise closes episode as SUCCESS (terminal=True)
- Case B: broken promise triggers replan #1 with `promise_broken=True` in state

---

## Regime A vs Regime B

### The Setup

**Regime B (Heterogeneous GT) — the realistic case:** Optimal recovery depends on hidden per-customer context — billing cadence, alternate instruments on file, network token type. Rule-Based can't adapt.

**Regime A (Homogeneous GT) — the honest counter-case:** The simulator assigns one dominant optimal action per failure code. Rule-Based's hardcoded rules match this by construction — structural alignment, not signal.

### Results (10 Seeds, Synthetic Simulator)

**Regime B first — this is the case that reflects real-world customer variation:**

| Strategy | Regime B Recovery | Regime B % Oracle | Regime B UIR |
|---|---|---|---|
| Smart-Dunning | 68.1 ± 0.6% | 78.9% | 61.8% |
| **Rule-Based** | 66.6 ± 0.8% | 77.6% | **38.9%** |
| **Autopilot** | **70.4 ± 0.5%** | **85.1%** | **0.0%** |
| Oracle `[CEILING]` | 84.7 ± 0.4% | 100% | ~0.1% |

**Rule-Based collapses in Regime B** (from 78.3% in Regime A to 66.6% here, UIR rises to 38.9%):

1. **Salary cycle mismatch.** Monthly subscribers need `retry_7d` (salary-cycle alignment). Rule-Based fires `retry_72h` unconditionally, exhausts attempts. Autopilot conditions on `avg_days_between_txns` and `billing_cycle`.

2. **Alternate instrument blindness.** Expired-card customers with a backup instrument can be recovered silently via `retry_alternate_route` (zero friction). Rule-Based fires `request_new_payment_method` on every expired card. Autopilot checks `has_alternate_instrument_on_file` and prices C_friction explicitly.

3. **No replanning.** Rule-Based picks one action and stops. Autopilot's Outcome Agent feeds failure back into the Strategist for up to 3 replanning cycles.

**Statistical significance vs Rule-Based in Regime B:** paired t=+10.46, p=2.46×10⁻⁶ across 10 seeds. Autopilot vs Smart-Dunning in Regime B: t=+7.62, p=3.26×10⁻⁵.

---

**Regime A — the honest counter-case (Rule-Based wins here, by construction):**

| Strategy | Regime A Recovery | Regime A % Oracle |
|---|---|---|
| Smart-Dunning | 65.9 ± 0.6% | 77.9% |
| **Rule-Based** | **78.3 ± 0.5%** | **93.4%** |
| **Autopilot** | 74.4 ± 0.3% | 89.5% |
| Oracle `[CEILING]` | 82.4 ± 0.5% | 100% |

**Rule-Based wins Regime A by design.** Its rules (`insufficient_funds → retry_72h`, `card_expired → request_new_payment_method`) match exactly what the simulator's GT assigns as optimal for a homogeneous cohort. That's structural alignment, not a signal advantage. Autopilot's logistic regression doesn't hard-code these mappings, which costs ~12pp against a simulator built with a unique optimal action per class.

> The full technical explanation of why Rule-Based leads on `insufficient_funds` and `expired_card` specifically is in `SUMMARY.md §Why Rule-Based leads on two populations`.

---

## Honest Limitations

**Everything here is synthetic.** The simulator produces realistic episode structure, but
outcome probabilities, population mix, and optimal action labels all come from our own
generator. Beating our simulator is not the same as beating a real dunning stack.

**What real validation requires:**

| Step | Description | Status |
|---|---|---|
| Shadow logging | Run recommendations alongside existing dunning (no execution) for ≥3 months | Not started |
| Calibration check | Verify P(success\|a) estimators have real-world signal on actual recovery outcomes | Not started |
| Canary A/B | 5–10% traffic with circuit breakers: halt if live UIR > 1% or recovery drops below baseline | Not started |

**What we can and cannot claim:**

| Claim | Status |
|---|---|
| EU(a) is a valid decision framework for this problem | ✓ Design claim, grounded in first principles |
| 0.0% UIR on synthetic benchmark | ✓ Verified — deterministic by design on our simulator |
| +14.74% lift over Smart-Dunning on synthetic data (Regime A, 10 seeds) | ✓ On our simulator, confirmed reproducible |
| Rule-Based degrades on heterogeneous cohorts | ✓ On this simulator; mechanism is documented and plausible |
| Any result holds on real Razorpay transaction data | ✗ Not tested. Requires shadow-mode validation |
| Production-ready | ✗ MockRetryAPI is not a live API. No live integration exists |

> **Reproducibility note (2026-09-04):** All benchmark results in this README were regenerated
> from scratch on this date. During pre-submission verification, a hash-randomization
> nondeterminism bug was found in `bench/multistep.py` (`hash(name) % 1000` used
> Python's PYTHONHASHSEED-dependent `hash()`) and fixed by replacing it with
> `zlib.crc32(name.encode()) % 1000` — a stable, seed-independent hash. Every number
> below is from a confirmed-stable run (identical output across 3 consecutive runs).

---

## Judge FAQ

**Q1: Why not just use Rule-Based's action mapping as a prior?**

Rule-Based wins where the simulator has a unique optimal action per failure class. It fails
where optimal recovery depends on per-episode customer context — billing cadence, alternate
instruments, token type. The Regime B result is the evidence: 78.3% → 66.6% recovery,
UIR rising to 38.9%. Autopilot's EU function sees the per-episode context; the rule table
can't.

**Q2: What would it actually take to run this in production?**

The decision logic is separated from the tool layer, so swapping `MockRetryAPI` for real
APIs is architecturally straightforward. The hard part is calibrating `P(success|a)` against
real outcome distributions — those priors are currently fit on synthetic data. The
`_class_action_fit` multipliers in `strategist.py` and every constant in `costs.yaml`
need shadow-mode validation before any production traffic. We don't have that yet.
Shadow logging is the minimum next step, not production deployment.

**Q3: How does this scale beyond 13 actions?**

The Strategist scores actions independently via EU(a) = P(a)·Rev − ΣC. Adding a 14th
action requires defining its P(success|a) estimator and its cost vector in `costs.yaml`.
The calibration work doesn't disappear, but the architecture accommodates it cleanly.

**Q4: What is the computational cost?**

Deterministic classification + logistic regression scoring are the dominant cost paths.
LLM fallback (stub in demo mode) triggers on <8% of volume — ambiguous failure codes
where deterministic confidence < 0.60. The stub is a keyword-matching fallback, not a
live LLM call. No latency benchmark exists in the repo; the <2.5ms figure previously
cited was an estimate and has been removed. See the 🧠 LLM panel in the UI for an honest
account of what the stub does and doesn't do.

**Q5: Are n=10 seeds statistically adequate?**

The paired bootstrap 95% CI is `[+11.95%, +17.89%]` (Regime A vs Smart-Dunning),
paired t=+9.98, p=3.65×10⁻⁶. The effect is large enough that 10 seeds is not the
binding constraint. However: all 10 seeds use the same simulator, same population mix,
same incident structure. Statistical significance within the simulator doesn't transfer
to real-world significance.

**Q6: UIR=0.0% — is Autopilot passive?**

No. ~8,174 total interventions per seed in Regime A (8,802 in Regime B). 0.0% UIR means
zero customer-visible requests dispatched on episodes where ground truth had zero recovery
probability, or where a silent retry was equally effective. The Strategist's EU computation
includes C_friction; customer-visible actions only win when their expected revenue minus
friction cost exceeds the best zero-friction alternative.

**Q7: Does the WHY? tab show real values?**

Yes. The causal chain renders actual `InvestigatorResult` output — `inferred_class`,
`confidence`, `flags`, `eliminated_hypotheses` — computed by `investigator.py` from
the observed episode fields. Strategist EU scores in the trace log are real outputs from
`strategist.py`. No values are fabricated in the UI layer.

**Q8: Is the Razorpay integration live?**

The integration layer is built and tested against Razorpay's documented API contract — webhook schema, HMAC-SHA256 signature validation logic, and the Payment Links endpoint structure. We did not complete live verification because that requires KYC/PAN submission to obtain test credentials, which we chose not to do for a hackathon test integration. This is architecturally ready and contract-verified locally, not yet live-API-verified.

**Q9: How does the same EU(a) framework extend to Promise-to-Pay and other revenue-leak surfaces?**

The EU function is not specific to payment failures. The same formula — EU(a) = P(a)·Revenue − C_friction − C_risk − C_intervention — applies to any recovery surface where actions have measurable friction costs and success probabilities.

For Promise-to-Pay: the decision to send a recovery link vs. retry silently vs. send a dunning notification is made by the same Strategist, with C_friction pricing in the expected CLV cost of contacting the customer. Once the customer commits, `log_promise_to_pay` extends the episode lifecycle — tracking whether the commitment was fulfilled and triggering high-urgency replanning if broken. The Outcome Agent's replanning loop handles both paths.

For checkout drop-off recovery (not built): the same EU(a) formulation and 5-stage pipeline would apply in principle — a drop-off event maps to a failure class, the Strategist scores recovery actions against their friction costs, and the Policy Engine gates customer-visible actions. However, none of this has been implemented: no checkout drop-off episode generator, no failure codes, no Investigator rules, and no P(success|a) estimators for that surface exist in this repo. This is an architectural claim about extensibility, not a statement about something that's been built or tested.

---

## Quickstart

```bash
# Prerequisites: Python 3.10+, Node.js 18+
pip install -r requirements.txt   # pyyaml numpy scikit-learn joblib scipy fastapi uvicorn razorpay

# Start the Command Center UI
cd ui && npm install && npm run dev
# Open http://localhost:5173

# (Optional) Start the live EU trace API + Razorpay integration backend
py -m api.server
# Required for the EU(a) tab, Regime A vs B toggle, and Razorpay integration panel

# (Optional) Enable live Razorpay test-mode API calls
# Copy .env.example to .env and add your rzp_test_... keys
# Then restart py -m api.server

# Reproduce all benchmark results
py -m bench.reproduce_all
```

**Demo walkthrough (2 minutes):**
1. Open http://localhost:5173 — starts before INC-1 detection fires (sim_h=244.0)
2. Click `▶ PLAY SIM` — watch the HDFC RuPay node degrade from amber to red
3. Click the `IN · rupay · HDFC` node → STATUS & ACTIONS for incident detail
4. Click WHY? (DIAGNOSIS) for the 5-step causal chain
5. Use Approve/Reject on the gated episode card (outcome is deterministic per episode)
6. Click `🧠 LLM (SIMULATED)` for the honest account of what the LLM stub does
7. Click `⚖ REGIME A vs B` and `▶ Run Live` to watch Rule-Based degrade in Regime B
8. Click `� P2P TRACKER` for the Promise-to-Pay second walkthrough with EU scoring
9. Click `�🔌 RAZORPAY API` to see integration status (contract-implemented, not live-verified)

All tools are mocked (`MockRetryAPI`, `MockOpsQueue`, etc.) — no live API calls unless
`RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` are configured (see `.env.example`).

---

## Razorpay Test-Mode Integration

**What this is:** The integration layer in `razorpay_integration/` is fully implemented against Razorpay's documented API contract: `payment.failed` webhook payload schema, HMAC-SHA256 signature validation, and the `POST /v1/payment_links` endpoint. The code structure, field mapping, and error-handling follow Razorpay's published test-mode documentation.

**What has NOT been verified:** This integration has not been tested against Razorpay's live test infrastructure. Live test-mode verification requires KYC/PAN submission to obtain `rzp_test_...` credentials — that was deliberately not pursued for this hackathon submission.

**What IS verified:**

| Component | Verified how |
|---|---|
| `payment.failed` payload parsing → observed-episode translation | ✓ Local test with representative payload matching Razorpay's documented schema |
| EU pipeline execution on translated payload | ✓ Full Investigator → Strategist → Policy pipeline runs correctly |
| Mock fallback behavior (no credentials) | ✓ Returns clearly-labeled mock responses |
| HMAC-SHA256 signature validation logic | ✓ Implemented per Razorpay's published spec; not tested against a real signed payload |
| `POST /v1/payment_links` API call | ✓ Implemented using razorpay-python 2.0.1 SDK; not called against api.razorpay.com |

**What you can demo on camera (honestly):**

```bash
# Show the webhook handler parsing a documented payload and running the EU pipeline
py -m razorpay_integration.demo_local

# Show the integration layer responding correctly to /razorpay/status
py -m api.server
# then: curl http://localhost:8000/razorpay/status
```

This is architecturally ready and implemented against Razorpay's contract. It is not a live API integration — label it accordingly on camera.

---

## Appendix: Statistical Suite

### A1. Hypothesis Testing (10 Seeds, Stable Run — zlib.crc32 fix applied)

| Comparison | Regime | Paired t-stat | p-value | Bootstrap 95% CI | Significance |
|---|---|---|---|---|---|
| Autopilot vs Smart-Dunning | A | t=+9.98 | p=3.65×10⁻⁶ | [+11.95%, +17.89%] | p < 0.001 |
| Autopilot vs Smart-Dunning | B | t=+7.62 | p=3.26×10⁻⁵ | [+6.07%, +10.21%] | p < 0.001 |
| Autopilot vs Rule-Based | B | t=+10.46 | p=2.46×10⁻⁶ | [+7.69%, +11.31%] | p < 0.001 |
| Autopilot vs Rule-Based | A | t=−7.47 | p=3.81×10⁻⁵ | [−5.32%, −3.14%] | p < 0.001 (negative — RB wins) |

Wilcoxon signed-rank W=0.0 (p=0.00195) for all comparisons except Autopilot vs RB in
Regime B where W=0.0 (p=0.00195 also). Run: `py -m bench.statistical_rigor`

### A2. Lift Decomposition

```
Autopilot vs Smart-Dunning     +15.08% Gross Lift   (ablation-baseline, 10 seeds)
├── Orchestration-gain (6b vs SD)  +14.23%   Full 13-action EU + horizon policy
└── Detection-gain (AP vs 6b)       +0.85%   Cross-episode incident detection
```

Detection-gain is modest (0.85%) because only 240/3,000 episodes (8%) are in incident
clusters. The detector is correct and working; the gain reflects the episode mix.

Mean gross revenue lift (statistical_rigor run): **+14.74%** over Smart-Dunning (Regime A).
The ablation baseline (+15.08%) uses a separately recomputed SD denominator; both figures
are from the same fixed-seed runs and are self-consistent within their respective scripts.

### A3. Cost Sensitivity (±20% Perturbations, Seeds 1–5)

All 9 perturbations produce 0.0% UIR. Lift vs Smart-Dunning bounded
**[+12.77%, +14.14%]** across all perturbations including simultaneous ±20% on all cost
constants. Run: `py -m bench.sensitivity`

| Cost Perturbation | Autopilot Recovery % | UIR % | Lift vs Smart-Dunning |
|---|---|---|---|
| Nominal Baseline (0%) | 74.51% | 0.0% | +13.16% |
| C_friction +20% | 74.16% | 0.0% | +13.40% |
| C_friction −20% | 75.03% | 0.0% | +13.00% |
| C_risk +20% | 74.55% | 0.0% | +13.02% |
| C_risk −20% | 74.51% | 0.0% | +13.15% |
| C_intervention +20% | 74.58% | 0.0% | +12.77% |
| C_intervention −20% | 74.41% | 0.0% | +14.14% |
| All Costs +20% | 74.32% | 0.0% | +13.60% |
| All Costs −20% | 74.98% | 0.0% | +13.98% |

### A4. Component Ablation (10 Seeds)

| Configuration | Recovery % | Lift vs SD | Delta vs Full AP |
|---|---|---|---|
| Full Autopilot | 73.67% | +15.08% | — |
| Without Degradation Detection (6b) | 73.35% | +14.23% | **−0.74%** |
| Without Horizon Policy EU | 70.07% | +7.38% | **−6.70%** |
| Without Time-Decay Calibration | 71.36% | +12.01% | **−2.67%** |
| Without Calibrated Priors† | 73.67% | +15.08% | 0.00% |
| Without Policy Engine Tiers† | 73.67% | +15.08% | 0.00% |

† Ablations 4 and 5 show 0.00% delta: the `flat_priors` and `unconstrained_autonomy`
monkeypatches in `bench/ablation.py` do not take effect in the current implementation
because `_COSTS` is reloaded and `policy.apply` is re-imported within the run loop.
These ablation configurations are not currently producing meaningful isolation — treat
them as not-yet-implemented rather than as confirming those components have no effect.
Horizon Policy EU (ablation 2, −6.70%) is the single most load-bearing component.

Run: `py -m bench.ablation`

### A5. Feature Provenance & Leakage Audit

All 7 features conditioned on by Autopilot verified CLEAN (upstream of GT optimal_action
generation, no statistical label leakage). Run: `py -m bench.leakage_audit`

### A6. Full UIR & Friction Table

**Regime A (10 Seeds, Homogeneous GT):**

| Strategy | UIR % | Contacts / Recovery | Gross Rev (INR) mean |
|---|---|---|---|
| Smart-Dunning | 49.1% | 0.781 | 221,146,385 |
| Rule-Based | 10.1% | 0.586 | 264,568,673 |
| **Autopilot** | **0.0%** | **0.452** | **253,460,956** |
| Oracle `[CEILING]` | 0.0% | 0.560 | 283,285,550 |

**Regime B (10 Seeds, Heterogeneous GT):**

| Strategy | UIR % | Contacts / Recovery | Gross Rev (INR) mean |
|---|---|---|---|
| Smart-Dunning | 61.8% | 0.756 | 226,991,652 |
| Rule-Based | 38.9% | 0.709 | 223,172,665 |
| **Autopilot** | **0.0%** | **0.491** | **244,800,293** |
| Oracle `[CEILING]` | ~0.1% | 0.402 | 287,777,835 |

### A7. Decisions Log

| ID | Decision | Consequence |
|---|---|---|
| D1 | Keep cross-episode detection; decompose lift into orchestration + detection gains | Ablation 6b required |
| D2 | Population mix: IF 24% / transient 22% / non-rec 14% / auth 13% / expired 11% / regional 8% / ambiguous 8% | Fixed in sim_config.yaml |
| D3 | Gross revenue headline; net in adjacent column | IRPI on gross; net-basis IRPI secondary |
| D4 | Eval seeds 1–10; training seeds 1000–1019, disjoint | Enforced by test |
