import logging

import requests
from django.conf import settings
from django.core.cache import cache
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from products.cache import make_cache_key
from .anon import record_anon
from .models import UserEvent, UserGeo
from .serializers import UserEventSerializer, UserGeoSerializer

logger = logging.getLogger(__name__)

# Hard cap on how many events one request may carry.
MAX_BATCH = settings.ANALYTICS_MAX_BATCH

# Nominatim (OpenStreetMap) reverse-geocode endpoint. Their usage policy
# requires an identifying User-Agent and <=1 req/sec; we satisfy the latter by
# caching results aggressively (coords rounded to 3 decimals -> shared key).
NOMINATIM_URL = settings.NOMINATIM_URL
NOMINATIM_USER_AGENT = settings.NOMINATIM_USER_AGENT
GEOCODE_TTL = getattr(settings, 'CACHE_TTL_GEOCODE', 60 * 60 * 24 * 30)  # 30 days


class EventIngestThrottle(UserRateThrottle):
    scope = 'events'


class GeocodeThrottle(UserRateThrottle):
    scope = 'geocode'


class AnonEventThrottle(AnonRateThrottle):
    """Per-IP throttle for the public anonymous-event endpoint (abuse guard)."""
    scope = 'anon_events'


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([EventIngestThrottle])
def ingest_events(request):
    """
    Record one or many behavioral events for the current user.

    Accepts either a single event object or a JSON array (batch). Individual
    invalid items are skipped rather than failing the whole batch, so a stale
    product id on the client never drops a user's other events.
    """
    payload = request.data
    items = payload if isinstance(payload, list) else [payload]
    items = items[:MAX_BATCH]

    events = []
    skipped = 0
    for raw in items:
        serializer = UserEventSerializer(data=raw)
        if serializer.is_valid():
            events.append(serializer.to_event(request.user))
        else:
            skipped += 1

    if events:
        UserEvent.objects.bulk_create(events)

    return Response({'recorded': len(events), 'skipped': skipped}, status=201)


@api_view(['POST'])
# No authentication: this endpoint is identity-free by design. Leaving the
# default CookieJWTAuthentication on would make it enforce CSRF whenever a
# (possibly stale) access_token cookie rides along, 403-ing the sendBeacon
# call — which cannot set an X-CSRFToken header. Disabling auth keeps the
# beacon truly anonymous and CSRF-free.
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AnonEventThrottle])
def ingest_anon(request):
    """
    Record one anonymous (logged-out) behavioral event as aggregate counters.

    Public + identity-free by design: no row is stored and no session is kept,
    so a repeat visitor cannot be recognised. The body carries only a coarse
    ``metric`` (+ optional ``query``/``zero`` for searches). Always returns 204
    so analytics can never disrupt a guest's browsing, even on bad input.
    """
    record_anon(
        request.data.get('metric'),
        request,
        product_id=request.data.get('product_id'),
        query=request.data.get('query'),
        zero=bool(request.data.get('zero')),
    )
    return Response(status=204)


def _parse_latlng(request):
    """Pull and bounds-check lat/lng query params. Returns (lat, lng) or None."""
    try:
        lat = float(request.query_params.get('lat'))
        lng = float(request.query_params.get('lng'))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def _map_nominatim(payload):
    """Reduce a Nominatim reverse response to the address fields we use."""
    addr = (payload or {}).get('address', {}) or {}
    city = (
        addr.get('city') or addr.get('town') or addr.get('village')
        or addr.get('suburb') or addr.get('county') or ''
    )
    return {
        'address_line': payload.get('display_name', '') if payload else '',
        'city': city,
        'state': addr.get('state', ''),
        'pincode': addr.get('postcode', ''),
        'country': addr.get('country', ''),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([GeocodeThrottle])
def reverse_geocode(request):
    """
    Reverse-geocode lat/lng -> address via Nominatim, proxied + cached.

    Proxied server-side so the outbound call carries the required User-Agent and
    so responses are cached (Nominatim asks callers to stay <=1 req/sec). The
    cache key rounds coordinates to 3 decimals, collapsing nearby requests onto
    one upstream hit.
    """
    coords = _parse_latlng(request)
    if coords is None:
        return Response({'error': 'Valid lat and lng query params are required.'}, status=400)
    lat, lng = coords

    cache_key = make_cache_key('geocode', 'rev', round(lat, 3), round(lng, 3))
    cached = cache.get(cache_key)
    if cached is not None:
        return Response(cached)

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={'lat': lat, 'lon': lng, 'format': 'jsonv2', 'addressdetails': 1},
            headers={'User-Agent': NOMINATIM_USER_AGENT},
            timeout=6,
        )
        resp.raise_for_status()
        data = _map_nominatim(resp.json())
    except requests.RequestException as exc:
        logger.warning(f"Reverse geocode failed for ({lat},{lng}): {exc}")
        return Response({'error': 'Geocoding service unavailable.'}, status=502)

    cache.set(cache_key, data, GEOCODE_TTL)
    return Response(data)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def user_geo(request):
    """
    Read or upsert the current user's coarse location.

    GET  -> the stored coarse location (or 204 if none).
    PUT  -> upsert; precise coordinates in the body are rounded before storage.
    """
    if request.method == 'GET':
        obj = UserGeo.objects.filter(user=request.user).first()
        if obj is None:
            return Response(status=204)
        return Response(UserGeoSerializer(obj).data)

    serializer = UserGeoSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    obj = serializer.upsert(request.user)
    return Response(UserGeoSerializer(obj).data, status=200)
