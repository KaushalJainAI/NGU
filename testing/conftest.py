"""
Shared fixtures for the NGU end-to-end test suite.

Configuration is via environment variables so the same suite can run against a
local docker stack, staging, or production (read-only):

    NGU_BASE_URL   Base URL of the API host. Default: http://localhost:8000
                   (the suite appends `/api/...` itself).
    NGU_IS_PROD    "1" to mark the target as production. Destructive tests
                   (anything that writes/mutates data) are skipped automatically.
    NGU_TIMEOUT    Per-request timeout in seconds. Default: 15.

Example:
    NGU_BASE_URL=https://nidhimasala.com pytest -m "smoke or security"
"""
import os
import time
import uuid

import pytest
import requests


def _env_base_url() -> str:
    raw = os.environ.get("NGU_BASE_URL", "http://localhost:8000").rstrip("/")
    # Allow callers to pass either the host or the host + /api
    if raw.endswith("/api"):
        raw = raw[: -len("/api")]
    return raw


def pytest_configure(config):
    config._ngu_base_url = _env_base_url()


@pytest.fixture(scope="session")
def base_url() -> str:
    return _env_base_url()


@pytest.fixture(scope="session")
def api(base_url) -> str:
    """Convenience: the `/api` root."""
    return f"{base_url}/api"


@pytest.fixture(scope="session")
def timeout() -> float:
    return float(os.environ.get("NGU_TIMEOUT", "15"))


@pytest.fixture(scope="session")
def is_prod() -> bool:
    if os.environ.get("NGU_IS_PROD"):
        return os.environ["NGU_IS_PROD"] not in ("0", "false", "False", "")
    # Heuristic: treat the known live host as production.
    return "nidhimasala.com" in _env_base_url()


@pytest.fixture()
def session(timeout):
    """A requests.Session with a sane default timeout via a wrapper."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "User-Agent": "ngu-e2e/1.0"})

    orig_request = s.request

    def _request(method, url, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return orig_request(method, url, **kwargs)

    s.request = _request  # type: ignore[assignment]
    return s


@pytest.fixture(scope="session", autouse=True)
def _require_server(timeout):
    """Fail fast with a clear message if the target API is unreachable."""
    url = f"{_env_base_url()}/api/health/"
    try:
        r = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        pytest.exit(
            f"\nTarget API unreachable at {url}\n"
            f"  -> {exc}\n"
            f"Start the backend or set NGU_BASE_URL.\n",
            returncode=3,
        )
    if r.status_code != 200:
        pytest.exit(
            f"\nHealth check at {url} returned {r.status_code}, expected 200.\n",
            returncode=3,
        )


def _skip_if_prod(is_prod):
    if is_prod:
        pytest.skip("destructive test skipped against production target")


@pytest.fixture()
def new_user_payload():
    """A unique registration payload that won't collide between runs."""
    suffix = uuid.uuid4().hex[:10]
    return {
        "username": f"e2e_{suffix}",
        "email": f"e2e_{suffix}@example.com",
        "name": "E2E Tester",
        "first_name": "E2E",
        "last_name": "Tester",
        "phone": "9999999999",
        "password": "Sup3r$ecret!{}".format(suffix[:4]),
        "password2": "Sup3r$ecret!{}".format(suffix[:4]),
    }


@pytest.fixture()
def registered_user(session, api, is_prod, new_user_payload):
    """
    Register a throwaway user and return (payload, access_token).

    Skipped on production targets because it writes a user row.
    """
    _skip_if_prod(is_prod)
    r = session.post(f"{api}/auth/register/", json=new_user_payload)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text[:300]}"

    # The User model's USERNAME_FIELD is `email`, so login authenticates by email.
    login = session.post(
        f"{api}/auth/login/",
        json={
            "email": new_user_payload["email"],
            "password": new_user_payload["password"],
        },
    )
    assert login.status_code == 200, f"login failed: {login.status_code} {login.text[:300]}"
    token = login.json().get("access")
    assert token, f"no access token in login response: {login.text[:300]}"
    return new_user_payload, token


@pytest.fixture()
def auth_session(session, registered_user):
    """A session pre-authenticated as a fresh throwaway user."""
    _payload, token = registered_user
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


# ---------------------------------------------------------------------------
# Reusable, prod-safe account
#
# Against production we must NOT mint a new user row every run. When
# NGU_TEST_ACCOUNT_EMAIL / NGU_TEST_ACCOUNT_PASSWORD are set, the whole suite
# authenticates as that single, known account (registered once, idempotently).
# When they are unset (local / e2e-server runs) it falls back to a per-session
# throwaway account so the suite still works with zero configuration.
#
# Tests that use `account_session` are expected to be *self-cleaning*: whatever
# they create (cart items, favorites, COD orders) they must undo (clear the
# cart, remove the favorite, cancel the order — which also restocks). The only
# tolerated residue on prod is cancelled-order rows on this one account.
# ---------------------------------------------------------------------------

