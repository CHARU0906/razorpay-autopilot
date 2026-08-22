# Razorpay Autopilot — System Specification

**Status:** Phase 0 deliverable. Nothing else is built yet.
**Purpose:** single source of truth for the action space, data schemas, strategies, and metrics. Every later phase must conform to this file or explicitly amend it.

---

## 0. Positioning (binding — applies to code, comments, logs, UI copy, and the pitch)

| # | Rule |
|---|---|
| P1 | This is **not** a smart-retry-timing tool. Retry timing is one action among many, and it is what the baselines already do. |
| P2 | This **is** a closed-loop recovery orchestration system: `decide whether → decide what → execute → verify → re-plan`. |
| P3 | North-star metric is **IRPI** (incremental revenue recovered per intervention), always reported against a *named* baseline. |
| P4 | Baselines are **representative implementations inspired by publicly documented capabilities**. We never claim to reproduce Stripe's, Chargebee's, or anyone else's proprietary algorithm. Generic names only: "Learned Smart-Retry Baseline", "Smart-Dunning Baseline". |
| P5 | The word **"learning"** is only used where a model is actually fit from accumulated outcomes. The default term for the Strategist→Outcome→Strategist cycle is **"outcome-driven replanning"**. |
| P6 | Deterministic code owns: execution, thresholds, policy enforcement, scoring math, logging, and every number that appears on screen. |
| P7 | LLM calls are restricted to exactly three jobs: (a) classifying failures the rules layer flags as ambiguous, (b) natural-language justification of a strategy choice, (c) rendering readable Action Log entries. |
| P8 | **No LLM call sits in a performance-critical or demo-critical execution path.** Every LLM output has a deterministic fallback, and Demo Mode (Phase 7) runs with LLM calls fully disabled. |
| P9 | Oracle is a **reference ceiling, not a competitor**. It must be labelled `[CEILING]` in every table, chart, and log line. |
| P10 | No strategy may see anything a baseline cannot see, except where documented in §5.2 and approved by the user. |

---

## 1. Action space

13 actions. `action_id` is the canonical string used in code, logs, ground truth, and metrics.

| # | `action_id` | Class | Customer-visible? | Params | Mock tool (Phase 3) | Intended for |
|---|---|---|---|---|---|---|
| 1 | `stop` | terminal | no | — | — | non-recoverable, or EV ≤ 0 |
| 2 | `retry_1h` | silent retry | no | `delay_h=1` | Mock Retry API | transient |
| 3 | `retry_6h` | silent retry | no | `delay_h=6` | Mock Retry API | transient, soft decline |
| 4 | `retry_24h` | silent retry | no | `delay_h=24` | Mock Retry API | insufficient funds, degradation |
| 5 | `retry_72h` | silent retry | no | `delay_h=72` | Mock Retry API | insufficient funds |
| 6 | `retry_7d` | silent retry | no | `delay_h=168` | Mock Retry API | insufficient funds / salary-cycle alignment |
| 7 | `retry_alternate_route` | silent retry | no | `delay_h=0.25`, `route_id` | Mock Retry API | route / acquirer / regional degradation |
| 8 | `hold_for_incident` | deferred silent retry | no | `until_h` (derived from incident state, not a fixed bucket) | Mock Retry API | live degradation incident |
| 9 | `send_dunning_notification` | nudge | **yes** (low friction) | `channel`, `template` | Mock Notification API | prime a following retry; insufficient funds |
| 10 | `send_recovery_link` | customer action | **yes** (medium friction) | `channel`, `expiry_h` | Mock Recovery Link API | insufficient funds, ambiguous, fallback |
| 11 | `request_reauth` | customer action | **yes** (medium friction) | `channel`, `auth_type` (3ds / upi_mandate) | Mock Recovery Link API | `auth_required`, mandate re-auth |
| 12 | `request_new_payment_method` | customer action | **yes** (high friction) | `channel`, `deadline_h` | Mock Notification + Link API | `expired_card`, revoked mandate |
| 13 | `escalate_to_merchant` | human | no (merchant-facing) | `queue`, `note` | Mock Ops Queue | high value, policy `requires-human`, exhausted replans |

