"""Observed-only featurization for the learned retry-timing model."""

from __future__ import annotations

import math

CATEGORICAL = [
    "failure_code",
    "payment_method",
    "auth_state",
    "card_expiry_state",
    "country",
    "issuer_bank_code",
    "card_network",
    "failure_source",
    "merchant_vertical",
]
NUMERIC = [
    "log_amount_inr",
    "risk_score_gateway",
    "prior_soft_declines_on_instrument_30d",
    "is_recurring",
    "is_cross_border",
    "attempt_index",
    "hours_since_first_failure",
    "has_alternate_instrument_on_file",
    "email_engagement_score",
]


def row_to_raw(observed: dict, episode_state: dict) -> dict:
    amount = float(observed.get("amount_inr") or 0.0)
    return {
        "failure_code": observed.get("failure_code") or "unknown_error",
        "payment_method": observed.get("payment_method") or "card",
        "auth_state": observed.get("auth_state") or "not_required",
        "card_expiry_state": observed.get("card_expiry_state") or "unknown",
        "country": observed.get("country") or "IN",
        "issuer_bank_code": observed.get("issuer_bank_code") or "INTL",
        "card_network": observed.get("card_network") or "none",
        "failure_source": observed.get("failure_source") or "gateway",
        "merchant_vertical": observed.get("merchant_vertical") or "saas",
        "log_amount_inr": math.log1p(max(0.0, amount)),
        "risk_score_gateway": float(observed.get("risk_score_gateway") or 0.0),
        "prior_soft_declines_on_instrument_30d": float(
            observed.get("prior_soft_declines_on_instrument_30d") or 0
        ),
        "is_recurring": 1.0 if observed.get("is_recurring") else 0.0,
        "is_cross_border": 1.0 if observed.get("is_cross_border") else 0.0,
        "attempt_index": float(episode_state.get("attempt_index") or 0),
        "hours_since_first_failure": float(episode_state.get("hours_since_first_failure") or 0.0),
        "has_alternate_instrument_on_file": 1.0
        if observed.get("has_alternate_instrument_on_file")
        else 0.0,
        "email_engagement_score": float(observed.get("email_engagement_score") or 0.0),
    }