def _shared_account_creds() -> tuple[str, str, bool]:
    """Return (email, password, is_reused). is_reused=True means an env-pinned
    account (safe to reuse on prod); False means a random per-session one."""
    email = os.environ.get("NGU_TEST_ACCOUNT_EMAIL")
    pw = os.environ.get("NGU_TEST_ACCOUNT_PASSWORD")
    if email and pw:
        return email, pw, True
    suffix = uuid.uuid4().hex[:10]
    return f"e2e_shared_{suffix}@example.com", f"Sup3r$ecret!{suffix[:4]}", False


@pytest.fixture(scope="session")
def shared_account(timeout) -> dict:
    """A single reusable account. Registers it if it does not exist yet
    (a 400 on register is treated as 'already exists'), then logs in.

    Returns {'email', 'password', 'token', 'reused'}.
    """
    base = _env_base_url()
    email, pw, reused = _shared_account_creds()
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "User-Agent": "ngu-e2e/1.0"})

    payload = {
        "username": email.split("@")[0][:150],
        "email": email,
        "name": "E2E Reusable",
        "first_name": "E2E",
        "last_name": "Reusable",
        "phone": "9999999999",
        "password": pw,
        "password2": pw,
    }
    # Idempotent: 200/201 = created now; 400 = already registered (expected on
    # every run after the first against a pinned account). Anything else is a
    # real problem worth surfacing.
    reg = s.post(f"{base}/api/auth/register/", json=payload, timeout=timeout)
    assert reg.status_code in (200, 201, 400), (
        f"register for reusable account failed unexpectedly: "
        f"{reg.status_code} {reg.text[:200]}"
    )

    login = s.post(
        f"{base}/api/auth/login/",
        json={"email": email, "password": pw},
        timeout=timeout,
    )
    assert login.status_code == 200, (
        f"login for reusable account {email!r} failed: "
        f"{login.status_code} {login.text[:200]}. If this account exists with a "
        f"different password, set NGU_TEST_ACCOUNT_PASSWORD to match."
    )
    token = login.json().get("access")
    assert token, f"no access token in login response: {login.text[:200]}"
    return {"email": email, "password": pw, "token": token, "reused": reused}


@pytest.fixture()
def account_session(session, shared_account):
    """A session authenticated as the reusable account. Safe against prod."""
    session.headers.update({"Authorization": f"Bearer {shared_account['token']}"})
    return session


# ---------------------------------------------------------------------------
# Catalog helpers (shared across the functional suites)
# ---------------------------------------------------------------------------

def first_in_stock_product(session, api, min_stock: int = 1) -> dict:
    """First active product with at least `min_stock` on hand, else skip."""
    r = session.get(f"{api}/products/")
    assert r.status_code == 200, f"products list failed: {r.status_code}"
    data = r.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    for p in items:
        if (p.get("stock") or 0) >= min_stock:
            return p
    pytest.skip(f"no product with stock >= {min_stock} on this target")


# ---------------------------------------------------------------------------
# Razorpay mode guard
#
# The publishable key returned by create-order/ starts with `rzp_test_` in TEST
# mode and `rzp_live_` in LIVE mode. Any test that could move real money depends
# on `require_razorpay_test_mode`, which HARD-SKIPS unless the target is in test
# mode — so the charging suite physically cannot fire against live keys.
# ---------------------------------------------------------------------------

def _create_online_order_and_payment(sess, api):
    """Place a 1-item ONLINE order and open its Razorpay order.
    Returns (order_id, create_order_json) or (None, None) if unavailable."""
    p = first_in_stock_product(sess, api)
    sess.post(f"{api}/cart/add_item/", json={"product_id": p["id"], "quantity": 1})
    order = sess.post(f"{api}/orders/", json={
        "shipping_address": "1 E2E Test Rd, Test City",
        "phone_number": "9999999999",
        "payment_method": "ONLINE",
    })
    if order.status_code != 201:
        return None, None
    order_id = order.json()["order_id"]
    co = sess.post(f"{api}/payments/create-order/", json={"order_id": order_id})
    if co.status_code != 200:
        return order_id, None
    return order_id, co.json()


@pytest.fixture()
def require_razorpay_test_mode(account_session, api):
    """Skip unless the target's active Razorpay key is a TEST key.

    Yields the publishable key id. Refuses (skips, never fails) on live keys so
    the charging suite is safe to point at production only when it has been
    switched to test mode.
    """
    order_id, co = _create_online_order_and_payment(account_session, api)
    # Best-effort cleanup of the probe order so we don't leave a pending online
    # order lying around.
    if order_id is not None:
        account_session.post(f"{api}/orders/{order_id}/cancel/")
    if not co:
        pytest.skip("create-order unavailable — cannot determine Razorpay mode "
                    "(online payments may be disabled on this target)")
    key = co.get("razorpay_key_id", "")
    if not key.startswith("rzp_test_"):
        pytest.skip(
            f"Razorpay is NOT in test mode (key {key[:9]!r}). Charging tests "
            f"refuse to run against live keys — set RAZORPAY_TEST_MODE=True on "
            f"the target first."
        )
    return key