Notes:
- Actions 2–8 are **zero-friction** by construction (no customer contact). Actions 9–12 carry friction. Action 13 carries operational cost, not friction.
- `hold_for_incident` is reachable by *any* strategy in principle; only Autopilot implements the cross-episode aggregation needed to choose it (see §5.2 fairness note — flagged for your review).
- Every strategy must return an action from this list. Illegal or unparseable returns are a hard test failure, not a silent `stop`.

---

## 2. Transaction schema — OBSERVED fields

What a real recovery system would see. This is the only input any strategy under test receives (except Oracle).

### 2.1 Identity & clock
| Field | Type | Notes |
|---|---|---|
| `episode_id` | str | `ep_{seed}_{index}` |
| `merchant_id` | str | 12 synthetic merchants |
| `merchant_vertical` | enum | `saas`, `edtech`, `dtc_subscription`, `lending_emi`, `insurance`, `utility` |
| `customer_id` | str | reused across episodes to build history |
| `first_failure_at` | ISO ts | simulated |
| `sim_hour` | float | hours since sim epoch — the harness clock |

### 2.2 Money
| Field | Type | Notes |
|---|---|---|
| `amount` | float | major units |
| `currency` | enum | `INR`, `USD`, `AED`, `SGD` |
| `amount_inr` | float | normalized with **fixed documented FX rates**, no live FX |
| `mcc` | str | merchant category code |

### 2.3 Instrument
| Field | Type | Notes |
|---|---|---|
| `payment_method` | enum | `card`, `upi_collect`, `upi_autopay`, `netbanking`, `wallet`, `emandate_nach`, `international_card` |
| `card_network` | enum/null | `visa`, `mastercard`, `rupay`, `amex`, null |
| `card_funding` | enum/null | `credit`, `debit`, `prepaid`, null |
| `card_expiry_state` | enum | `valid`, `expiring_soon`, `expired`, `unknown` — `unknown` for tokenized/mandate cases, which is a real source of ambiguity |
| `issuer_bank_code` | enum | `HDFC`, `ICICI`, `SBIN`, `AXIS`, `KKBK`, `PAYTM`, `INTL` |
| `token_type` | enum | `network_token`, `raw_stored`, `mandate`, `none` |

### 2.4 Geography & routing
| Field | Type | Notes |
|---|---|---|
| `country` | enum | `IN`, `US`, `AE`, `SG`, `GB` |
| `region_state` | str/null | for `IN` |
| `acquirer_route_id` | enum | `route_a`, `route_b`, `route_c` |
| `is_cross_border` | bool | |

### 2.5 Recurring / subscription
| Field | Type | Notes |
|---|---|---|
| `is_recurring` | bool | |
| `subscription_id` | str/null | |
| `billing_cycle` | enum/null | `weekly`, `monthly`, `annual` |
| `cycle_index` | int | how many cycles billed so far |
| `mandate_status` | enum | `active`, `expired`, `revoked`, `none` |
| `days_until_service_suspension` | int/null | urgency signal |
| `is_first_charge_on_instrument` | bool | |

### 2.6 Failure signal
| Field | Type | Notes |
|---|---|---|
| `failure_code` | enum | see §2.9 — **deliberately many-to-many with true class** |
| `failure_message` | str | free text; the only field the ambiguity-path LLM reads |
| `failure_source` | enum | `issuer`, `network`, `gateway`, `risk_engine`, `customer_action` |
| `auth_state` | enum | `not_required`, `not_attempted`, `attempted_failed`, `authenticated`, `mandate_auth_pending` |
| `risk_score_gateway` | float 0–1 | |
| `prior_soft_declines_on_instrument_30d` | int | |

### 2.7 Customer history (observed)
`customer_tenure_days`, `lifetime_successful_txns`, `lifetime_failed_txns`, `lifetime_value_inr`, `prior_recovery_attempts`, `prior_recovery_successes`, `avg_days_between_txns`, `email_engagement_score` (0–1), `engagement_recency_days`, `has_alternate_instrument_on_file` (bool), `prior_payment_method_update_count`.

`lifetime_value_inr` and `email_engagement_score` are the observed proxies the Strategist uses to price friction — the *true* friction cost stays hidden (§3).

### 2.8 Retry / episode state (mutated by the harness as actions execute)
`attempt_index`, `hours_since_first_failure`, `actions_taken` (list of `{action, params, at_hour, outcome}`), `customer_contacts_sent`, `last_action`, `last_outcome`, `replan_count`.

### 2.9 Failure codes and their intentional ambiguity

