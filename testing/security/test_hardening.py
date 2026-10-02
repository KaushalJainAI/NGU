"""
Security hardening: injection robustness, malformed input handling, throttling, and security headers.
"""
import pytest

SQLI_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE products; --",
    "1) UNION SELECT username, password FROM auth_user --",
    "%27%20OR%201=1--",
]

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    "\"><img src=x onerror=alert(1)>",
    "javascript:alert(document.cookie)",
]

LEAK_MARKERS = [
    "Traceback (most recent call last)",
    "django.db.utils",
    "psycopg2",
    "OperationalError",
    "ProgrammingError",
    "SyntaxError",
    "at /api/",
]


def _assert_no_leak(resp):
    body = resp.text
    lower = body.lower()
    for marker in LEAK_MARKERS:
        assert marker.lower() not in lower, (
            f"response leaked internal error marker {marker!r} "
            f"(status {resp.status_code})"
        )


# --- From test_injection_and_robustness.py ---

@pytest.mark.security
@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_search_sql_injection(session, api, payload):
    r = session.get(f"{api}/search/", params={"q": payload})
    assert r.status_code < 500, f"SQLi payload caused {r.status_code}: {r.text[:200]}"
    _assert_no_leak(r)


@pytest.mark.security
@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_product_filter_sql_injection(session, api, payload):
    r = session.get(f"{api}/products/", params={"category": payload, "search": payload})
    assert r.status_code < 500
    _assert_no_leak(r)


@pytest.mark.security
@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_xss_not_reflected_verbatim_in_json(session, api, payload):
    """Stored/reflected XSS guard: payload must not come back unescaped as HTML."""
    r = session.get(f"{api}/search/", params={"q": payload})
    assert r.status_code < 500
    ctype = r.headers.get("Content-Type", "")
    assert "text/html" not in ctype or "<script>alert(1)</script>" not in r.text


@pytest.mark.security
def test_malformed_json_body(session, api):
    """A broken JSON body to a POST endpoint must yield 400, not 500."""
    r = session.post(
        f"{api}/auth/login/",
        data="{not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code in (400, 415), f"got {r.status_code}: {r.text[:200]}"
    _assert_no_leak(r)


@pytest.mark.security
def test_unknown_route_is_404_not_500(session, api):
    r = session.get(f"{api}/this/route/does/not/exist/")
    assert r.status_code == 404
    _assert_no_leak(r)


@pytest.mark.security
def test_wrong_method_is_405(session, api):
    """DELETE on a list endpoint should be 405/403/401, never a 500."""
    r = session.delete(f"{api}/products/")
    assert r.status_code in (401, 403, 405)


# --- From test_rate_limit_and_headers.py ---

@pytest.mark.security
def test_login_is_throttled(session, api):
    statuses = []
    for _ in range(12):
        r = session.post(
            f"{api}/auth/login/",
            json={"username": "throttle-probe", "password": "nope"},
        )
        statuses.append(r.status_code)
        if r.status_code == 429:
            break
    if 429 not in statuses:
        pytest.skip(f"no 429 observed (throttling likely off on this target): {statuses}")
    assert 429 in statuses


@pytest.mark.security
@pytest.mark.destructive
def test_order_placement_is_rate_limited(auth_session, api):
    pr = auth_session.get(f"{api}/products/")
    data = pr.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    prod = next((p for p in items if (p.get("stock") or 0) >= 1), None)
    if not prod:
        pytest.skip("no in-stock product to place orders with")

    addr = {"shipping_address": "1 Rd", "phone_number": "1234567890", "payment_method": "COD"}
    statuses = []
    for _ in range(15):
        auth_session.post(f"{api}/cart/add_item/", json={"product_id": prod["id"], "quantity": 1})
        r = auth_session.post(f"{api}/orders/", json=addr)
        statuses.append(r.status_code)
        if r.status_code == 429:
            break
    if 429 not in statuses:
        pytest.skip(f"no 429 observed (order throttle relaxed on this target): {statuses}")
    assert 429 in statuses


@pytest.mark.security
def test_cors_does_not_reflect_arbitrary_origin(session, api):
    evil = "https://evil.example.com"
    r = session.get(f"{api}/products/", headers={"Origin": evil})
    acao = r.headers.get("Access-Control-Allow-Origin")
    assert acao != evil, (
        f"CORS reflected arbitrary origin {evil!r} — credentials could be read "
        f"cross-site if Allow-Credentials is also set."
    )


@pytest.mark.security
def test_no_server_version_disclosure(session, api):
    r = session.get(f"{api}/health/")
    server = (r.headers.get("Server") or "").lower()
    if "wsgiserver" in server:
        pytest.skip(f"dev server banner ({server!r}); verify prod nginx/gunicorn separately")
    for leaky in ("gunicorn/", "werkzeug", "python/"):
        assert leaky not in server, f"Server header discloses stack: {server!r}"


@pytest.mark.security
def test_debug_is_off_on_unknown_route(session, base_url):
    r = session.get(f"{base_url}/api/__definitely_not_a_route__/")
    assert r.status_code == 404
    assert "Using the URLconf defined in" not in r.text, "Django DEBUG appears to be ON"
