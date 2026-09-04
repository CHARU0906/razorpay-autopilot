"""
Razorpay TEST MODE client — wraps the real Razorpay API for the integration layer.

This module is the ONLY place in the codebase that touches Razorpay's live API.
All calls are TEST MODE (rzp_test_... keys). No real money moves.

What is real here:
  - HTTP calls to api.razorpay.com/v1/payment_links (real Razorpay servers)
  - HTTP calls to api.razorpay.com/v1/payments/{id} (real payment entity fetch)
  - Webhook signature validation using HMAC-SHA256 (same algorithm as production)
  - The payment_failed webhook payload structure is identical to production

What is NOT real:
  - No real customer cards or bank accounts involved
  - Test-mode payment links go to Razorpay's test checkout, not live checkout
  - The 30-link-per-business test limit applies

If RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET env vars are not set, this module
falls back to MockRecoveryLinkAPI behavior and logs a clear warning.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — loaded from environment variables, never hardcoded
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[str | None, str | None]:
    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        return None, None
    if not key_id.startswith("rzp_test_"):
        logger.error(
            "RAZORPAY_KEY_ID does not start with 'rzp_test_'. "
            "Live-mode keys are not accepted in this integration. "
            "Falling back to mock behavior."
        )
        return None, None
    return key_id, key_secret


def is_live() -> bool:
    """Return True if real Razorpay test-mode credentials are configured."""
    key_id, key_secret = _get_credentials()
    return key_id is not None and key_secret is not None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PaymentLinkResult:
    """Result of creating a Razorpay Payment Link."""
    success: bool
    payment_link_id: Optional[str]
    short_url: Optional[str]
    amount_paise: int
    currency: str
    is_live_api: bool          # True = real Razorpay API call; False = mock fallback
    raw_response: Optional[dict]
    error: Optional[str]


@dataclass
class PaymentFetchResult:
    """Result of fetching a payment entity from Razorpay."""
    success: bool
    payment_id: str
    status: str                # failed / authorized / captured
    error_code: Optional[str]
    error_description: Optional[str]
    error_source: Optional[str]
    error_reason: Optional[str]
    amount_paise: int
    currency: str
    method: Optional[str]
    is_live_api: bool
    raw_response: Optional[dict]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Webhook signature validation
# ---------------------------------------------------------------------------

def validate_webhook_signature(
    body: bytes,
    razorpay_signature: str,
    webhook_secret: str,
) -> bool:
    """
    Validate a Razorpay webhook signature using HMAC-SHA256.
    This is the same algorithm used in production.

    Args:
        body: Raw request body bytes
        razorpay_signature: Value of X-Razorpay-Signature header
        webhook_secret: Your webhook secret from the Razorpay dashboard

    Returns:
        True if signature is valid, False otherwise
    """
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, razorpay_signature)


# ---------------------------------------------------------------------------
# Payment Links — real API call (with mock fallback)
# ---------------------------------------------------------------------------

def create_payment_link(
    amount_inr: float,
    description: str,
    payment_id_reference: str,
    customer_email: Optional[str] = None,
    expiry_hours: int = 48,
) -> PaymentLinkResult:
    """
    Create a Razorpay Payment Link for the send_recovery_link action.

    In TEST MODE with valid credentials: fires a real POST to
    https://api.razorpay.com/v1/payment_links and returns the real short_url.

    Without credentials: falls back to MockRecoveryLinkAPI behavior, clearly
    labeled as mock in the result.

    Args:
        amount_inr: Amount in INR (will be converted to paise for the API)
        description: Human-readable description shown on the payment page
        payment_id_reference: Original failed payment ID for audit trail
        customer_email: Customer email (optional, pre-fills checkout)
        expiry_hours: Link validity window (default 48h)

    Returns:
        PaymentLinkResult with is_live_api=True if a real API call was made
    """
    amount_paise = int(round(amount_inr * 100))

    key_id, key_secret = _get_credentials()
    if key_id is None:
        # Mock fallback — clearly labeled
        logger.warning(
            "RAZORPAY credentials not configured. "
            "Falling back to MockRecoveryLinkAPI. "
            "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET (test-mode keys) to enable real API calls."
        )
        return PaymentLinkResult(
            success=True,
            payment_link_id=f"mock_plink_{payment_id_reference}",
            short_url=f"https://rzp.io/mock/{payment_id_reference}",
            amount_paise=amount_paise,
            currency="INR",
            is_live_api=False,
            raw_response=None,
            error=None,
        )

    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))

        import time
        expire_by = int(time.time()) + expiry_hours * 3600

        payload: dict = {
            "amount": amount_paise,
            "currency": "INR",
            "accept_partial": False,
            "description": description[:255],  # API max length
            "expire_by": expire_by,
            "reference_id": payment_id_reference[:40],  # API max 40 chars
            "notify": {
                "sms": False,
                "email": bool(customer_email),
            },
        }
        if customer_email:
            payload["customer"] = {"email": customer_email}

        response = client.payment_link.create(payload)

        return PaymentLinkResult(
            success=True,
            payment_link_id=response.get("id"),
            short_url=response.get("short_url"),
            amount_paise=amount_paise,
            currency="INR",
            is_live_api=True,
            raw_response=response,
            error=None,
        )

    except Exception as exc:
        logger.error("Razorpay payment_link.create failed: %s", exc)
        return PaymentLinkResult(
            success=False,
            payment_link_id=None,
            short_url=None,
            amount_paise=amount_paise,
            currency="INR",
            is_live_api=True,
            raw_response=None,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Payment fetch — real API call (with mock fallback)
# ---------------------------------------------------------------------------

def fetch_payment(payment_id: str) -> PaymentFetchResult:
    """
    Fetch a payment entity from Razorpay by ID.

    In TEST MODE with valid credentials: fires a real GET to
    https://api.razorpay.com/v1/payments/{payment_id}.

    The returned error_code, error_description, error_source, error_reason
    are the real Razorpay fields from the payment entity schema.
    These map to our Investigator's failure classification inputs.

    Without credentials: returns a mock failed-payment structure.
    """
    key_id, key_secret = _get_credentials()
    if key_id is None:
        logger.warning("RAZORPAY credentials not configured. Returning mock payment entity.")
        return PaymentFetchResult(
            success=True,
            payment_id=payment_id,
            status="failed",
            error_code="mock_insufficient_funds",
            error_description="Mock: insufficient funds (no credentials configured)",
            error_source="issuer",
            error_reason="insufficient_funds",
            amount_paise=500000,
            currency="INR",
            method="card",
            is_live_api=False,
            raw_response=None,
            error=None,
        )

    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        response = client.payment.fetch(payment_id)

        return PaymentFetchResult(
            success=True,
            payment_id=payment_id,
            status=response.get("status", "unknown"),
            error_code=response.get("error_code"),
            error_description=response.get("error_description"),
            error_source=response.get("error_source"),
            error_reason=response.get("error_reason"),
            amount_paise=response.get("amount", 0),
            currency=response.get("currency", "INR"),
            method=response.get("method"),
            is_live_api=True,
            raw_response=response,
            error=None,
        )

    except Exception as exc:
        logger.error("Razorpay payment.fetch(%s) failed: %s", payment_id, exc)
        return PaymentFetchResult(
            success=False,
            payment_id=payment_id,
            status="unknown",
            error_code=None,
            error_description=None,
            error_source=None,
            error_reason=None,
            amount_paise=0,
            currency="INR",
            method=None,
            is_live_api=True,
            raw_response=None,
            error=str(exc),
        )