| `failure_code` | Compatible true classes |
|---|---|
| `insufficient_funds` | insufficient_funds |
| `card_expired` | expired_card |
| `authentication_failed` | auth_required |
| `mandate_revoked` | non_recoverable, auth_required |
| `issuer_down` | regional_degradation, transient |
| `network_timeout` | transient, regional_degradation |
| `do_not_honour` | insufficient_funds, non_recoverable, transient |
| `GATEWAY_ERROR` | transient, regional_degradation, insufficient_funds |
| `payment_method_restricted` | non_recoverable, expired_card |
| `risk_blocked` | non_recoverable |
| `stolen_or_lost_card` | non_recoverable |
| `unknown_error` | any |

Codes with ≥2 compatible classes are what create the `ambiguous` population and give the Investigator (and its narrow LLM path) something real to do.

**Derived features are allowed** (e.g. cohort rolling success rate over `(country, card_network, issuer_bank_code, acquirer_route_id)`), but only if computed from observed fields and observed outcomes of *already-resolved* episodes. Any derived feature must be registered in `features.py` so the fairness audit can check it.

---

## 3. Ground-truth schema — HIDDEN

Written to a separate file (`ground_truth.jsonl`), keyed by `episode_id`. Loaded **only** by the scorer, the mock tool layer's outcome sampler, and Oracle. A fairness test asserts no strategy module imports it.

| Field | Type | Notes |
|---|---|---|
| `population` | enum | which generator produced it: `transient`, `insufficient_funds`, `auth_required`, `expired_card`, `regional_degradation`, `non_recoverable`, `ambiguous` |
| `true_failure_class` | enum | the real underlying cause. For `population == ambiguous`, this is drawn from the other six — so ambiguity is an *observability* property, not a separate cause |
| `observability` | enum | `clear`, `ambiguous` |
| `true_recoverability` | float 0–1 | probability the payment is *ever* recoverable under the best possible policy |
| `valid_actions` | list | actions with non-zero success probability (`stop` always included) |
| `action_success_probabilities` | dict | `action_id → base_p` |
| `action_time_profile` | dict | `action_id → {optimal_delay_h, decay_lambda}` — makes timing matter, so the Learned baseline has real signal to exploit |
| `attempt_fatigue_factor` | float | multiplicative penalty per additional attempt |
| `customer_friction_cost` | dict | `action_id → friction_cost_inr`, per-episode (varies with CLV and engagement) |
| `incident_id` | str/null | links correlated episodes |
| `incident_degradation_curve` | ref/null | success-rate trajectory over the incident window |
| `optimal_action` | `action_id` | argmax of the §6 utility under *true* probabilities |
| `optimal_delay_h` | float | |
| `optimal_action_revenue_only` | `action_id` | argmax of `P(success)·Revenue` alone — a second, friction-blind ceiling |
| `true_max_expected_revenue_inr` | float | |
| `zero_friction_recovery_possible` | bool | some zero-friction action has non-trivial success probability → used for UIR |
| `eventual_recovery_without_intervention` | bool | would have recovered on its own within the horizon |
| `root_cause_label` | str | human-readable, for the Action Log and demo narrative |

**Effective success probability** when an action executes at simulated hour `t` on attempt `k`:

```
p_eff = base_p[a]
      × time_decay(a, delay_h)            # peaked at optimal_delay_h, decays with lambda
      × incident_multiplier(incident, t)  # 1.0 when no incident
      × attempt_fatigue_factor ** k
      × contact_fatigue(customer_contacts_sent)   # customer-visible actions only
```

Clamped to `[0, 0.98]`. This is the **only** place randomness decides an outcome, and the deciding logic never reads it.

---

## 4. Failure populations — proposed default mix

For 3,000 episodes (Phase 1 iteration size). **APPROVED — Decision D2 (§11).**

| Population | Share | n @3k | Rationale |
|---|---:|---:|---|
| `insufficient_funds` | 24% | 720 | Largest real-world recoverable bucket in recurring billing |
| `transient` | 22% | 660 | Timeouts, gateway blips, issuer soft declines |
| `non_recoverable` | 14% | 420 | Hard declines: stolen/lost, risk blocks, restricted methods |
| `auth_required` | 13% | 390 | 3DS/SCA step-up, UPI AutoPay mandate re-auth |
| `expired_card` | 11% | 330 | Expiry churn on stored instruments |
| `regional_degradation` | 8% | 240 | Concentrated into **3 incidents**, ~80 episodes each |
| `ambiguous` | 8% | 240 | Uninformative failure codes; true class drawn from the six above |

