"""
Admin-only Insights API.

Each endpoint reads the pre-computed rollups (kept current by the
``rollup_analytics`` command), accepts ``?from=&to=&granularity=`` and is
Redis-cached for a few minutes. Admin-only — these expose aggregate business
data.
"""
from datetime import date as date_cls

from django.conf import settings
from django.core.cache import cache
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from products.cache import make_cache_key
from . import insights

VALID_GRANULARITIES = {'day', 'week', 'month'}


def _parse_params(request):
    """Return (date_from, date_to, granularity), falling back to sane defaults."""
    default_from, default_to = insights.default_range()
    try:
        date_from = date_cls.fromisoformat(request.query_params['from'])
    except (KeyError, ValueError):
        date_from = default_from
    try:
        date_to = date_cls.fromisoformat(request.query_params['to'])
    except (KeyError, ValueError):
        date_to = default_to
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    granularity = request.query_params.get('granularity', 'day')
    if granularity not in VALID_GRANULARITIES:
        granularity = 'day'
    return date_from, date_to, granularity


def _cached(name, request, fn, *, use_granularity=True):
    date_from, date_to, granularity = _parse_params(request)
    gran = granularity if use_granularity else '-'
    key = make_cache_key('insights', name, date_from.isoformat(), date_to.isoformat(), gran)
    data = cache.get(key)
    if data is None:
        data = fn(date_from, date_to, granularity) if use_granularity else fn(date_from, date_to)
        cache.set(key, data, getattr(settings, 'CACHE_TTL_INSIGHTS', 300))
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def overview(request):
    return _cached('overview', request, insights.overview)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def sales(request):
    return _cached('sales', request, insights.sales)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def funnel(request):
    return _cached('funnel', request, insights.funnel, use_granularity=False)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def search_insights(request):
    return _cached('search', request, insights.search, use_granularity=False)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def customers(request):
    return _cached('customers', request, insights.customers)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def anonymous(request):
    return _cached('anonymous', request, insights.anonymous, use_granularity=False)
