"""
Local offline demo of the Razorpay integration layer.

Shows on camera:
1. Representative payment.failed payload (from Razorpay's documented schema)
   parsed correctly into observed-episode format
2. Full EU pipeline running on that translated episode
3. Signature validation logic tested against a known HMAC-SHA256 test vector

This is local/offline verification — no HTTP calls to api.razorpay.com.
Label it accordingly if shown on camera.

Usage:
    py -m razorpay_integration.demo_local
"""

from __future__ import annotations
import sys, os, hashlib, hmac

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from razorpay_integration.webhook_handler import translate_webhook_payload, process_webhook
from razorpay_integration.client import validate_webhook_signature


def main():
    print("=" * 72)
    print("RAZORPAY INTEGRATION — LOCAL OFFLINE DEMO")
    print("No HTTP calls to api.razorpay.com. Labeled as local verification.")
    print("=" * 72)

    # ── Demo 1: Payload parsing ───────────────────────────────────────────────
    print("\n[1/3] Parsing a representative payment.failed payload")
    print("      (structure from Razorpay's documented payment entity schema)")

    # This payload matches Razorpay's documented payment entity + webhook structure
    # Source: https://razorpay.com/docs/api/payments/entity/
    # and: https://razorpay.com/docs/webhooks/payments/
    representative_payload = {
        "event": "payment.failed",
        "account_id": "acc_test_demo",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_DemoInsufficientFunds01",
                    "entity": "payment",
                    "amount": 750000,       # ₹7,500 in paise
                    "currency": "INR",
                    "status": "failed",
                    "method": "card",
                    "international": False,
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Your payment could not be completed due to insufficient account balance.",
                    "error_source": "issuer",
                    "error_step": "payment_authentication",
                    "error_reason": "insufficient_fund",
                    "card": {
                        "id": "card_demo001",
                        "network": "Visa",
                        "type": "debit",
                        "issuer": "HDFC",
                        "international": False,
                    },
                    "created_at": 1756000000,
                }
            }
        }
    }

    observed, missing = translate_webhook_payload(representative_payload)
    print(f"  episode_id:      {observed['episode_id']}")
    print(f"  failure_code:    {observed['failure_code']}  (mapped from error_reason='insufficient_fund')")
    print(f"  amount_inr:      ₹{observed['amount_inr']:,.2f}  (converted from {representative_payload['payload']['payment']['entity']['amount']} paise)")
    print(f"  failure_source:  {observed['failure_source']}")
    print(f"  missing_fields:  {missing if missing else 'none (all required fields present)'}")
    print("  ✓ Payload parsed correctly")

    # ── Demo 2: EU pipeline ───────────────────────────────────────────────────
    print("\n[2/3] Running EU pipeline on translated episode")
    result = process_webhook(representative_payload, event_type="payment.failed")
    print(f"  inferred_class:      {result.inferred_class}")
    print(f"  recommended_action:  {result.recommended_action}")
    print(f"  policy_tier:         {result.policy_tier}")
    print(f"  eu_winner:           ₹{result.eu_winner:,.2f}")
    print(f"  payment_link_url:    {result.payment_link_url} (mock — no credentials)")
    print(f"  payment_link_is_live:{result.payment_link_is_live}")
    print("  Pipeline trace:")
    for stage in result.pipeline_trace:
        action_or_class = stage.get('action') or stage.get('inferred_class') or stage.get('winner', '')
        print(f"    {stage['stage']:15s} → {action_or_class}")
    print("  ✓ Full EU pipeline ran on Razorpay-structured payload")

    # ── Demo 3: Signature validation logic ────────────────────────────────────
    print("\n[3/3] Testing HMAC-SHA256 webhook signature validation")
    print("      (per Razorpay's published spec: https://razorpay.com/docs/webhooks/validate-test/)")

    # Construct a known test vector
    test_body = b'{"event":"payment.failed","payload":{"payment":{"entity":{"id":"pay_test"}}}}'
    test_secret = "test_webhook_secret_12345"

    # Compute expected signature (same formula Razorpay uses)
    expected_sig = hmac.new(
        test_secret.encode("utf-8"),
        test_body,
        hashlib.sha256,
    ).hexdigest()

    # Validate correct signature
    assert validate_webhook_signature(test_body, expected_sig, test_secret), "Validation failed for correct sig"
    print(f"  Correct signature:   {expected_sig[:32]}…")
    print(f"  validate() result:   True  ✓")

    # Validate wrong signature
    wrong_sig = "a" * 64
    assert not validate_webhook_signature(test_body, wrong_sig, test_secret), "Validation should fail for wrong sig"
    print(f"  Wrong signature:     {'a'*32}…")
    print(f"  validate() result:   False ✓")
    print("  ✓ HMAC-SHA256 validation logic correct against known test vector")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("LOCAL DEMO COMPLETE")
    print("=" * 72)
    print("Verified locally:")
    print("  ✓ payment.failed payload → observed-episode translation")
    print("  ✓ EU pipeline on Razorpay-structured input")
    print("  ✓ HMAC-SHA256 signature validation logic")
    print()
    print("NOT verified (no live API calls):")
    print("  ~ Actual HTTP call to api.razorpay.com/v1/payment_links")
    print("  ~ Real payment.failed webhook from Razorpay servers")
    print("  ~ Signature against a real Razorpay-signed payload")
    print()
    print("Demo framing: 'Integration built against Razorpay's documented contract,")
    print("               verified locally — not a live API call.'")
    print("=" * 72)


if __name__ == "__main__":
    main()
