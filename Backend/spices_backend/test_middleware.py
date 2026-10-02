"""
Tests for the request middlewares in ``spices_backend.middleware``.

These run on *every* request but had no direct coverage:

  * ``AbuseGuardMiddleware`` — the 403 IP-ban gate. Deliberately fail-open, so a
    regression that flipped it closed (or stopped consulting ``is_blocked``)
    would lock out real shoppers while every other test still passed.
  * ``LanguageQueryMiddleware`` — activates the ``?lang=`` / ``X-Language``
    language and patches ``Vary: X-Language`` so the browser HTTP cache doesn't
    serve an English response to a Hindi request for the same URL.
"""
import pytest
from django.test import RequestFactory
from django.utils import translation
from rest_framework.test import APIClient

from spices_backend.abuse import block_ip, unblock_ip
from spices_backend.middleware import AbuseGuardMiddleware, LanguageQueryMiddleware

# A public, unauthenticated GET endpoint — the cheapest way to drive the whole
# middleware stack for real (WSGI -> AbuseGuard -> ... -> LanguageQuery -> view).
LIVE_URL = '/api/health/'


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _ok_response(request):
    """A trivial downstream handler that records it was reached."""
    from django.http import HttpResponse
    resp = HttpResponse("ok")
    resp._reached = True
    return resp


def _request(ip='1.2.3.4', lang=None, header_lang=None):
    rf = RequestFactory()
    path = '/api/products/'
    if lang is not None:
        path += f'?lang={lang}'
    extra = {'REMOTE_ADDR': ip}
    if header_lang is not None:
        extra['HTTP_X_LANGUAGE'] = header_lang
    return rf.get(path, **extra)


# --------------------------------------------------------------------------- #
# AbuseGuardMiddleware
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestAbuseGuardMiddleware:
    def test_banned_ip_gets_403_before_downstream(self):
        """A blocked IP is short-circuited with 403; the view never runs."""
        block_ip('9.9.9.9')
        mw = AbuseGuardMiddleware(_ok_response)
        resp = mw(_request(ip='9.9.9.9'))
        assert resp.status_code == 403
        assert not getattr(resp, '_reached', False)

    def test_unbanned_ip_passes_through(self):
        unblock_ip('1.2.3.4')  # ensure clean
        mw = AbuseGuardMiddleware(_ok_response)
        resp = mw(_request(ip='1.2.3.4'))
        assert resp.status_code == 200
        assert resp._reached is True

    def test_unbanned_after_lift(self):
        block_ip('5.5.5.5')
        unblock_ip('5.5.5.5')
        mw = AbuseGuardMiddleware(_ok_response)
        resp = mw(_request(ip='5.5.5.5'))
        assert resp.status_code == 200

    def test_fail_open_when_block_check_raises(self, monkeypatch):
        """If the ban check blows up (e.g. cache down), the request must still
        be served — never lock out legit traffic on a cache hiccup."""
        import spices_backend.middleware as mw_mod

        def boom(_ip):
            raise RuntimeError("cache down")

        monkeypatch.setattr(mw_mod, 'is_blocked', boom)
        mw = AbuseGuardMiddleware(_ok_response)
        resp = mw(_request(ip='9.9.9.9'))
        assert resp.status_code == 200
        assert resp._reached is True

    def test_banned_ip_via_x_forwarded_for_first_hop(self):
        """Behind nginx the real client is the first XFF hop; the ban must key
        off that, not REMOTE_ADDR (the proxy)."""
        block_ip('7.7.7.7')
        rf = RequestFactory()
        req = rf.get('/api/products/', HTTP_X_FORWARDED_FOR='7.7.7.7, 10.0.0.1',
                     REMOTE_ADDR='10.0.0.1')
        mw = AbuseGuardMiddleware(_ok_response)
        resp = mw(req)
        assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# LanguageQueryMiddleware
# --------------------------------------------------------------------------- #

