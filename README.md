# Razorpay Autopilot

> Most payment recovery systems optimize retry timing and recovery rate.
> Autopilot treats recovery as a utility maximization problem:
> **EU(a) = P(a)·Revenue − C_friction − C_risk − C_intervention**.
> On a 3,000-episode synthetic benchmark, this produces measurably less customer friction
> than rule-based systems across heterogeneous customer cohorts — while Rule-Based wins
> on homogeneous setups, which is the expected result and what makes the heterogeneous
> comparison meaningful.

> **Synthetic simulation only.** Every number in this repo is derived from a simulator
> we built ourselves. No production Razorpay APIs or live transaction data were used.
> See [Honest Limitations](#honest-limitations) for what real validation would require.

[![UI Demo](https://img.shields.io/badge/Demo-Command_Center_UI-blue)](http://localhost:5173)
[![Reproduce](https://img.shields.io/badge/Benchmark-One--Shot_Reproduction-green)](#quickstart)

---

## Table of Contents
1. [The One Incident Walkthrough](#the-one-incident-walkthrough)
2. [Regime A vs Regime B](#regime-a-vs-regime-b)
3. [Honest Limitations](#honest-limitations)
4. [Judge FAQ](#judge-faq)
5. [Quickstart](#quickstart)
6. [Appendix: Statistical Suite](#appendix-statistical-suite)

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
triggers replanning. Attempt 2 succeeds (p_eff=0.356). ₹9,751 recovered.

**Why this matters vs the baselines:**
- Smart-Dunning dispatches a dunning notification (customer-visible) on the INC-1 cohort
  as a standard step — no cross-episode detection.
- Rule-Based has no replanning loop and no incident detection.
- Autopilot suppresses customer friction because the infrastructure signal makes
  friction-bearing actions EU-negative regardless of their individual recovery probability.

---

## Regime A vs Regime B

### The Setup

**Regime A (Homogeneous GT):** The simulator assigns one dominant optimal action per failure
code — e.g. every `insufficient_funds` maps to `retry_72h`. Rule-Based's hardcoded rules
match this by construction.

**Regime B (Heterogeneous GT):** Optimal recovery depends on hidden per-customer context —
billing cadence, alternate instruments on file, network token type. Rule-Based can't adapt.

### Results (10 Seeds, Synthetic Simulator)

| Strategy | Regime A Recovery | Regime A % Oracle | Regime B Recovery | Regime B % Oracle |
|---|---|---|---|---|
| Smart-Dunning | 66.4 ± 1.0% | 77.6% | 67.1% | 76.3% |
| **Rule-Based** | **78.2 ± 0.4%** | **94.3%** | 66.9% | 77.4% |
| **Autopilot** | 74.4 ± 0.4% | 89.6% | **70.3%** | **84.2%** |
| Oracle `[CEILING]` | 82.6 ± 0.3% | 100% | 85.3% | 100% |

**Rule-Based wins Regime A. This is intentional and documented.** Rule-Based maps
`insufficient_funds → retry_72h` and `card_expired → request_new_payment_method` — the
same actions the simulator's GT assigns as optimal. That's structural alignment, not
leakage. Autopilot's logistic regression doesn't hard-code these mappings, splitting
~50/50 between `retry_72h` and `retry_7d` on IF — the right behavior for a system that
generalizes, but it costs ~12pp against a simulator built with a unique optimal action.

**Rule-Based collapses in Regime B** (78.2% → 66.9%, UIR rises to 39.8%):

1. **Salary cycle mismatch.** Monthly subscribers need `retry_7d` (salary-cycle alignment).
   Rule-Based fires `retry_72h` unconditionally, exhausts attempts.
   Autopilot conditions on `avg_days_between_txns` and `billing_cycle`.

2. **Alternate instrument blindness.** Expired-card customers with a backup instrument
   can be recovered silently via `retry_alternate_route` (zero friction).
   Rule-Based fires `request_new_payment_method` on every expired card — those
   customer contacts had no chance of being necessary when an alternate instrument existed.
   Autopilot checks `has_alternate_instrument_on_file` and prices C_friction explicitly.

3. **No replanning.** Rule-Based picks one action and stops. Autopilot's Outcome Agent
   feeds failure back into the Strategist for up to 3 replanning cycles.

**Statistical significance vs Rule-Based in Regime B:** paired t=+8.35, p=1.57×10⁻⁵
across 10 seeds.

> **Full explanation of why Rule-Based leads on two Regime A populations** (insufficient_funds
> and expired_card) is in `SUMMARY.md §Why Rule-Based leads on two populations`. The short
> version: the simulator was built with a unique GT optimal action per class, and Rule-Based's
> rules happen to match those actions. A real production environment wouldn't have this
> structural property.

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
| +15.4% lift over Smart-Dunning on synthetic data | ✓ On our simulator, 10 seeds, documented population mix |
| Rule-Based degrades on heterogeneous cohorts | ✓ On this simulator; mechanism is documented and plausible |
| Any result holds on real Razorpay transaction data | ✗ Not tested. Requires shadow-mode validation |
| Production-ready | ✗ MockRetryAPI is not a live API. No live integration exists |

---

## Judge FAQ

**Q1: Why not just use Rule-Based's action mapping as a prior?**

Rule-Based wins where the simulator has a unique optimal action per failure class. It fails
where optimal recovery depends on per-episode customer context — billing cadence, alternate
instruments, token type. The Regime B result is the evidence: 78.2% → 66.9% recovery,
UIR rising to 39.8%. Autopilot's EU function sees the per-episode context; the rule table
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

Deterministic classification + logistic regression scoring: <2.5ms per episode on CPU.
LLM fallback (stub in demo mode) triggers on <8% of volume — ambiguous failure codes
where deterministic confidence < 0.60. The stub is a keyword-matching fallback, not a
live LLM call. See the 🧠 LLM panel in the UI for an honest account of what the stub
does and doesn't do.

**Q5: Are n=10 seeds statistically adequate?**

The paired bootstrap 95% CI is `[+11.67%, +16.60%]`, paired t=+11.54, p=1.07×10⁻⁶.
The effect is large enough that 10 seeds is not the binding constraint. However: all
10 seeds use the same simulator, same population mix, same incident structure. Statistical
significance within the simulator doesn't transfer to real-world significance.

**Q6: UIR=0.0% — is Autopilot passive?**

No. ~8,816 total interventions per seed. 0.0% UIR means zero customer-visible requests
dispatched on episodes where ground truth had zero recovery probability, or where a
silent retry was equally effective. The Strategist's EU computation includes C_friction;
customer-visible actions only win when their expected revenue minus friction cost exceeds
the best zero-friction alternative.

**Q7: Does the WHY? tab show real values?**

Yes. The causal chain renders actual `InvestigatorResult` output — `inferred_class`,
`confidence`, `flags`, `eliminated_hypotheses` — computed by `investigator.py` from
the observed episode fields. Strategist EU scores in the trace log are real outputs from
`strategist.py`. No values are fabricated in the UI layer.

---

## Quickstart

```bash
# Prerequisites: Python 3.10+, Node.js 18+
pip install -r requirements.txt   # pyyaml numpy scikit-learn joblib scipy

# Start the Command Center UI
cd ui && npm install && npm run dev
# Open http://localhost:5173

# Reproduce all benchmark results
py -m bench.reproduce_all
```

**Demo walkthrough (2 minutes):**
1. Open http://localhost:5173 — starts at INC-1 active (sim_h=248.5)
2. Click `🟡 Demo 2` to start at h=244, then `▶ PLAY SIM` — watch degradation and detection fire
3. Click the `IN · rupay · HDFC` node → STATUS & ACTIONS for incident detail
4. Click WHY? (DIAGNOSIS) for the 5-step causal chain
5. Use Approve/Reject on the gated episode card (outcome is deterministic per episode)
6. Click `🧠 LLM (SIMULATED)` for the honest account of what the LLM stub does

All tools are mocked (`MockRetryAPI`, `MockOpsQueue`, etc.) — no live API calls.

---

## Appendix: Statistical Suite

### A1. Hypothesis Testing (10 Seeds)

| Comparison | Regime | Paired t-stat | p-value | Significance |
|---|---|---|---|---|
| Autopilot vs Smart-Dunning | A | t=+11.54 | p=1.07×10⁻⁶ | p < 0.001 |
| Autopilot vs Smart-Dunning | B | t=+7.16 | p=5.28×10⁻⁵ | p < 0.001 |
| Autopilot vs Rule-Based | B | t=+8.35 | p=1.57×10⁻⁵ | p < 0.001 |

Bootstrap 95% CI (Autopilot vs Smart-Dunning, Regime A): `[+11.67%, +16.60%]`.
Run: `py -m bench.statistical_rigor`

### A2. Lift Decomposition

```
Autopilot vs Smart-Dunning     +15.4% Gross Lift   (+₹34.0M mean, 10 seeds)
├── Orchestration-gain (6b vs SD)  +14.2%   Full 13-action EU + horizon policy
└── Detection-gain (AP vs 6b)       +1.2%   Cross-episode incident detection
```

Detection-gain is modest (1.2%) because only 240/3,000 episodes (8%) are in incident
clusters. The detector is correct and working; the gain reflects the episode mix.

### A3. Cost Sensitivity (±20% Perturbations)

Lift vs Smart-Dunning bounded `[+13.7%, +15.1%]` with 0.0% UIR across all perturbations
including simultaneous ±20% on all cost constants. Run: `py -m bench.sensitivity`

### A4. Component Ablation (10 Seeds)

| Configuration | Recovery % | Lift vs SD | Delta vs Full AP |
|---|---|---|---|
| Full Autopilot | 74.40% | +15.38% | — |
| Without Degradation Detection (6b) | 73.20% | +14.17% | −1.05% |
| Without Horizon Policy EU | 69.94% | +5.32% | **−7.44%** |
| Without Time-Decay Calibration | 71.56% | +10.71% | −2.71% |
| Without Calibrated Priors | 73.85% | +13.78% | −0.70% |

Horizon Policy EU is the single largest component: −7.44% when removed.
Run: `py -m bench.ablation`

### A5. Feature Provenance & Leakage Audit

All 7 features conditioned on by Autopilot verified CLEAN (upstream of GT optimal_action
generation, no statistical label leakage). Run: `py -m bench.leakage_audit`

### A6. Full UIR & Friction Table (Regime A, 10 Seeds)

| Strategy | UIR % | Contacts / Recovery | Gross Rev (INR) |
|---|---|---|---|
| Smart-Dunning | 49.0 ± 0.4% | 0.776 | 220,866,149 |
| Rule-Based | 9.2 ± 2.0% | 0.585 | 268,282,158 |
| **Autopilot** | **0.0 ± 0.0%** | **0.463** | **254,842,959** |
| Oracle `[CEILING]` | 0.0% | 0.550 | 284,527,486 |

### A7. Decisions Log

| ID | Decision | Consequence |
|---|---|---|
| D1 | Keep cross-episode detection; decompose lift into orchestration + detection gains | Ablation 6b required |
| D2 | Population mix: IF 24% / transient 22% / non-rec 14% / auth 13% / expired 11% / regional 8% / ambiguous 8% | Fixed in sim_config.yaml |
| D3 | Gross revenue headline; net in adjacent column | IRPI on gross; net-basis IRPI secondary |
| D4 | Eval seeds 1–10; training seeds 1000–1019, disjoint | Enforced by test |