Sums to 100%. Configurable in `sim_config.yaml`; the mix is recorded in the output manifest so every benchmark run states the mix it used.

### 4.1 Correlated incidents (mandatory, not optional)

Three incidents, each defined by a cohort key and a degrading trajectory over simulated time:

| Incident | Cohort key | Window | Success-rate trajectory | Right answer |
|---|---|---|---|---|
| `INC-1` | `country=IN, card_network=rupay, issuer=HDFC` | 18h | 94% → 91% → 87% → 82% | `hold_for_incident` then retry |
| `INC-2` | `acquirer_route_id=route_b, is_cross_border=True` | 12h | 96% → 90% → 84% | `retry_alternate_route` |
| `INC-3` | `payment_method=upi_autopay, issuer=PAYTM` | 24h | 93% → 89% → 85% → 88% (partial self-heal) | `hold_for_incident` |

Episodes inside an incident window carry `incident_id` in ground truth and are otherwise indistinguishable to a per-episode strategy — detection requires aggregating across episodes, which is exactly the Phase 5 point.

### 4.2 Output & seed policy
- `episodes.jsonl` (observed) + `ground_truth.jsonl` (hidden) + `manifest.json` (seed, mix, version, git-less content hash).
- Seed is a CLI parameter. **Seed bands are disjoint:** `1000–1019` = training data for the learned models; `1–20` = evaluation seeds. A test asserts no overlap. Training on eval seeds is a fairness violation.
- Episode horizon: **336 simulated hours (14 days)**. Hard cap **6 executed actions** per episode.

---

## 5. Strategies

Identical interface for all six competitors:

```python
def decide(observed: dict, episode_state: dict) -> tuple[str, dict]:   # (action_id, params)
```

| # | Strategy | Summary |
|---|---|---|
| 1 | **No Recovery** | always `stop`. The do-nothing floor. |
| 2 | **Fixed Retry** | `retry_1h → retry_6h → retry_24h → retry_72h → stop`, regardless of failure type. |
| 3 | **Rule-Based Recovery** | explicit if/else on failure code and auth state. Rules written out for your review *before* implementation (Phase 2). |
| 4 | **Learned Smart-Retry Baseline** | logistic regression / gradient boosting predicting best retry delay from observed features. **Retry timing only** — represents "retry optimization", nothing more. |
| 5 | **Smart-Dunning Baseline** | learned timing + notification triggers + payment-method-update flow + retry caps. The strongest baseline; the headline comparison. |
| 6 | **Autopilot** | Phase 3 pipeline: Investigator → Strategist → Policy Engine → Action Agent → Outcome Agent, with outcome-driven replanning. |
| 6b | **Autopilot (no degradation detection) `[ABLATION]`** | Identical to #6 with the Phase 5 detector disabled — Autopilot restricted to per-episode information, exactly like the baselines. Not a competitor; exists so the headline lift decomposes into orchestration-gain vs detection-gain (Decision D1). |
| — | **Oracle `[CEILING]`** | reads ground truth, plays `optimal_action`. Reference ceiling, **not a competitor** — excluded from every "beats X" claim. |

### 5.1 Information access matrix

| | Observed fields | Own episode state | Cross-episode observed outcomes | Model fit on training seeds | Ground truth |
|---|---|---|---|---|---|
| No Recovery | – | – | – | – | – |
| Fixed Retry | minimal | ✅ | – | – | – |
| Rule-Based | ✅ | ✅ | – | – | – |
| Learned Smart-Retry | ✅ | ✅ | – | ✅ | – |
| Smart-Dunning | ✅ | ✅ | – | ✅ | – |
| **Autopilot** | ✅ | ✅ | ✅ (§5.2) | ✅ (same model, same seeds) | – |
| Oracle `[CEILING]` | ✅ | ✅ | ✅ | – | ✅ |

### 5.2 Where Autopilot's advantage is allowed to come from — and where it is not

**Allowed:**
1. Considering the **full action space** instead of a retry-timing subset.
2. An **explicit utility function** that prices friction, risk, and intervention cost (§6) instead of implicit heuristics.
3. **Cross-episode degradation detection** from observed outcomes only (Phase 5).
4. **Outcome-driven replanning** after a verified failure.
5. **Policy gating** that routes high-value/high-risk cases to approval instead of guessing.

