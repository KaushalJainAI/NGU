"""
Razorpay payment endpoints — the NON-charging, prod-safe HTTP surface.

These tests never complete a real capture (only Razorpay can mint a valid
payment id + signature — that lives in the browser suite,
ui/record_payment_netbanking.cjs). Here we exercise everything reachable over
plain HTTP without moving money:

  * create-order/  — auth, ownership, server-side amount, idempotency
  * verify/        — the HMAC gate rejects a forged signature; auth + ownership
  * webhook/       — signature-gated: unsigned / bad-signature deliveries rejected
  * status/        — auth, ownership, honest labels
  * payment-methods CRUD — create / list / set-default / soft-delete (self-cleaning)

Anything that opens a live Razorpay order is gated behind
`require_razorpay_test_mode`, so it cannot fire against production while it is on
live keys. Every order these tests create is cancelled again in teardown.
"""
import uuid
import pytest
import requests

from conftest import first_in_stock_product


def _place_online_order(sess, api):
    p = first_in_stock_product(sess, api)
    sess.post(f"{api}/cart/add_item/", json={"product_id": p["id"], "quantity": 1})
    r = sess.post(f"{api}/orders/", json={
        "shipping_address": "1 E2E Test Rd, Test City",
        "phone_number": "9999999999",
        "payment_method": "ONLINE",
    })
    if r.status_code != 201:
        pytest.skip(f"could not place ONLINE order ({r.status_code} {r.text[:200]})")
    return r.json()["order_id"]


@pytest.fixture()
def online_order(account_session, api):
    """A fresh unpaid ONLINE order owned by the reusable account, cancelled on
    teardown so nothing lingers."""
    order_id = _place_online_order(account_session, api)
    yield order_id
    account_session.post(f"{api}/orders/{order_id}/cancel/")


# --------------------------------------------------------------------------- #
# create-order
# --------------------------------------------------------------------------- #

@pytest.mark.payment
def test_create_order_requires_auth(session, api):
    r = session.post(f"{api}/payments/create-order/", json={"order_id": 1})
    assert r.status_code in (401, 403)


@pytest.mark.payment
def test_create_order_rejects_unknown_order(account_session, api):
    r = account_session.post(f"{api}/payments/create-order/",
                             json={"order_id": 999999999})
    assert r.status_code == 404


@pytest.mark.payment
def test_create_order_amount_is_server_side_and_idempotent(
        require_razorpay_test_mode, account_session, api, online_order):
    """The client cannot influence the amount, and a second call returns the SAME
    Razorpay order — never a second live one the customer could also pay."""
    first = account_session.post(f"{api}/payments/create-order/",
                                 json={"order_id": online_order, "amount": 1})
    assert first.status_code == 200, first.text[:300]
    body = first.json()
    assert body["currency"] == "INR"
    assert body["amount"] != 1 and body["amount"] > 0  # server-computed, not injected
    assert body["razorpay_key_id"].startswith("rzp_test_")
    rzp_id = body["razorpay_order_id"]

    second = account_session.post(f"{api}/payments/create-order/",
                                  json={"order_id": online_order})
    assert second.status_code == 200
    assert second.json()["razorpay_order_id"] == rzp_id  # idempotent


@pytest.mark.payment
@pytest.mark.security
@pytest.mark.destructive
def test_create_order_rejects_other_users_order(
        require_razorpay_test_mode, account_session, api, online_order, new_user_payload, is_prod):
    """A different authenticated user must not open a Razorpay order for someone
    else's order id. Registers a throwaway user, so it skips on prod to keep the
    single-account guarantee."""
    if is_prod:
        pytest.skip("creates a second user — skipped against production")
    s = requests.Session()
    reg = s.post(f"{api}/auth/register/", json=new_user_payload)
    if reg.status_code not in (200, 201):
        pytest.skip(f"could not create a second user ({reg.status_code})")
    tok = s.post(f"{api}/auth/login/", json={
        "email": new_user_payload["email"],
        "password": new_user_payload["password"]}).json()["access"]
    s.headers.update({"Authorization": f"Bearer {tok}"})
    r = s.post(f"{api}/payments/create-order/", json={"order_id": online_order})
    assert r.status_code == 404, f"IDOR: got {r.status_code}"


# --------------------------------------------------------------------------- #
# verify (L1) — the browser fast-path. We only prove the HMAC gate REJECTS a
# forged signature; a *valid* signature is impossible to forge without Razorpay.
# --------------------------------------------------------------------------- #

@pytest.mark.payment
def test_verify_requires_auth(session, api):
    r = session.post(f"{api}/payments/verify/", json={
        "razorpay_order_id": "order_x", "razorpay_payment_id": "pay_x",
        "razorpay_signature": "sig"})
    assert r.status_code in (401, 403)


