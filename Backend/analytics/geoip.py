"""
Coarse IP -> region resolution for anonymous-traffic analytics.

Uses a local MaxMind GeoLite2-City database (no per-request external call, so
it scales flat). Everything here is best-effort and fails silent: if the
``geoip2`` package isn't installed, the ``.mmdb`` file is missing, or the IP is
private/unresolvable, we simply return ``None`` and the caller records the event
without a geo dimension. We deliberately resolve only to city/state level —
never anything that could identify an individual.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_reader = None
_load_attempted = False


def _get_reader():
    """Lazily memory-map the GeoLite2 database once. Returns None on any failure."""
    global _reader, _load_attempted
    if _load_attempted:
        return _reader
    _load_attempted = True
    try:
        from django.contrib.gis.geoip2 import GeoIP2
        path = getattr(settings, 'GEOIP_PATH', None)
        _reader = GeoIP2(path) if path else GeoIP2()
    except Exception as exc:  # ImportError, missing db, bad path...
        logger.info(f"GeoIP2 unavailable; anonymous geo disabled: {exc}")
        _reader = None
    return _reader


def client_ip(request):
    """
    Best-effort client IP. Trusts the left-most X-Forwarded-For hop (we sit
    behind nginx / Cloudflare in production) and falls back to REMOTE_ADDR.
    """
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or ''


def coarse_geo(ip):
    """
    Resolve an IP to ``{'city': str, 'state': str}`` (either may be '') or
    ``None``. Never raises.
    """
    if not ip:
        return None
    reader = _get_reader()
    if reader is None:
        return None
    try:
        data = reader.city(ip)
    except Exception:
        # Private IPs, lookup misses, malformed addresses all land here.
        return None
    return {
        'city': data.get('city') or '',
        'state': data.get('region_name') or data.get('region') or '',
    }