**Forbidden:**
- Reading any ground-truth field.
- Training on evaluation seeds.
- A better-calibrated success model than the baselines get. Autopilot's `P(success|a)` estimator is fit on the **same training seeds** as the Learned and Smart-Dunning baselines, and where the action spaces overlap it is the **same fitted model object**.
- Any tuning of thresholds against evaluation-seed results (config is tuned on training seeds only).

> ✅ **Fairness item — RESOLVED (Decision D1).** The degradation detector consumes only observed fields and observed outcomes of already-resolved episodes — information any strategy *could* compute. The baselines don't, because their real-world counterparts are per-transaction dunning stacks. This is kept, **and** two things are mandatory as a result:
>
> 1. Every results table carries a footnote stating that Autopilot aggregates across episodes and the baselines do not.
> 2. Phase 4 runs **Autopilot (no degradation detection) `[ABLATION]`** as strategy 6b, so the headline lift over Smart-Dunning splits into `orchestration-gain` (6b vs Smart-Dunning) and `detection-gain` (6 vs 6b). If detection-gain turns out to be the whole story, we report that plainly rather than hiding it in an aggregate.

---

## 6. Strategist utility function (Phase 3)

```
ExpectedUtility(a) = P(success | a, episode, t) · Revenue(a)
                   − C_friction(a) − C_risk(a) − C_intervention(a)
```

### 6.1 Normalization approach — every term in INR expected-value units

| Term | Definition | Normalization to INR |
|---|---|---|
| `Revenue(a)` | recovered amount, time-discounted | `amount_inr × (1 − ρ)^(expected_delay_days)`, `ρ` ≈ small daily discount so faster recovery scores higher |
| `C_friction(a)` | customer annoyance | `P(churn_increment \| a) × lifetime_value_inr`, scaled by `email_engagement_score` and `customer_contacts_sent` — i.e. friction is priced as **expected CLV loss** |
| `C_risk(a)` | adverse downstream events | `Σ P(event \| a) × cost_inr(event)` over {chargeback/dispute, mandate revocation, compliance flag} |
| `C_intervention(a)` | direct operational cost | gateway retry fee + SMS/email unit cost + (ops minutes × loaded hourly rate) |

Because all four are INR, they are directly comparable with no arbitrary weights. Every constant lives in `costs.yaml` with a one-line source/justification comment, and the whole table gets shown to you for sign-off **before** the Strategist is implemented (as you asked).

`P(success | a, episode, t)` comes from the shared calibrated estimator of §5.2 — never from ground truth.

---

## 7. Metrics

Let `E` = evaluation episode set, `S` = strategy, `B` = named baseline.

| Metric | Definition |
|---|---|
| **Recovery rate** | `recovered(S) / \|E\|`. "Recovered" = payment succeeds within the 336h horizon before `stop`/attempt cap. |
| **Revenue recovered** | **Headline = gross:** `Σ amount_inr` over recovered episodes. **Net** (`gross − C_friction − C_risk − C_intervention`, all realized) reported as an adjacent column in the same table (Decision D3). IRPI and lift % are computed on gross; a net-basis IRPI is reported as a secondary column so cost-efficiency is visible without changing the headline. |
| **IRPI** | `(Revenue(S) − Revenue(B)) / interventions(S)`. Always reported **against a named baseline**. `interventions` = executed non-`stop` actions. Also report plain revenue-per-intervention. |
| **Recovery lift %** | `(Revenue(S) − Revenue(Smart-Dunning)) / Revenue(Smart-Dunning) × 100` — headline comparison is against Smart-Dunning specifically. |
| **UIR** (unnecessary intervention rate) | over **customer-visible** actions: unnecessary if `true_recoverability == 0` (could never pay off) **or** `zero_friction_recovery_possible` and a silent retry had ≥ the chosen action's success probability (friction was avoidable). `UIR = unnecessary / all customer-visible actions`. |
| Wasted-attempt rate | silent retries spent on episodes with `true_recoverability == 0` — reported separately so UIR stays interpretable. |
| **Time to recovery** | simulated hours from `first_failure_at` to success; mean and median over recovered episodes. |
| **% of Oracle** | `Revenue(S) / Revenue(Oracle) × 100`. Oracle labelled `[CEILING]`. |
| Customer contacts per recovered payment | friction efficiency |
| Approval-gate stats | count and value of `requires-approval` / `requires-human` routings (Autopilot only) |

