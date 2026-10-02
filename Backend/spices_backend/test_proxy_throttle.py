"""Regression tests for the X-Forwarded-For throttle-bypass fix.

Background: DRF derives a request's throttle identity from X-Forwarded-For. With
NUM_PROXIES unset it concatenated the WHOLE header, and because our nginx layers
APPEND to XFF, a client could prepend a rotating fake value and mint a brand-new
throttle bucket per request — bypassing the login / OTP / order rate limits.

The fix sets REST_FRAMEWORK['NUM_PROXIES'] = 2 (host nginx + frontend-container
nginx), so both DRF and spices_backend.abuse.get_client_ip read the real client
as the 2nd-from-last XFF entry — an entry the client cannot forge. These tests
lock that behaviour in.
"""
import pytest
from django.core.cache import cache
from django.test import RequestFactory
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle

from spices_backend.abuse import get_client_ip

# A production-shaped XFF: [client-supplied spoof, real client, docker gateway].
# With 2 trusted proxies the middle value is the true client.
REAL_CLIENT = "203.0.113.7"
GATEWAY = "172.18.0.1"


def _req(xff=None, remote_addr=GATEWAY):
    extra = {"REMOTE_ADDR": remote_addr}
    if xff is not None:
        extra["HTTP_X_FORWARDED_FOR"] = xff
    return RequestFactory().get("/", **extra)


def test_get_client_ip_ignores_spoofed_prefix():
    req = _req(f"9.9.9.9, {REAL_CLIENT}, {GATEWAY}")
    assert get_client_ip(req) == REAL_CLIENT


def test_get_client_ip_stable_across_rotating_spoof():
    """The whole point: changing the attacker-controlled prefix must NOT change
    the derived identity — otherwise the throttle bucket rotates and limits leak."""
    a = get_client_ip(_req(f"1.1.1.1, {REAL_CLIENT}, {GATEWAY}"))
    b = get_client_ip(_req(f"2.2.2.2, {REAL_CLIENT}, {GATEWAY}"))
    assert a == b == REAL_CLIENT


def test_get_client_ip_falls_back_to_remote_addr_without_xff():
    assert get_client_ip(_req(xff=None, remote_addr="198.51.100.1")) == "198.51.100.1"


def test_drf_throttle_ident_matches_trusted_hop():
    """DRF's throttle identity must resolve to the same un-spoofable client IP."""
    req = _req(f"9.9.9.9, {REAL_CLIENT}, {GATEWAY}")
    assert AnonRateThrottle().get_ident(req) == REAL_CLIENT


@pytest.mark.django_db
def test_login_throttle_not_bypassable_via_rotating_xff():
    """End-to-end: hammer the login endpoint while rotating the spoofed XFF
    prefix but keeping the real proxy hops fixed. Because the throttle now keys on
    the fixed real client, the 5/min login limit still trips (429)."""
    cache.clear()
    client = APIClient()
    url = "/api/auth/login/"
    data = {"email": "nobody@example.com", "password": "wrong-on-purpose"}
    tail = f"{REAL_CLIENT}, {GATEWAY}"

    statuses = []
    for i in range(7):
        # A different spoofed first hop every request — the pre-fix bypass.
        resp = client.post(
            url, data, format="json",
            HTTP_X_FORWARDED_FOR=f"{i}.{i}.{i}.{i}, {tail}",
        )
        statuses.append(resp.status_code)

    assert 429 in statuses, (
        f"login throttle bypassed via rotating X-Forwarded-For; statuses={statuses}"
    )
    cache.clear()