@pytest.mark.payment
@pytest.mark.security
def test_verify_forged_signature_rejected(
        require_razorpay_test_mode, account_session, api, online_order):
    co = account_session.post(f"{api}/payments/create-order/",
                              json={"order_id": online_order})
    rzp_id = co.json()["razorpay_order_id"]
    r = account_session.post(f"{api}/payments/verify/", json={
        "razorpay_order_id": rzp_id,
        "razorpay_payment_id": "pay_FORGED",
        "razorpay_signature": "deadbeef" * 8,  # not a valid HMAC
    })
    assert r.status_code == 400, f"forged signature accepted? {r.status_code} {r.text[:200]}"
    # The order must remain unpaid.
    st = account_session.get(f"{api}/payments/status/", params={"order_id": online_order})
    assert st.json()["payment_status"] != "paid"


@pytest.mark.payment
def test_verify_unknown_order_is_404(account_session, api):
    r = account_session.post(f"{api}/payments/verify/", json={
        "razorpay_order_id": f"order_{uuid.uuid4().hex}",
        "razorpay_payment_id": "pay_x", "razorpay_signature": "sig"})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# webhook (L2) — signature-gated, no auth. We cannot forge a valid signature
# (secret is server-side), so we assert every UNSIGNED / BAD delivery is
# rejected and NEVER 500s.
# --------------------------------------------------------------------------- #

CAPTURED_BODY = (
    '{"event":"payment.captured","payload":{"payment":{"entity":'
    '{"id":"pay_E2E","order_id":"order_E2E","amount":100,"status":"captured"}}}}'
)


@pytest.mark.payment
@pytest.mark.security
def test_webhook_unsigned_rejected(session, api):
    r = session.post(f"{api}/payments/webhook/", data=CAPTURED_BODY,
                     headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.status_code < 500


@pytest.mark.payment
@pytest.mark.security
def test_webhook_bad_signature_rejected(session, api):
    r = session.post(f"{api}/payments/webhook/", data=CAPTURED_BODY,
                     headers={"Content-Type": "application/json",
                              "X-Razorpay-Signature": "not-a-real-signature",
                              "X-Razorpay-Event-Id": f"e2e-{uuid.uuid4().hex}"})
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #

@pytest.mark.payment
def test_status_requires_auth(session, api):
    r = session.get(f"{api}/payments/status/", params={"order_id": 1})
    assert r.status_code in (401, 403)


@pytest.mark.payment
def test_status_reports_honest_label(account_session, api, online_order):
    r = account_session.get(f"{api}/payments/status/", params={"order_id": online_order})
    assert r.status_code == 200
    body = r.json()
    assert body["order_id"] == online_order
    assert "payment_status" in body and "label" in body
    # A fresh unpaid order must never be labelled a failure.
    assert body["payment_status"] in ("pending", "processing")


@pytest.mark.payment
@pytest.mark.security
@pytest.mark.destructive
def test_status_rejects_other_users_order(account_session, api, online_order, new_user_payload, is_prod):
    if is_prod:
        pytest.skip("creates a second user — skipped against production")
    s = requests.Session()
    reg = s.post(f"{api}/auth/register/", json=new_user_payload)
    if reg.status_code not in (200, 201):
        pytest.skip("could not create a second user")
    tok = s.post(f"{api}/auth/login/", json={
        "email": new_user_payload["email"],
        "password": new_user_payload["password"]}).json()["access"]
    s.headers.update({"Authorization": f"Bearer {tok}"})
    r = s.get(f"{api}/payments/status/", params={"order_id": online_order})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# saved payment methods (self-cleaning CRUD)
# --------------------------------------------------------------------------- #

@pytest.mark.payment
def test_payment_methods_require_auth(session, api):
    r = session.get(f"{api}/payment-methods/")
    assert r.status_code in (401, 403)


@pytest.mark.payment
def test_payment_method_crud_lifecycle(account_session, api):
    """Create → appears in list → set default → soft-delete. Self-cleaning.

    The create serializer does not echo the id, so we resolve it from the list
    by the unique upi_id we just submitted (the read serializer includes id)."""
    upi_id = f"e2e{uuid.uuid4().hex[:6]}@okhdfcbank"
    create = account_session.post(f"{api}/payment-methods/", json={
        "payment_type": "UPI", "upi_id": upi_id,
    })
    if create.status_code not in (200, 201):
        pytest.skip(f"payment-method create unavailable ({create.status_code} "
                    f"{create.text[:200]})")

    def _rows():
        body = account_session.get(f"{api}/payment-methods/").json()
        return body.get("results") if isinstance(body, dict) and "results" in body else body

    rows = _rows()
    mine = next((m for m in rows if m.get("upi_id") == upi_id), None)
    assert mine, f"created method not found in list: {rows}"
    pm_id = mine["id"]
    try:
        sd = account_session.post(f"{api}/payment-methods/{pm_id}/set_default/")
        assert sd.status_code in (200, 201)
    finally:
        # Soft-delete so we don't accumulate methods on the reusable account.
        account_session.delete(f"{api}/payment-methods/{pm_id}/")