Reported as **mean ± std across seeds** (10 seeds to start, 20 if time allows), plus per-seed raw table.

---

## 8. Repo layout

```
SPEC.md
sim_config.yaml          # population mix, incidents, horizon
costs.yaml               # INR cost constants (§6.1)
policy.yaml              # autonomy-tier thresholds (Phase 3)
sim/                     # Phase 1 generator + ground truth
strategies/              # Phase 2, one module per strategy, identical interface
autopilot/               # Phase 3 graph: investigator, strategist, policy, action, outcome
tools/                   # Phase 3 mock Retry / Link / Notification / Ops APIs
detect/                  # Phase 5 degradation detection → routes into autopilot/
bench/                   # Phase 4 harness, scorer, tables
ui/                      # Phase 6 React + Tailwind, single page
demo/                    # Phase 7 deterministic playback script
data/                    # episodes.jsonl, ground_truth.jsonl, manifest.json, results/
```

---

## 9. Phase gates

| Phase | Exit criterion you must see before we move on |
|---|---|
| 0 | This file approved |
| 1 | Sample episodes from all 7 populations + one incident's degradation curve printed |
| 2 | Action distribution per strategy on a small sample |
| 3 | Full end-to-end trace for one episode, human-readable |
| 4 | Real numbers, mean ± std across 10 seeds, **8 runs per seed** (6 strategies + Oracle `[CEILING]` + Autopilot-no-detection `[ABLATION]`), with lift decomposed into orchestration-gain and detection-gain. **If Autopilot does not beat Smart-Dunning, I say so plainly and we debug the Strategist — we do not skip to UI.** |
| 5 | Before/after: undetected degradation vs detected + routed |
| 6 | UI running on real benchmark output, no fabricated figures |
| 7 | Deterministic playback, manual next-step trigger, reset |

---

## 10. Simplifications flagged for your decision

| # | Simplification | Why | Push back? |
|---|---|---|---|
| S1 | **Resolved (D3):** gross headline + net alongside. MDR/gateway fees still not deducted from gross | Keeps IRPI readable while preserving the cost-efficiency claim | An MDR constant is a one-line addition to `costs.yaml` if you want it later |
| S2 | Fixed FX rates, no live FX | Determinism | Fine for a hackathon |
| S3 | Retry-delay buckets are discrete (1h/6h/24h/72h/7d) not continuous | Makes the action space finite and Oracle exactly computable | Continuous delay would need a different Oracle |
| S4 | `C_risk` covers 3 event types only | Time | Extendable |
| S5 | 12 synthetic merchants, 6 verticals | Enough for cohort structure without bloating | — |
| S6 | Oracle is optimal **w.r.t. our utility definition**, so "% of Oracle" is relative to our own objective | Any ceiling needs an objective; we also report the friction-blind revenue-only ceiling for contrast | Worth stating on the slide |

---

## 11. Decisions log

| ID | Question | Decision | Date | Consequence |
|---|---|---|---|---|
| **D1** | Fairness of Autopilot's cross-episode degradation detection (§5.2) | **Keep it, footnote it, and ship the `[ABLATION]`** run | 2026-08-22 | Adds strategy 6b; Phase 4 reports lift split into orchestration-gain vs detection-gain |
| **D2** | Population mix (§4) | **Accept proposed default** (IF 24 / transient 22 / non-rec 14 / auth 13 / expired 11 / regional 8 / ambiguous 8) | 2026-08-22 | Written to `sim_config.yaml`; recorded in every run manifest |
| **D3** | Revenue basis (§7, S1) | **Gross headline, net in an adjacent column**; no MDR deduction | 2026-08-22 | IRPI and lift % on gross; net-basis IRPI as secondary column |
| **D4** | Seed count | **10 evaluation seeds now, 20 if time allows** (per original brief); training seeds `1000–1019`, disjoint | 2026-08-22 | Enforced by a test asserting no train/eval seed overlap |

Amendments to this spec must be appended here with an ID, not made silently in the affected section.

---

**Phase 0 complete.** Awaiting your go-ahead before writing Phase 1 (simulator + ground truth).

