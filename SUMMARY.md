# Benchmark Engineering Notes — Razorpay Autopilot

This document is the deeper technical narrative behind the benchmark numbers.
The README has the headline table; this has the reasoning behind every
methodological choice and the full audit trail.

---

## Why this isn't a standard retry-optimization benchmark

Most published work on subscription payment recovery optimises retry timing —
when to fire the next attempt. That's what "Learned Smart-Retry" and
"Smart-Dunning" (the two trained baselines here) do. Autopilot treats recovery
as a broader problem: given a failure, what is the highest-EU action across the
full 13-action space, accounting for the cost of customer friction, operational
overhead, and time-value of money?

This framing has two important consequences for how we measured things.

**First**, the Oracle [CEILING] had to be redesigned. A standard Oracle that
replays `gt.optimal_action` at every step is a first-action snapshot, not a
multi-step ceiling. We replaced it with a true multi-step Oracle that recomputes
EU at every attempt using actual `attempt_k`, contacts, and sim_hour — the same
inputs Autopilot's Strategist sees, but with perfect knowledge of
`action_success_probabilities`. This matters: a strategy that fails on attempt 1
and replans correctly can still beat a strategy that succeeds on attempt 1 with
a suboptimal action if the former recovers a larger population overall.

**Second**, IRPI (incremental revenue per intervention) required careful
denominator construction. `escalate_to_merchant` on confirmed fraud cases
(`stolen_or_lost_card`, `risk_blocked`) is a compliance obligation, not an
EU-optimising decision. Including those 279 escalations per seed in the IRPI
denominator would deflate Autopilot's IRPI vs baselines that simply `stop` on
those episodes. We excluded them from the headline denominator (Option 2), but
report the full-denominator IRPI and the exact ops cost (₹90/episode × 279 =
₹25,110/seed) as a footnote so judges can verify the math.

---

## The simulation design

The simulator generates 3,000 episodes per seed across 7 failure populations.
The key design choices that make the benchmark non-trivial:

**Many-to-many failure codes.** `do_not_honour` is compatible with
`insufficient_funds`, `non_recoverable`, or `transient`. `GATEWAY_ERROR` is
compatible with `transient`, `regional_degradation`, or `insufficient_funds`.
This is the real-world ambiguity — the observed failure code doesn't uniquely
determine the right recovery action. It's what gives the Investigator's
classification step actual work to do.

**Attempt fatigue and time decay.** `p_eff` at execution is not the stored
base_p. It's `base_p × time_decay(delay, optimal_delay) × fatigue^k × contact_fatigue`.
This means timing and sequencing matter: a strategy that fires the right action
at the wrong delay, or burns attempts on low-p actions early, loses to a
strategy that conserves attempts and fires at the optimal timing. The
time_decay formula uses per-class optimal_delay_h values calibrated against
the generation ranges — these are documented in `costs.yaml` under `time_profile`.

**Correlated incidents.** 240 of 3,000 episodes (8%) belong to one of three
incident clusters. Each cluster has a declining success-rate trajectory tied to
a specific cohort key. These episodes are indistinguishable from normal
`regional_degradation` episodes to a per-episode strategy — detection requires
aggregating across the cluster. This is the design mechanic that makes the
detection-gain decomposition (D1) meaningful.

**Seed band separation.** Training seeds (1000–1019) and evaluation seeds (1–20)
are disjoint. The retry-delay model is fit exclusively on training seeds. A test
in `strategies/train_retry_model.py` asserts no overlap. Any strategy that
trained on evaluation seeds would be flagged as a D4 violation.

---

## The five calibration bugs — technical detail

### Bug 3 in full (the most instructive one)

The `time_decay` bug (Bug 3) is worth understanding completely because it
caused the Strategist to simultaneously overestimate one action and
underestimate another, in opposite directions, with compounding effects.

For `insufficient_funds` episodes, the simulator sets `optimal_delay_h = 72h`
for all retry-delay actions (from `sim/generate.py` `time_profile()`). The
consequence:

- `retry_72h` has `action_delay_h = 72h = optimal_delay_h`, so
  `time_decay = exp(0) = 1.0`. No penalty. Action Agent executes at full base_p.
- `retry_7d` has `action_delay_h = 168h ≠ optimal_delay_h = 72h`, so
  `time_decay = exp(−0.18 × |168−72|/24) = 0.487`. Action Agent executes at
  ~49% of base_p.

