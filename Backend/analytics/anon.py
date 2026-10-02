"""
Anonymous-traffic analytics: counter-based, identity-free, DB-bounded.

Anonymous (logged-out) visitors are NEVER stored as individual rows. Each
event only increments a pre-aggregated daily counter, so storage is bounded by
``days × metric × dimension-cardinality`` and is completely independent of
traffic volume. We also keep no session/identity, so we cannot (by design)
recognise a repeat visitor — that is the privacy posture we want, and it
conveniently sidesteps any dedupe/explosion problem.

Two execution modes, chosen at runtime:

* **Redis present (production):** increments are buffered in Redis (atomic
  INCR) on the hot request path and an index set tracks which counters changed.
  ``flush_anon_to_db`` drains them into ``DailyAnonStat`` periodically, so the
  write path never touches Postgres per-event.
* **Redis absent (tests / local dev):** increments are written straight to
  ``DailyAnonStat`` with an atomic ``F()`` UPSERT, and ``flush_anon_to_db`` is a
  no-op. The dimension-building and aggregation logic is identical in both
  modes, so it is fully exercised by the test suite without a live Redis.

See ANALYTICS.md for the counter-key schema.
"""
import logging
import re
from datetime import date as date_cls

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .geoip import client_ip, coarse_geo
from .models import DailyAnonStat

logger = logging.getLogger(__name__)

# Only these metrics may be recorded for anonymous traffic.
ALLOWED_METRICS = {m for m, _ in DailyAnonStat.METRIC_CHOICES}

# Redis key namespace (the cache KEY_PREFIX 'ngu' is applied by django-redis to
# cache.* calls, but here we use the raw connection, so we include it ourselves).
_KEY = 'ngu:anon:{date}:{metric}:{dim}'
_INDEX = 'ngu:anon:index:{date}'
_TTL = 60 * 60 * 24 * 3  # 3 days — safety net well past the flush cadence.

_BOT_RE = re.compile(r'bot|crawl|spider|slurp|bing|headless|monitor|curl|wget|python-requests', re.I)
_MOBILE_RE = re.compile(r'mobile|android|iphone|ipod', re.I)
_TABLET_RE = re.compile(r'ipad|tablet', re.I)


def _redis():
    """Return the raw Redis connection, or None if Redis isn't configured."""
    try:
        from django_redis import get_redis_connection
        return get_redis_connection('default')
    except Exception:
        return None


def _device(user_agent):
    ua = user_agent or ''
    if _BOT_RE.search(ua):
        return 'bot'
    if _TABLET_RE.search(ua):
        return 'tablet'
    if _MOBILE_RE.search(ua):
        return 'mobile'
    return 'desktop'


def _source(referer, host):
    """Bucket the referrer into a coarse traffic-source label."""
    if not referer:
        return 'direct'
    ref = referer.lower()
    if host and host.lower() in ref:
        return None  # internal navigation — not a traffic source
    if any(s in ref for s in ('google.', 'bing.', 'duckduckgo.', 'yahoo.')):
        return 'google' if 'google.' in ref else 'search'
    if any(s in ref for s in ('facebook.', 'instagram.', 'twitter.', 't.co', 'youtube.', 'whatsapp')):
        return 'social'
    return 'referral'


def _dimensions(request):
    """
    Build the coarse, non-identifying dimension keys for a request:
    device, geo (state/city), and traffic source. Always includes the '' total.
    """
    dims = ['']  # day/metric grand total
    device = _device(request.META.get('HTTP_USER_AGENT', ''))
    dims.append(f'device:{device}')

    geo = coarse_geo(client_ip(request))
    if geo:
        if geo.get('state'):
            dims.append(f"state:{geo['state']}")
        if geo.get('city'):
            dims.append(f"city:{geo['city']}")

    source = _source(request.META.get('HTTP_REFERER', ''),
                     request.get_host() if hasattr(request, 'get_host') else '')
    if source:
        dims.append(f'source:{source}')
    return device, dims


def _today():
    return timezone.localdate()


def record_anon(metric, request, *, product_id=None, query=None, zero=False):
    """
    Record one anonymous event by incrementing daily counters. Best-effort:
    never raises into the request path. ``product_id`` is currently unused at
    the dimension level (we keep anon data product-agnostic to stay broad, not
    customer/-item-specific) but accepted for forward compatibility. ``zero``
    marks a search that returned no results.
    """
    try:
        if metric not in ALLOWED_METRICS:
            return
        day = _today()
        device, dims = _dimensions(request)

        # A search with no results also bumps the zero-result metric.
        metrics = [metric]
        if metric == 'search' and zero:
            metrics.append('search_zero_result')

        increments = [(m, dim) for m in metrics for dim in dims]

        conn = _redis()
        if conn is not None:
            _incr_redis(conn, day, increments)
        else:
            _upsert_counts(day, {(m, dim): 1 for (m, dim) in increments})
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"record_anon failed ({metric}): {exc}")


def _incr_redis(conn, day, increments):
    iso = day.isoformat()
    index = _INDEX.format(date=iso)
    pipe = conn.pipeline()
    for metric, dim in increments:
        key = _KEY.format(date=iso, metric=metric, dim=dim or '_')
        pipe.incr(key)
        pipe.expire(key, _TTL)
        pipe.sadd(index, f'{metric}|{dim}')
    pipe.expire(index, _TTL)
    pipe.execute()


@transaction.atomic
def _upsert_counts(day, counts):
    """Atomically add ``counts[(metric, dim)]`` into DailyAnonStat for ``day``."""
    for (metric, dim), n in counts.items():
        if n <= 0:
            continue
        obj, created = DailyAnonStat.objects.get_or_create(
            date=day, metric=metric, dimension_key=dim,
            defaults={'count': n},
        )
        if not created:
            DailyAnonStat.objects.filter(pk=obj.pk).update(count=F('count') + n)


def flush_anon_to_db(day=None):
    """
    Drain the Redis counters for ``day`` (default: today) into DailyAnonStat.
    Idempotent: counters are consumed (GETDEL) as they are flushed, so a
    re-run will not double-count. No-op when Redis is unavailable (the
    increments already went straight to the DB).

    Returns the number of (metric, dimension) counters flushed.
    """
    conn = _redis()
    if conn is None:
        return 0
    if day is None:
        day = _today()
    if isinstance(day, str):
        day = date_cls.fromisoformat(day)
    iso = day.isoformat()
    index = _INDEX.format(date=iso)

    members = conn.smembers(index)
    if not members:
        return 0

    counts = {}
    pipe = conn.pipeline()
    parsed = []
    for raw in members:
        member = raw.decode() if isinstance(raw, bytes) else raw
        metric, _, dim = member.partition('|')
        key = _KEY.format(date=iso, metric=metric, dim=dim or '_')
        # GETDEL (Redis 6.2+); fall back to GET+DEL via pipeline for older.
        pipe.getset(key, 0)
        parsed.append((metric, dim, key))
    values = pipe.execute()

    delete_keys = []
    for (metric, dim, key), val in zip(parsed, values):
        try:
            n = int(val or 0)
        except (TypeError, ValueError):
            n = 0
        if n:
            counts[(metric, dim)] = counts.get((metric, dim), 0) + n
        delete_keys.append(key)

    if counts:
        _upsert_counts(day, counts)

    # Clean up the drained counters and the index.
    cleanup = conn.pipeline()
    for key in delete_keys:
        cleanup.delete(key)
    cleanup.delete(index)
    cleanup.execute()

    return len(counts)
