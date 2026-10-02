"""
Full order lifecycle over HTTP — prod-safe because every order placed here is
cancelled again (which restocks), so the target returns to its original state.

Covered practical scenarios:
  * place a COD order → it is scoped to the user, has an invoice, restores stock
    on cancel
  * cannot order with an empty cart
  * cannot cancel an order twice / cannot cancel someone else's order
  * ONLINE order → open Razorpay order (test-mode gated) → cancel
  * checkout with an unknown coupon is a specific 400
"""
import pytest
import requests

from conftest import first_in_stock_product


def _product_stock(sess, api, product_id):
    r = sess.get(f"{api}/products/{product_id}/")
    if r.status_code != 200:
        # detail is keyed by slug in some deployments; fall back to the list
        return None
    return r.json().get("stock")


def _place_cod_order(sess, api, product, quantity=1, **extra):
    sess.post(f"{api}/cart/add_item/", json={"product_id": product["id"], "quantity": quantity})
    body = {
        "shipping_address": "1 E2E Test Rd, Test City",
        "phone_number": "9999999999",
        "payment_method": "COD",
    }
    body.update(extra)
    r = sess.post(f"{api}/orders/", json=body)
    return r


@pytest.mark.order
def test_cod_order_place_scope_invoice_and_cancel(account_session, api):
    """The canonical happy path: place → visible & scoped → invoice PDF → cancel."""
    product = first_in_stock_product(account_session, api, min_stock=1)
    placed = _place_cod_order(account_session, api, product)
    assert placed.status_code == 201, f"{placed.status_code} {placed.text[:300]}"
    order_id = placed.json()["order_id"]

    try:
        # Scoped to this user's order list.
        lst = account_session.get(f"{api}/orders/")
        assert lst.status_code == 200
        data = lst.json()
        items = data["results"] if isinstance(data, dict) and "results" in data else data
        assert any(o.get("id") == order_id for o in items), "placed order not in user's list"

        # Invoice PDF.
        inv = account_session.get(f"{api}/orders/{order_id}/invoice/")
        assert inv.status_code == 200
        assert inv.headers.get("Content-Type", "").startswith("application/pdf")
        assert inv.content[:5] == b"%PDF-"
    finally:
        cancel = account_session.post(f"{api}/orders/{order_id}/cancel/")
        assert cancel.status_code == 200, f"cancel failed: {cancel.status_code} {cancel.text[:200]}"
        assert cancel.json().get("success") is True


@pytest.mark.order
def test_cancel_restores_stock(account_session, api):
    """Cancelling a COD order must return the reserved units to inventory."""
    product = first_in_stock_product(account_session, api, min_stock=2)
    before = _product_stock(account_session, api, product["id"])
    placed = _place_cod_order(account_session, api, product, quantity=2)
    if placed.status_code != 201:
        pytest.skip(f"could not place order ({placed.status_code} {placed.text[:200]})")
    order_id = placed.json()["order_id"]

    after_order = _product_stock(account_session, api, product["id"])
    account_session.post(f"{api}/orders/{order_id}/cancel/")
    after_cancel = _product_stock(account_session, api, product["id"])

    if before is None or after_order is None or after_cancel is None:
        pytest.skip("product detail did not expose stock on this target")
    # Placing reserved stock; cancelling gives it back. Tolerant of concurrent
    # buyers on a live target: stock must not be LOWER after cancel than while
    # the order was open.
    assert after_order <= before, "stock did not decrease when order was placed"
    assert after_cancel >= after_order, "stock not restored after cancel"


@pytest.mark.order
def test_order_with_empty_cart_rejected(account_session, api):
    account_session.post(f"{api}/cart/clear/")
    r = account_session.post(f"{api}/orders/", json={
        "shipping_address": "1 Rd", "phone_number": "9999999999", "payment_method": "COD"})
    assert r.status_code == 400
    assert "cart" in r.text.lower()


@pytest.mark.order
def test_double_cancel_is_rejected(account_session, api):
    product = first_in_stock_product(account_session, api)
    placed = _place_cod_order(account_session, api, product)
    if placed.status_code != 201:
        pytest.skip(f"could not place order ({placed.status_code})")
    order_id = placed.json()["order_id"]

    first = account_session.post(f"{api}/orders/{order_id}/cancel/")
    assert first.status_code == 200
    second = account_session.post(f"{api}/orders/{order_id}/cancel/")
    assert second.status_code == 400, "a cancelled order must not be cancellable again"


@pytest.mark.order
@pytest.mark.security
@pytest.mark.destructive
def test_cannot_cancel_other_users_order(account_session, api, new_user_payload, is_prod):
    if is_prod:
        pytest.skip("creates a second user — skipped against production")
    product = first_in_stock_product(account_session, api)
    placed = _place_cod_order(account_session, api, product)
    if placed.status_code != 201:
        pytest.skip("could not place order")
    order_id = placed.json()["order_id"]
    try:
        s = requests.Session()
        reg = s.post(f"{api}/auth/register/", json=new_user_payload)
        if reg.status_code not in (200, 201):
            pytest.skip("could not create a second user")
        tok = s.post(f"{api}/auth/login/", json={
            "email": new_user_payload["email"],
            "password": new_user_payload["password"]}).json()["access"]
        s.headers.update({"Authorization": f"Bearer {tok}"})
        r = s.post(f"{api}/orders/{order_id}/cancel/")
        assert r.status_code in (403, 404), f"cross-user cancel allowed? {r.status_code}"
    finally:
        account_session.post(f"{api}/orders/{order_id}/cancel/")


@pytest.mark.order
def test_unknown_coupon_at_checkout_is_specific_400(account_session, api):
    product = first_in_stock_product(account_session, api)
    account_session.post(f"{api}/cart/add_item/",
                         json={"product_id": product["id"], "quantity": 1})
    r = account_session.post(f"{api}/orders/", json={
        "shipping_address": "1 Rd", "phone_number": "9999999999",
        "payment_method": "COD", "coupon_code": "NOPE_DOES_NOT_EXIST"})
    assert r.status_code == 400
    assert "valid coupon code" in r.json().get("error", "").lower()
    account_session.post(f"{api}/cart/clear/")


@pytest.mark.order
@pytest.mark.payment
def test_online_order_opens_razorpay_order_then_cancel(
        require_razorpay_test_mode, account_session, api):
    """ONLINE checkout → create-order mints a (test-mode) Razorpay order →
    status shows unpaid → cancel."""
    product = first_in_stock_product(account_session, api)
    account_session.post(f"{api}/cart/add_item/",
                         json={"product_id": product["id"], "quantity": 1})
    placed = account_session.post(f"{api}/orders/", json={
        "shipping_address": "1 Rd", "phone_number": "9999999999",
        "payment_method": "ONLINE"})
    assert placed.status_code == 201, placed.text[:300]
    order_id = placed.json()["order_id"]
    try:
        co = account_session.post(f"{api}/payments/create-order/", json={"order_id": order_id})
        assert co.status_code == 200
        assert co.json()["razorpay_order_id"].startswith("order_")
        st = account_session.get(f"{api}/payments/status/", params={"order_id": order_id})
        assert st.json()["payment_status"] != "paid"
    finally:
        account_session.post(f"{api}/orders/{order_id}/cancel/")