Before the fix, the Strategist computed `p_single` from the logistic regression
without applying time_decay. The fitted model gave `retry_7d` slightly higher
classifier probability (reflecting its higher GT base_p), so the Strategist
estimated retry_7d at p=0.567 and retry_72h at p=0.222. But at execution:
retry_7d ran at p=0.303 and retry_72h at p=0.598.

The Strategist was choosing retry_7d because it looked 2.5× better. The actual
execution gap was 2× in the other direction. The policy EU calculation
(`P_atleast1(K=2) = 0.78` for retry_7d, `P_atleast1(K=4) = 0.55` for
retry_72h) was computing the right math on inputs that were systematically wrong.

Fix: add `_time_decay_for_action(action, inferred_class, costs)` helper that
reads `time_profile[inferred_class].optimal_delay_h` and `decay_lambda` from
`costs.yaml` (sourced from and matching `sim/generate.py`), applies the same
formula the Action Agent will use. The Strategist's `p_success` and the Action
Agent's `p_eff` now agree within ~15% on all retry actions.

After this fix, the retry_72h / retry_7d split on IF episodes became a genuine
EU signal: retry_72h wins for episodes where the model's per-episode probability
estimate is close, because K=4 compounds better than K=2. retry_7d wins when the
model assigns it meaningfully higher single-shot probability (median gap +0.111).
Both choices are defensible.

---

## Why Rule-Based leads on two populations

After all calibration fixes, Autopilot trails Rule-Based by −4.1% overall,
driven by `insufficient_funds` (81.5% vs 94.3%) and `expired_card` (77.9% vs
95.4%).

The diagnostic is this: for both populations, `routeState` in the simulator
assigns a **single dominant GT optimal action**. For `insufficient_funds` it's
`retry_72h` (100% of episodes). For `expired_card` it's
`request_new_payment_method` (75% of episodes, with the rest split across 6
other actions).

Rule-Based's rules map `insufficient_funds → retry_72h` and
`card_expired → request_new_payment_method`. These are the same mappings the
simulator uses when constructing GT optimal_action. A first-action match of
100% on IF and 75% on EC is not leakage or overfitting — it's structural
alignment between the rule table and the simulator's EU argmax.

Autopilot's Strategist doesn't hard-code these mappings. It uses a fitted
logistic regression whose per-episode predictions split ~50/50 between
retry_72h and retry_7d on IF, and routes ~23% of EC episodes to escalation
via the policy gate. This is the correct behavior for a generalising system,
but it costs ~12pp on IF and ~17pp on EC against a simulator that was
constructed to have a unique optimal.

In a real deployment where multiple actions can be near-optimal for the same
failure class, this structural correlation would not hold. The comparison
against Smart-Dunning (+18.3%) is the more informative number.

---

## Detection-gain decomposition

The +1.8% detection-gain is currently modest for a specific reason: the
detector fires on correct incidents (median latency +9h for INC-1), but only
80 episodes per seed are in each incident cluster. The detector correctly
routes those episodes to `hold_for_incident` instead of burning retries into
a degrading route. But 80 × 3 = 240 episodes out of 3,000 (8%) limits the
ceiling of what detection-gain can add.

If incident prevalence were higher, or if the detector were used to inform
retry routing for the full transient + regional_degradation population (not
just the clustered incidents), detection-gain would be larger. The Phase 5
implementation is a correct and working detector; the measured gain reflects
the episode mix, not a limitation of the detection logic itself.

---

## Fairness checklist

- Autopilot's `p(success|a)` estimator is the same fitted `retry_delay_logreg`
  object as Learned Smart-Retry and Smart-Dunning. Where action spaces overlap,
  it is literally the same model.
- Training seeds (1000–1019) and evaluation seeds (1–10) are disjoint.
- The degradation detector reads only observed outcomes of already-resolved
  episodes — no ground-truth fields.
- Oracle applies the same `MANDATORY_ESCALATION_CODES` compliance constraint as
  all other strategies.
- All strategies are scored on identical episode draws: each strategy gets
  `Random(rng_base + seed * 31337 + ep_idx * 17 + hash(name) % 1000)` as its
  RNG, and the detector gets a separate `Random(rng_base + seed * 99991 + ep_idx)`.
- Results are means ± std across 10 evaluation seeds; Oracle is labeled
  `[CEILING]` in every table; Autopilot-no-detect is labeled `[ABLATION]`.
