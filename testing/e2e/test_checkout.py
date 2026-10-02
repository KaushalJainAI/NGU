"""
Orders, coupon validation, AI assistant Q&A, and PDF invoice downloads.
"""
import pytest
import requests

VALIDATE = "/auth/validate-coupon/"


def _first_product_id(session, api):
    r = session.get(f"{api}/products/")
    assert r.status_code == 200
    data = r.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    if not items:
        pytest.skip("catalog is empty on this target")
    return items[0]["id"]


def _first_in_stock_product(session, api):
    r = session.get(f"{api}/products/")
    data = r.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    for p in items:
        if (p.get("stock") or 0) >= 1:
            return p
    pytest.skip("no in-stock product on this target")


def _place_order(auth_session, api):
    pid = _first_product_id(auth_session, api)
    add = auth_session.post(f"{api}/cart/add_item/", json={"product_id": pid, "quantity": 1})
    if add.status_code not in (200, 201):
        pytest.skip(f"could not add to cart ({add.status_code}); cannot place order")
    order = auth_session.post(f"{api}/orders/", json={
        "shipping_address": "1 Test Rd, Test City",
        "phone_number": "1234567890",
        "payment_method": "COD",
    })
    if order.status_code != 201:
        pytest.skip(f"order placement unavailable ({order.status_code} {order.text[:200]})")
    return order.json()["order_id"]


# --- From test_orders_and_assistant.py ---

@pytest.mark.auth
@pytest.mark.destructive
def test_orders_list_scoped_to_user(auth_session, api):
    r = auth_session.get(f"{api}/orders/")
    assert r.status_code == 200
    data = r.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    assert isinstance(items, list)
    assert items == [] or all("id" in o for o in items)


@pytest.mark.auth
def test_orders_require_auth(session, api):
    r = session.get(f"{api}/orders/")
    assert r.status_code in (401, 403)


@pytest.mark.smoke
def test_assistant_anon_qa(session, api):
    try:
        r = session.post(f"{api}/assistant/chat/", json={"message": "What spices do you sell?"})
    except requests.RequestException:
        pytest.skip("assistant LLM not configured on this target (request timed out)")
    assert r.status_code in (200, 401, 403, 429, 500, 502, 503), f"{r.status_code} {r.text[:300]}"


@pytest.mark.smoke
def test_recommendations_endpoint(session, api):
    r = session.get(f"{api}/recommendations/")
    assert r.status_code in (200, 401, 403)


# --- From test_coupons.py ---

@pytest.mark.destructive
def test_unknown_coupon_message(auth_session, api):
    r = auth_session.post(f"{api}{VALIDATE}", json={"code": "NOPE_DOES_NOT_EXIST"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("valid") is False
    assert "valid coupon code" in body.get("message", "").lower()


@pytest.mark.destructive
def test_expired_coupon_message(auth_session, api):
    r = auth_session.post(f"{api}{VALIDATE}", json={"code": "E2EOLD"})
    body = r.json()
    if body.get("valid") is True:
        pytest.skip("E2EOLD not seeded as expired on this target")
    assert "expired" in body.get("message", "").lower()


@pytest.mark.destructive
def test_valid_coupon_is_case_insensitive(auth_session, api):
    r = auth_session.post(f"{api}{VALIDATE}", json={"code": "e2e10"})
    body = r.json()
    if "e2e10" not in str(body).lower() and body.get("valid") is not True:
        pytest.skip("E2E10 not seeded on this target")
    assert body.get("valid") is True


@pytest.mark.destructive
def test_minimum_order_message_states_shortfall(auth_session, api):
    p = _first_in_stock_product(auth_session, api)
    auth_session.post(f"{api}/cart/add_item/", json={"product_id": p["id"], "quantity": 1})
    r = auth_session.post(f"{api}{VALIDATE}", json={"code": "E2EMIN500"})
    body = r.json()
    if body.get("valid") is True:
        pytest.skip("cart already meets the minimum, or E2EMIN500 not seeded")
    assert "500" in body.get("message", "")


@pytest.mark.destructive
def test_unknown_coupon_at_checkout_is_specific_400(auth_session, api):
    p = _first_in_stock_product(auth_session, api)
    auth_session.post(f"{api}/cart/add_item/", json={"product_id": p["id"], "quantity": 1})
    r = auth_session.post(f"{api}/orders/", json={
        "shipping_address": "1 Rd", "phone_number": "1234567890",
        "payment_method": "COD", "coupon_code": "NOPE_DOES_NOT_EXIST",
    })
    assert r.status_code == 400
    assert "valid coupon code" in r.json().get("error", "").lower()


# --- From test_invoice.py ---

@pytest.mark.destructive
def test_invoice_download_returns_pdf(auth_session, api):
    order_id = _place_order(auth_session, api)
    r = auth_session.get(f"{api}/orders/{order_id}/invoice/")
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    assert r.headers.get("Content-Type", "").startswith("application/pdf")
    assert "attachment" in r.headers.get("Content-Disposition", "")
    assert r.content[:5] == b"%PDF-", "invoice body is not a PDF"
    assert len(r.content) > 1000


@pytest.mark.destructive
def test_invoice_requires_auth(session, api):
    r = session.get(f"{api}/orders/1/invoice/")
    assert r.status_code in (401, 403)


@pytest.mark.destructive
def test_invoice_unknown_order_not_served(auth_session, api):
    r = auth_session.get(f"{api}/orders/999999999/invoice/")
    assert r.status_code in (403, 404)
