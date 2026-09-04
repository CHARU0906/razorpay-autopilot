"""
Live API verification script — closes Check 2 from the Priority 1 verification gate.

Run this once you have real test-mode credentials configured to confirm:
1. create_payment_link() reaches api.razorpay.com and gets back a real link
2. fetch_payment() reaches api.razorpay.com and gets back a real payment entity

Usage:
    set RAZORPAY_KEY_ID=rzp_test_...
    set RAZORPAY_KEY_SECRET=...
    py -m razorpay_integration.verify_live

What it does:
    - Creates a ₹500 test Payment Link and prints the real short_url
    - Attempts to fetch a known test payment (will 404 if the ID doesn't exist in your account)
    - Prints exactly what came back from the API so you can paste it into the README

What it does NOT do:
    - No real money moves (test mode only)
    - Does not trigger a webhook (that requires a tunnel and dashboard config)
"""

from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from razorpay_integration.client import is_live, create_payment_link, fetch_payment, _get_credentials

def main():
    print("=" * 70)
    print("RAZORPAY LIVE API VERIFICATION")
    print("=" * 70)

    key_id, _ = _get_credentials()
    if not is_live():
        print("\nERROR: No test-mode credentials configured.")
        print("Set RAZORPAY_KEY_ID=rzp_test_... and RAZORPAY_KEY_SECRET=...")
        print("Then re-run: py -m razorpay_integration.verify_live")
        sys.exit(1)

    print(f"\nCredentials detected: {key_id[:16]}...")
    print("Confirmed rzp_test_ prefix. Proceeding with live API calls.\n")

    # --- Test 1: Create a Payment Link ---
    print("TEST 1: Creating ₹500 Payment Link via api.razorpay.com/v1/payment_links")
    result = create_payment_link(
        amount_inr=500.0,
        description="Autopilot verify_live test — safe to cancel",
        payment_id_reference="verify_live_001",
        customer_email=None,
        expiry_hours=1,
    )

    if result.success and result.is_live_api:
        print(f"  ✓ LIVE API CALL CONFIRMED")
        print(f"  payment_link_id: {result.payment_link_id}")
        print(f"  short_url:       {result.short_url}")
        print(f"  amount_paise:    {result.amount_paise}")
        print(f"  is_live_api:     {result.is_live_api}")
        print(f"\n  >>> Paste this into your demo notes:")
        print(f"      Payment Link created: {result.short_url}")
        print(f"      (Test mode — no real money, openable in browser)")
        CHECK_1_PASSED = True
    elif result.success and not result.is_live_api:
        print(f"  ✗ Mock fallback triggered — credentials not working correctly")
        CHECK_1_PASSED = False
    else:
        print(f"  ✗ API call failed: {result.error}")
        CHECK_1_PASSED = False

    # --- Test 2: Fetch a payment (expected 404 if no real payments in account) ---
    print("\nTEST 2: Fetching test payment entity (expect 404 if account has no payments)")
    test_payment_id = "pay_test_verify001"
    fetch_result = fetch_payment(test_payment_id)
    if fetch_result.is_live_api:
        if fetch_result.success:
            print(f"  ✓ LIVE FETCH CONFIRMED: status={fetch_result.status}")
        else:
            print(f"  ✓ LIVE API REACHED (got error as expected for non-existent ID): {fetch_result.error}")
            print(f"    This confirms api.razorpay.com is reachable with these credentials.")
    else:
        print(f"  ✗ Mock fallback: {fetch_result.error}")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    if CHECK_1_PASSED:
        print("CHECK 2 (Payment Link): VERIFIED LIVE")
        print("  Paste the short_url above into your demo notes.")
        print("  The README can now say:")
        print("  'send_recovery_link creates a real Razorpay test-mode Payment Link'")
    else:
        print("CHECK 2 (Payment Link): NOT VERIFIED")
        print("  Check your RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET values.")

    print("\nCHECK 1 (Webhook from Razorpay servers): STILL NEEDS LIVE TUNNEL")
    print("  Steps:")
    print("  1. Install zrok: https://docs.zrok.io/docs/getting-started")
    print("  2. zrok share public http://localhost:8000")
    print("  3. Register https://<tunnel>/razorpay/webhook in Razorpay dashboard")
    print("     Subscribe to: payment.failed")
    print("  4. Trigger with test card 4100 2800 0008 0001 (insufficient_funds)")
    print("  5. Confirm the webhook POST arrives at /razorpay/webhook")
    print("     and /razorpay/status shows a processed event in the response.")
    print("=" * 70)


if __name__ == "__main__":
    main()
