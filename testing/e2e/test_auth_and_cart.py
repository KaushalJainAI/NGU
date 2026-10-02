"""
Authentication flows, registration, password validation, profile management, email normalization/integrity, cart lifecycle, favorites, and input bounds.
"""
import uuid
import pytest

MAX_ITEM_QUANTITY = 100
MAX_SYNC_ITEMS = 100
MAX_REVIEW_COMMENT = 2000


def _first_in_stock_product(session, api, min_stock=1):
    r = session.get(f"{api}/products/")
    assert r.status_code == 200
    data = r.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    for p in items:
        if (p.get("stock") or 0) >= min_stock:
            return p
    pytest.skip(f"no product with stock >= {min_stock} on this target")


def _first_product_id(session, api, min_stock=1):
    return _first_in_stock_product(session, api, min_stock=min_stock)["id"]


# --- From test_auth_flow.py ---

@pytest.mark.auth
@pytest.mark.destructive
def test_register_login_profile(auth_session, api, registered_user):
    payload, _token = registered_user
    r = auth_session.get(f"{api}/auth/profile/")
    assert r.status_code == 200
    body = r.json()
    assert body.get("email") == payload["email"]
    assert body.get("username") == payload["username"]


@pytest.mark.auth
@pytest.mark.destructive
def test_profile_requires_auth(session, api):
    r = session.get(f"{api}/auth/profile/")
    assert r.status_code in (401, 403)


@pytest.mark.auth
@pytest.mark.destructive
def test_register_password_mismatch_rejected(session, api, is_prod, new_user_payload):
    if is_prod:
        pytest.skip("destructive test skipped against production target")
    new_user_payload["password2"] = "totally-different"
    r = session.post(f"{api}/auth/register/", json=new_user_payload)
    assert r.status_code == 400
    assert "password" in r.text.lower()


@pytest.mark.auth
@pytest.mark.destructive
def test_register_weak_password_rejected(session, api, is_prod, new_user_payload):
    if is_prod:
        pytest.skip("destructive test skipped against production target")
    new_user_payload["password"] = new_user_payload["password2"] = "123"
    r = session.post(f"{api}/auth/register/", json=new_user_payload)
    assert r.status_code == 400


