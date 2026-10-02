"""
Access control: authentication guards and cross-tenant isolation (BOLA/IDOR).
"""
import uuid
import pytest
import requests

PROTECTED_GET = [
    "/cart/",
    "/favorites/",
    "/orders/",
    "/auth/profile/",
    "/payment-methods/",
    "/recommendations/",
    "/assistant/conversations/",
]

ADMIN_ONLY_GET = [
    "/dashboard/",
    "/receivable-accounts/",
    "/coupons/",
    "/assistant/conversations/admin/",
    "/contact/",
]


# --- From test_auth_guards.py ---

@pytest.mark.security
@pytest.mark.parametrize("path", PROTECTED_GET)
def test_protected_endpoints_reject_anonymous(session, api, path):
    r = session.get(f"{api}{path}")
    assert r.status_code in (401, 403), (
        f"{path} returned {r.status_code} to an anonymous client — possible "
        f"broken access control. Body: {r.text[:200]}"
    )


@pytest.mark.security
@pytest.mark.parametrize("path", ADMIN_ONLY_GET)
def test_admin_endpoints_reject_normal_users(auth_session, api, path):
    """A logged-in but non-staff user must not reach admin endpoints."""
    r = auth_session.get(f"{api}{path}")
    assert r.status_code in (401, 403), (
        f"{path} returned {r.status_code} to a non-staff user — privilege "
        f"escalation risk. Body: {r.text[:200]}"
    )


@pytest.mark.security
def test_garbage_bearer_token_rejected(session, api):
    session.headers.update({"Authorization": "Bearer not.a.real.jwt"})
    r = session.get(f"{api}/auth/profile/")
    assert r.status_code in (401, 403)


@pytest.mark.security
def test_admin_django_panel_not_anonymously_browsable(session, base_url):
    """The Django admin must redirect to login, not expose model data."""
    r = session.get(f"{base_url}/admin/", allow_redirects=False)
    assert r.status_code in (301, 302, 401, 403)


# --- From test_bola.py ---

def _make_user(api):
    suffix = uuid.uuid4().hex[:10]
    payload = {
        "username": f"bola_{suffix}",
        "email": f"bola_{suffix}@example.com",
        "name": "BOLA Tester",
        "first_name": "BOLA",
        "last_name": "Tester",
        "phone": "9999999999",
        "password": f"Sup3r$ecret!{suffix[:4]}",
        "password2": f"Sup3r$ecret!{suffix[:4]}",
    }
    s = requests.Session()
    reg = s.post(f"{api}/auth/register/", json=payload, timeout=20)
    assert reg.status_code in (200, 201), reg.text[:200]
    login = s.post(
        f"{api}/auth/login/",
        json={"email": payload["email"], "password": payload["password"]},
        timeout=20,
    )
    assert login.status_code == 200, login.text[:200]
    return login.json()["access"]


@pytest.mark.security
@pytest.mark.destructive
def test_users_cannot_see_each_others_orders(session, api, is_prod):
    if is_prod:
        pytest.skip("destructive test skipped against production target")
    token_a = _make_user(api)
    token_b = _make_user(api)

    session.headers.update({"Authorization": f"Bearer {token_a}"})
    a_orders = session.get(f"{api}/orders/")
    assert a_orders.status_code == 200

    session.headers.update({"Authorization": f"Bearer {token_b}"})
    b_orders = session.get(f"{api}/orders/")
    assert b_orders.status_code == 200

    def ids(resp):
        data = resp.json()
        items = data["results"] if isinstance(data, dict) and "results" in data else data
        return {o.get("id") for o in items}

    assert ids(a_orders).isdisjoint(ids(b_orders)) or (not ids(a_orders) and not ids(b_orders))


@pytest.mark.security
@pytest.mark.destructive
def test_order_detail_idor(session, api, is_prod):
    """Fetching a low / guessable order id as a fresh user must 403/404, not 200."""
    if is_prod:
        pytest.skip("destructive test skipped against production target")
    token = _make_user(api)
    session.headers.update({"Authorization": f"Bearer {token}"})
    for oid in (1, 2, 3):
        r = session.get(f"{api}/orders/{oid}/")
        assert r.status_code in (403, 404), (
            f"order {oid} returned {r.status_code} to an unrelated user — IDOR risk"
        )
