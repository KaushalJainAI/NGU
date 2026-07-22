"""
Tests for ``analytics.geoip`` — coarse IP -> region resolution for anonymous
analytics.

``client_ip`` feeds the abuse/ban keying, so its X-Forwarded-For parsing is
security-relevant (spoofing / proxy-hop handling). ``coarse_geo`` is best-effort
and must never raise; the field-mapping branch is exercised with a fake reader
since the GeoLite2 DB isn't present in the test environment.
"""
import pytest

from analytics import geoip
from analytics.geoip import client_ip, coarse_geo


def _req(xff=None, remote=None):
    from django.test import RequestFactory
    rf = RequestFactory()
    extra = {}
    if xff is not None:
        extra['HTTP_X_FORWARDED_FOR'] = xff
    if remote is not None:
        extra['REMOTE_ADDR'] = remote
    return rf.get('/', **extra)


# --------------------------------------------------------------------------- #
# client_ip
# --------------------------------------------------------------------------- #

class TestClientIp:
    def test_uses_first_xff_hop(self):
        req = _req(xff='203.0.113.5, 10.0.0.1, 10.0.0.2', remote='10.0.0.1')
        assert client_ip(req) == '203.0.113.5'

    def test_strips_whitespace_around_first_hop(self):
        req = _req(xff='  203.0.113.5  , 10.0.0.1', remote='10.0.0.1')
        assert client_ip(req) == '203.0.113.5'

    def test_falls_back_to_remote_addr_without_xff(self):
        req = _req(remote='198.51.100.7')
        assert client_ip(req) == '198.51.100.7'

    def test_empty_xff_falls_back_to_remote_addr(self):
        req = _req(xff='', remote='198.51.100.7')
        assert client_ip(req) == '198.51.100.7'

    def test_single_hop_xff(self):
        req = _req(xff='203.0.113.5', remote='10.0.0.1')
        assert client_ip(req) == '203.0.113.5'

    def test_returns_empty_string_when_nothing_available(self):
        # RequestFactory always injects REMOTE_ADDR=127.0.0.1; blank it to
        # exercise the "no XFF, no REMOTE_ADDR" fallback to ''.
        req = _req(remote='')
        assert client_ip(req) == ''


# --------------------------------------------------------------------------- #
# coarse_geo
# --------------------------------------------------------------------------- #

class TestCoarseGeo:
    def test_none_ip_returns_none(self):
        assert coarse_geo(None) is None

    def test_empty_ip_returns_none(self):
        assert coarse_geo('') is None

    def test_returns_none_when_reader_unavailable(self, monkeypatch):
        monkeypatch.setattr(geoip, '_get_reader', lambda: None)
        assert coarse_geo('8.8.8.8') is None

    def test_maps_city_and_state(self, monkeypatch):
        class FakeReader:
            def city(self, ip):
                return {'city': 'Ahmedabad', 'region_name': 'Gujarat'}

        monkeypatch.setattr(geoip, '_get_reader', lambda: FakeReader())
        assert coarse_geo('8.8.8.8') == {'city': 'Ahmedabad', 'state': 'Gujarat'}

    def test_region_fallback_key(self, monkeypatch):
        """Some GeoIP payloads use 'region' instead of 'region_name'."""
        class FakeReader:
            def city(self, ip):
                return {'city': 'Pune', 'region': 'Maharashtra'}

        monkeypatch.setattr(geoip, '_get_reader', lambda: FakeReader())
        assert coarse_geo('8.8.8.8') == {'city': 'Pune', 'state': 'Maharashtra'}

    def test_missing_fields_become_empty_strings(self, monkeypatch):
        class FakeReader:
            def city(self, ip):
                return {}

        monkeypatch.setattr(geoip, '_get_reader', lambda: FakeReader())
        assert coarse_geo('8.8.8.8') == {'city': '', 'state': ''}

    def test_never_raises_on_lookup_error(self, monkeypatch):
        """Private IPs / lookup misses raise inside .city() and must be swallowed."""
        class FakeReader:
            def city(self, ip):
                raise ValueError("address not in database")

        monkeypatch.setattr(geoip, '_get_reader', lambda: FakeReader())
        assert coarse_geo('192.168.0.1') is None
