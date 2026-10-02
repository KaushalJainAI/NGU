"""
Account + cart edge cases, exercised on the reusable account and fully
self-cleaning (every cart item / favorite added here is removed again).

  * cart: add → view → update quantity → remove; sync a set then clear
  * favorites: add → list → remove (by product id)
  * profile: read is scoped and well-formed (no mutation of the shared account)
  * password reset: request is anti-enumeration (200 for unknown email), and
    validates its input — we never complete a reset (that needs the emailed OTP)
"""
import uuid
import pytest

from conftest import first_in_stock_product


# --------------------------------------------------------------------------- #
# cart
# --------------------------------------------------------------------------- #

@pytest.mark.cart
def test_cart_add_update_remove(account_session, api):
    p = first_in_stock_product(account_session, api, min_stock=3)
    try:
        add = account_session.post(f"{api}/cart/add_item/",
                                   json={"product_id": p["id"], "quantity": 1})
        assert add.status_code in (200, 201), add.text[:200]

        view = account_session.get(f"{api}/cart/")
        assert view.status_code == 200

        upd = account_session.post(f"{api}/cart/update_item/",
                                   json={"product_id": p["id"], "quantity": 3})
        assert upd.status_code in (200, 201), upd.text[:200]

        rem = account_session.post(f"{api}/cart/remove_item/",
                                   json={"product_id": p["id"]})
        assert rem.status_code in (200, 204)
    finally:
        account_session.post(f"{api}/cart/clear/")


@pytest.mark.cart
def test_cart_sync_then_clear(account_session, api):
    p = first_in_stock_product(account_session, api, min_stock=2)
    try:
        r = account_session.post(f"{api}/cart/sync/",
                                 json={"items": [{"product_id": p["id"], "quantity": 2}]})
        assert r.status_code in (200, 201), r.text[:200]
        view = account_session.get(f"{api}/cart/")
        assert view.status_code == 200
    finally:
        clr = account_session.post(f"{api}/cart/clear/")
        assert clr.status_code in (200, 204)


@pytest.mark.cart
def test_cart_rejects_zero_and_negative_quantity(account_session, api):
    p = first_in_stock_product(account_session, api)
    for bad in (0, -5):
        r = account_session.post(f"{api}/cart/add_item/",
                                 json={"product_id": p["id"], "quantity": bad})
        assert r.status_code == 400, f"quantity {bad} accepted ({r.status_code})"


# --------------------------------------------------------------------------- #
# favorites
# --------------------------------------------------------------------------- #

@pytest.mark.cart
def test_favorites_add_list_remove(account_session, api):
    p = first_in_stock_product(account_session, api)
    add = account_session.post(f"{api}/favorites/", json={"product_id": p["id"]})
    assert add.status_code in (200, 201), add.text[:200]
    try:
        lst = account_session.get(f"{api}/favorites/")
        assert lst.status_code == 200
    finally:
        rem = account_session.delete(f"{api}/favorites/{p['id']}/")
        assert rem.status_code in (200, 204, 404)


# --------------------------------------------------------------------------- #
# profile (read-only on the shared account — never mutate its login identity)
# --------------------------------------------------------------------------- #

@pytest.mark.auth
def test_profile_is_scoped_and_wellformed(account_session, shared_account, api):
    r = account_session.get(f"{api}/auth/profile/")
    assert r.status_code == 200
    body = r.json()
    assert body.get("email") == shared_account["email"]


# --------------------------------------------------------------------------- #
# password reset — request side only (completing needs the emailed OTP)
# --------------------------------------------------------------------------- #

@pytest.mark.auth
def test_password_reset_request_does_not_enumerate(session, api):
    """An unknown email must return the same 200 as a known one — no user
    enumeration. We use a random address so no real reset email is triggered."""
    r = session.post(f"{api}/auth/password-reset-request/",
                     json={"email": f"nobody_{uuid.uuid4().hex}@example.com"})
    assert r.status_code in (200, 202), f"{r.status_code} {r.text[:200]}"


@pytest.mark.auth
def test_password_reset_request_validates_email(session, api):
    r = session.post(f"{api}/auth/password-reset-request/", json={"email": "not-an-email"})
    assert r.status_code == 400


@pytest.mark.auth
def test_password_reset_verify_rejects_bad_otp(session, api):
    r = session.post(f"{api}/auth/password-reset-verify/",
                     json={"email": f"nobody_{uuid.uuid4().hex}@example.com", "otp": "000000"})
    assert r.status_code == 400
