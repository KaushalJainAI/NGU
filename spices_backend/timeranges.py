"""Local-calendar-date → datetime range helpers.

Reporting code thinks in inclusive local calendar dates ("orders from
2026-07-01 to 2026-07-31"), but the columns it filters are ``DateTimeField``s
stored in UTC. The obvious translation is Django's ``__date`` lookup, which is
a trap: with ``USE_TZ`` on, Postgres renders it as

    (orders_order.created_at AT TIME ZONE 'Asia/Kolkata')::date >= '2026-07-01'

— an *expression* over the column, so the btree indexes on ``created_at`` are
unusable and every dated report degrades to a sequential scan over the whole
table.

Converting the span to a half-open aware datetime range instead keeps the
predicate on the bare column, which the existing indexes serve directly:

    created_at >= '2026-07-01 00:00+05:30' AND created_at < '2026-08-01 00:00+05:30'

Half-open (``__lt`` on the exclusive end) rather than ``__lte`` on 23:59:59, so
no row can fall through the crack in the last second of the day.
"""
from datetime import datetime, time, timedelta

from django.utils import timezone


def day_start(day):
    """Aware datetime at midnight local time on the given date."""
    return timezone.make_aware(
        datetime.combine(day, time.min), timezone.get_current_timezone()
    )


def day_range(day):
    """Half-open ``[start, end)`` covering one local calendar day."""
    return day_start(day), day_start(day + timedelta(days=1))


def date_range(date_from=None, date_to=None):
    """Half-open ``[start, end)`` for an *inclusive* local date span.

    Either bound may be ``None`` for an open-ended range; the corresponding
    element of the returned tuple is then ``None``.
    """
    start = day_start(date_from) if date_from else None
    end = day_start(date_to + timedelta(days=1)) if date_to else None
    return start, end


def range_filter(field, date_from=None, date_to=None):
    """Filter kwargs for `field` over an inclusive local date span.

    Drop-in replacement for ``{field}__date__gte`` / ``{field}__date__lte``::

        qs.filter(**range_filter('created_at', date_from, date_to))
        qs.filter(**range_filter('order__created_at', date_from, date_to))

    Returns an empty dict when both bounds are ``None``, so it is safe to
    splat unconditionally.
    """
    start, end = date_range(date_from, date_to)
    lookups = {}
    if start is not None:
        lookups[f'{field}__gte'] = start
    if end is not None:
        lookups[f'{field}__lt'] = end
    return lookups