@pytest.mark.auth
@pytest.mark.destructive
def test_token_refresh(session, api, registered_user):
    payload, _ = registered_user
    login = session.post(
        f"{api}/auth/login/",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200
    refresh = login.json().get("refresh")
    assert refresh
    r = session.post(f"{api}/auth/token/refresh/", json={"refresh": refresh})
    assert r.status_code == 200
    assert r.json().get("access")


@pytest.mark.auth
def test_login_wrong_password(session, api):
    r = session.post(
        f"{api}/auth/login/",
        json={"username": "definitely-not-a-real-user", "password": "wrong"},
    )
    assert r.status_code in (400, 401)


# --- From test_account_integrity.py ---

def _payload(email):
    s = uuid.uuid4().hex[:8]
    return {
        "username": f"acc_{s}", "email": email, "name": "Acc",
        "first_name": "Acc", "last_name": "Test", "phone": "9999999999",
        "password": f"Sup3r$ecret!{s[:4]}", "password2": f"Sup3r$ecret!{s[:4]}",
    }


@pytest.mark.auth
@pytest.mark.destructive
def test_register_case_variant_email_rejected(session, api, is_prod):
    if is_prod:
        pytest.skip("destructive test skipped against production target")
    base = f"dup_{uuid.uuid4().hex[:8]}@example.com"
    first = session.post(f"{api}/auth/register/", json=_payload(base))
    assert first.status_code in (200, 201), first.text[:200]
    second = session.post(f"{api}/auth/register/", json=_payload(base.upper()))
    assert second.status_code == 400


@pytest.mark.auth
@pytest.mark.destructive
def test_profile_email_case_collision_is_clean_400(auth_session, session, api, is_prod):
    if is_prod:
        pytest.skip("destructive test skipped against production target")
    victim_email = f"victim_{uuid.uuid4().hex[:8]}@example.com"
    reg = session.post(f"{api}/auth/register/", json=_payload(victim_email))
    assert reg.status_code in (200, 201)
    r = auth_session.patch(f"{api}/auth/profile/", json={"email": victim_email.upper()})
    assert r.status_code == 400


@pytest.mark.auth
@pytest.mark.destructive
def test_profile_email_normalized_to_lowercase(auth_session, api, is_prod):
    if is_prod:
        pytest.skip("destructive test skipped against production target")
    new_email = f"Mixed_{uuid.uuid4().hex[:8]}@Example.COM"
    r = auth_session.patch(f"{api}/auth/profile/", json={"email": new_email})
    assert r.status_code in (200, 202)
    prof = auth_session.get(f"{api}/auth/profile/")
    assert prof.json().get("email") == new_email.lower()


# --- From test_cart_and_favorites.py ---

@pytest.mark.cart
@pytest.mark.destructive
def test_cart_add_view_update_clear(auth_session, api):
    pid = _first_product_id(auth_session, api, min_stock=2)

    add = auth_session.post(f"{api}/cart/add_item/", json={"product_id": pid, "quantity": 2})
    assert add.status_code in (200, 201), f"add_item: {add.status_code} {add.text[:300]}"

    view = auth_session.get(f"{api}/cart/")
    assert view.status_code == 200

    clear = auth_session.post(f"{api}/cart/clear/")
    assert clear.status_code in (200, 204)


@pytest.mark.cart
@pytest.mark.destructive
def test_cart_rejects_zero_and_negative_quantity(auth_session, api):
    pid = _first_product_id(auth_session, api)
    for bad in (0, -5):
        r = auth_session.post(f"{api}/cart/add_item/", json={"product_id": pid, "quantity": bad})
        assert r.status_code == 400, f"quantity {bad} should be rejected, got {r.status_code}"


@pytest.mark.cart
@pytest.mark.destructive
def test_cart_add_nonexistent_product(auth_session, api):
    r = auth_session.post(f"{api}/cart/add_item/", json={"product_id": 999999999, "quantity": 1})
    assert r.status_code in (400, 404)


@pytest.mark.cart
def test_cart_requires_auth(session, api):
    r = session.get(f"{api}/cart/")
    assert r.status_code in (401, 403)


@pytest.mark.cart
@pytest.mark.destructive
def test_favorites_lifecycle(auth_session, api):
    pid = _first_product_id(auth_session, api)
    add = auth_session.post(f"{api}/favorites/", json={"product_id": pid})
    assert add.status_code in (200, 201, 400)
    lst = auth_session.get(f"{api}/favorites/")
    assert lst.status_code == 200


# --- From test_input_bounds.py (cart/review bounds) ---

@pytest.mark.cart
@pytest.mark.destructive
def test_cart_add_quantity_over_max_rejected(auth_session, api):
    p = _first_in_stock_product(auth_session, api)
    r = auth_session.post(f"{api}/cart/add_item/",
                          json={"product_id": p["id"], "quantity": MAX_ITEM_QUANTITY + 1})
    assert r.status_code == 400
    assert str(MAX_ITEM_QUANTITY) in r.json().get("error", "")


@pytest.mark.cart
@pytest.mark.destructive
def test_cart_add_quantity_at_max_ok(auth_session, api):
    p = _first_in_stock_product(auth_session, api, min_stock=MAX_ITEM_QUANTITY)
    r = auth_session.post(f"{api}/cart/add_item/",
                          json={"product_id": p["id"], "quantity": MAX_ITEM_QUANTITY})
    assert r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}"


@pytest.mark.cart
@pytest.mark.destructive
def test_cart_sync_payload_size_capped(auth_session, api):
    p = _first_in_stock_product(auth_session, api)
    items = [{"product_id": p["id"], "quantity": 1} for _ in range(MAX_SYNC_ITEMS + 1)]
    r = auth_session.post(f"{api}/cart/sync/", json={"items": items})
    assert r.status_code == 400
    assert str(MAX_SYNC_ITEMS) in r.json().get("error", "")


@pytest.mark.destructive
def test_review_oversized_comment_rejected_not_500(auth_session, api):
    p = _first_in_stock_product(auth_session, api)
    huge = "x" * (MAX_REVIEW_COMMENT + 50)
    r = auth_session.post(f"{api}/reviews/", json={
        "item_type": "product", "product": p["id"], "rating": 5, "title": "t", "comment": huge,
    })
    assert r.status_code == 400
