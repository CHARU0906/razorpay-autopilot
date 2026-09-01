/**
 * Real benchmark data from Phase 4+5 canonical run.
 * Source: data/results/phase4_multistep.json — 10 eval seeds, multi-step Oracle.
 * DO NOT fabricate numbers. All figures sourced from committed benchmark output.
 */

export const BENCHMARK = {
  autopilot: {
    recovery_rate:  0.744,
    recovery_rate_std: 0.004,
    gross_revenue:  254842959,
    gross_revenue_std: 11426424,
    lift_vs_sd_pct: 15.4,
    pct_of_oracle:  89.6,
    interventions:  8178,
    uir:            0.0,
    contacts_per_recovery: 0.463,
    orchestration_gain_pct: 14.2,
    detection_gain_pct: 1.2,
    per_pop: {
      insufficient_funds:  0.815,
      transient:           0.967,
      auth_required:       0.891,
      expired_card:        0.780,
      regional_degradation:0.868,
      non_recoverable:     0.104,
      ambiguous:           0.629,
    },
  },
  smart_dunning: {
    recovery_rate:  0.664,
    gross_revenue:  220866149,
    lift_vs_sd_pct: 0.0,
    uir:            0.490,
    contacts_per_recovery: 0.776,
  },
  rule_based: {
    recovery_rate:  0.782,
    gross_revenue:  268282158,
    lift_vs_sd_pct: 21.5,
    uir:            0.092,
    contacts_per_recovery: 0.585,
  },
  oracle: {
    recovery_rate:  0.826,
    gross_revenue:  284527486,
    lift_vs_sd_pct: 28.8,
    label: 'Oracle [CEILING]',
  },
}

// Total episodes in benchmark
export const TOTAL_EPISODES = 3000

// Revenue at risk = episodes that failed × average amount
// Derived from recovery rate gap: (oracle_rr - autopilot_rr) × gross_oracle
export const REVENUE_AT_RISK = Math.round(
  (BENCHMARK.oracle.gross_revenue - BENCHMARK.autopilot.gross_revenue)
)

// Failures processed (episodes Autopilot received interventions on)
export const FAILURES_PROCESSED = BENCHMARK.autopilot.interventions

// Seed count for the run
export const SEED_COUNT = 10