class TestLanguageQueryMiddleware:
    def _capture_active_language(self):
        """Returns (middleware, box) where box['lang'] holds the language that
        was active *inside* the downstream handler."""
        box = {}

        def capture(request):
            from django.http import HttpResponse
            box['lang'] = translation.get_language()
            box['request_lang'] = getattr(request, 'LANGUAGE_CODE', None)
            return HttpResponse("ok")

        return LanguageQueryMiddleware(capture), box

    def test_valid_lang_query_param_activated(self):
        mw, box = self._capture_active_language()
        mw(_request(lang='hi'))
        assert box['lang'] == 'hi'
        assert box['request_lang'] == 'hi'

    def test_valid_lang_via_header(self):
        mw, box = self._capture_active_language()
        mw(_request(header_lang='gu'))
        assert box['lang'] == 'gu'

    def test_query_param_wins_over_header(self):
        mw, box = self._capture_active_language()
        rf = RequestFactory()
        req = rf.get('/api/products/?lang=mr', HTTP_X_LANGUAGE='gu')
        mw(req)
        assert box['lang'] == 'mr'

    def test_unknown_lang_leaves_default_active(self):
        mw, box = self._capture_active_language()
        translation.activate('en')
        mw(_request(lang='klingon'))
        # Not one of settings.LANGUAGES -> default stays active, not 'klingon'.
        assert box['request_lang'] is None
        assert box['lang'] == 'en'

    def test_blank_lang_leaves_default_active(self):
        mw, box = self._capture_active_language()
        mw(_request(lang=''))
        assert box['request_lang'] is None

    def test_case_insensitive(self):
        mw, box = self._capture_active_language()
        mw(_request(lang='HI'))
        assert box['lang'] == 'hi'

    def test_vary_header_patched(self):
        """Every response gets Vary: X-Language so caches key on it."""
        mw, _ = self._capture_active_language()
        resp = mw(_request(lang='hi'))
        assert 'X-Language' in resp.get('Vary', '')

    def test_vary_header_patched_even_without_lang(self):
        mw, _ = self._capture_active_language()
        resp = mw(_request())
        assert 'X-Language' in resp.get('Vary', '')

    def test_language_deactivated_after_request(self):
        """The activated language must not leak into the next request."""
        translation.activate('en')
        mw, _ = self._capture_active_language()
        mw(_request(lang='hi'))
        # activate() inside the mw is undone in its finally -> back to default.
        assert translation.get_language() == 'en'


# --------------------------------------------------------------------------- #
# End-to-end: both middlewares driven through the real request stack against a
# live endpoint, exercising the GOOD (request allowed) and BAD (request blocked
# / input rejected) paths as they actually behave in production.
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestMiddlewareEndToEnd:
    def test_good_request_reaches_endpoint(self):
        """A request from a clean IP is served normally (200)."""
        client = APIClient()
        resp = client.get(LIVE_URL, REMOTE_ADDR='203.0.113.10')
        assert resp.status_code == 200
        assert resp.json()['status'] == 'healthy'

    def test_bad_request_from_banned_ip_is_403(self):
        """A banned IP is rejected by the guard before reaching the view."""
        block_ip('203.0.113.99')
        client = APIClient()
        resp = client.get(LIVE_URL, REMOTE_ADDR='203.0.113.99')
        assert resp.status_code == 403
        assert resp.json()['error'] == 'Access denied.'

    def test_banned_then_unbanned_recovers(self):
        block_ip('203.0.113.50')
        client = APIClient()
        assert client.get(LIVE_URL, REMOTE_ADDR='203.0.113.50').status_code == 403
        unblock_ip('203.0.113.50')
        assert client.get(LIVE_URL, REMOTE_ADDR='203.0.113.50').status_code == 200

    def test_ban_keys_off_forwarded_client_not_proxy(self):
        """Behind a proxy, only the real client IP (first XFF hop) is banned;
        another client sharing the proxy still gets through."""
        block_ip('203.0.113.7')
        client = APIClient()
        banned = client.get(
            LIVE_URL, HTTP_X_FORWARDED_FOR='203.0.113.7, 10.0.0.1',
            REMOTE_ADDR='10.0.0.1')
        assert banned.status_code == 403
        other = client.get(
            LIVE_URL, HTTP_X_FORWARDED_FOR='203.0.113.8, 10.0.0.1',
            REMOTE_ADDR='10.0.0.1')
        assert other.status_code == 200

    def test_good_language_request_sets_vary(self):
        """A valid ?lang= request succeeds and the response varies on X-Language."""
        client = APIClient()
        resp = client.get(LIVE_URL + '?lang=hi', REMOTE_ADDR='203.0.113.11')
        assert resp.status_code == 200
        assert 'X-Language' in resp.get('Vary', '')

    def test_bad_language_is_ignored_not_rejected(self):
        """An unknown language is silently ignored — the request still succeeds
        (with English fallback), never a 4xx."""
        client = APIClient()
        resp = client.get(LIVE_URL + '?lang=klingon', REMOTE_ADDR='203.0.113.12')
        assert resp.status_code == 200
        assert 'X-Language' in resp.get('Vary', '')
