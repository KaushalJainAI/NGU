"""
Abuse identification, tracking and (manual) banning — an independent layer.

Business code calls `flag_suspicious(request, reason, **meta)` at the points
where it rejects an extreme/abusive request (out-of-bound value, throttle hit).
That:
  * writes a structured WARNING log (ip / user / path / reason) you can grep or
    ship to monitoring, and
  * increments a rolling per-IP "strike" counter in the cache (Redis in prod),
    logging loudly once the count crosses ABUSE_STRIKE_ALERT.

Banning is a deliberate operator action (`block_ip`, exposed via the `ban_ip`
management command). The `AbuseGuardMiddleware` then 403s blocked clients. The
whole module is fail-open: if the cache is unavailable it never blocks legit
traffic, and removing it leaves the app fully functional.
"""
import logging

from django.conf import settings
from django.core.cache import cache

from .limits import ABUSE_STRIKE_WINDOW, ABUSE_STRIKE_ALERT

logger = logging.getLogger("ngu.abuse")

_STRIKE_KEY = "abuse:strikes:{ip}"
_BLOCK_KEY = "abuse:blocked:{ip}"


def _num_proxies() -> int:
    """How many trusted reverse proxies sit in front of Django. Mirrors DRF's
    REST_FRAMEWORK['NUM_PROXIES'] so this module and the throttles agree on which
    X-Forwarded-For entry is the real client. Defaults to 2 (host nginx +
    frontend-container nginx)."""
    try:
        n = (settings.REST_FRAMEWORK or {}).get("NUM_PROXIES")
        return int(n) if n is not None else 2
    except Exception:
        return 2


def get_client_ip(request) -> str:
    """Best-effort client IP, honouring the trusted proxy chain.

    Behind our nginx layers the socket peer (REMOTE_ADDR) is always a proxy and
    the real client is the Nth-from-last entry of X-Forwarded-For, where N is the
    number of trusted proxies. Counting from the RIGHT is what makes this
    un-spoofable: a client can prepend fake values to XFF, but it can never touch
    the entries our own proxies append. (This must match DRF's throttle identity
    logic — see settings.REST_FRAMEWORK['NUM_PROXIES'] — so a banned/abusive IP is
    tracked by the same address the throttles rate-limit.)"""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    num_proxies = _num_proxies()
    if xff and num_proxies > 0:
        addrs = [a.strip() for a in xff.split(",") if a.strip()]
        if addrs:
            return addrs[-min(num_proxies, len(addrs))]
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _bump_strikes(ip: str) -> int:
    key = _STRIKE_KEY.format(ip=ip)
    try:
        count = cache.get(key, 0) + 1
        cache.set(key, count, timeout=ABUSE_STRIKE_WINDOW)
        return count
    except Exception:  # cache down -> never break the request path
        return 0


def flag_suspicious(request, reason: str, **meta) -> None:
    """Record one abusive/out-of-bound request. Never raises."""
    try:
        ip = get_client_ip(request)
        user = getattr(request, "user", None)
        user_id = user.id if getattr(user, "is_authenticated", False) else None
        strikes = _bump_strikes(ip)
        payload = {
            "ip": ip,
            "user_id": user_id,
            "path": request.path,
            "method": request.method,
            "reason": reason,
            "strikes": strikes,
            **meta,
        }
        if strikes and strikes >= ABUSE_STRIKE_ALERT:
            logger.error("ABUSE ALERT (consider banning %s): %s", ip, payload)
        else:
            logger.warning("suspicious request: %s", payload)
    except Exception:  # telemetry must never break the response
        logger.exception("flag_suspicious failed")


def is_blocked(ip: str) -> bool:
    try:
        return cache.get(_BLOCK_KEY.format(ip=ip)) is not None
    except Exception:
        return False  # fail-open


def block_ip(ip: str, ttl: int | None = None) -> None:
    """Ban an IP (manual operator action). ttl=None means until unbanned."""
    cache.set(_BLOCK_KEY.format(ip=ip), True, timeout=ttl)
    logger.error("BANNED ip=%s ttl=%s", ip, ttl)


def unblock_ip(ip: str) -> None:
    cache.delete(_BLOCK_KEY.format(ip=ip))
    logger.warning("UNBANNED ip=%s", ip)
