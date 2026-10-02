# Location Detection & Coarse Geo

Automatic location detection lets a shopper fill their shipping address from the
browser's geolocation instead of typing it, and captures a **coarse** copy of
that location to (later) improve personalized recommendations. It is strictly
opt-in: the browser permission prompt only appears when the user clicks
"Use my location".

## Flow

```
User clicks "Use my location"  (Billing or Profile page)
      │
      │  navigator.geolocation.getCurrentPosition()  ← browser permission prompt
      ▼
{ lat, lng, accuracy }   (precise, in-memory only)
      │
      │  GET /api/geocode/reverse/?lat=&lng=         ← server proxy → Nominatim
      ▼
{ address_line, city, state, pincode, country }
      │
      ├── prefill the address form fields (user reviews/edits)
      │
      └── PUT /api/geo/  { lat, lng, city, state, pincode }
              │   coords rounded to 3 decimals server-side
              ▼
          analytics.UserGeo  (one coarse row per user)
```

The precise GPS coordinates never leave the request that resolves them — the
only thing persisted is the coarse `UserGeo` row.

## Backend

### Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/geocode/reverse/?lat=&lng=` | GET | required | Reverse-geocode coordinates → address (Nominatim proxy) |
| `/api/geo/` | GET | required | Read the current user's stored coarse location (`204` if none) |
| `/api/geo/` | PUT | required | Upsert the user's coarse location |

### Reverse-geocode proxy

`analytics.views.reverse_geocode` calls the OpenStreetMap **Nominatim** service
server-side rather than from the browser, for three reasons:

1. Nominatim's usage policy requires an identifying `User-Agent` header.
2. It asks callers to stay at ≤ 1 request/second — we honor this by caching each
   result in Redis for 30 days, keyed on coordinates rounded to 3 decimals, so
   nearby lookups collapse onto a single upstream hit.
3. It keeps the provider swappable (e.g. to a paid India-accurate geocoder)
   without touching the frontend.

Throttled via the `geocode` scope (`60/hour`, see `DEFAULT_THROTTLE_RATES`).

### `UserGeo` model

One row per user (`OneToOneField`), holding only coarse fields:

| Field | Notes |
|-------|-------|
| `city`, `state` | From reverse geocode |
| `pincode_prefix` | First 3 PIN digits only — region, not locality |
| `lat_coarse`, `lng_coarse` | Rounded to 3 decimals (~110 m) at the serializer boundary |
| `updated_at` | Last refresh |

`UserGeoSerializer` accepts precise `lat`/`lng`/`pincode` as **write-only**
inputs and rounds/truncates them in `validate()` before they are stored, so
precise data cannot be persisted even if the client sends it.

## Frontend

| Piece | Location |
|-------|----------|
| `useGeolocation()` hook | `src/hooks/useGeolocation.ts` — wraps `navigator.geolocation`, exposes `request()` + `status` |
| `geoAPI` | `src/lib/api/geo.ts` — `reverseGeocode()`, `get()`, `update()` |
| Checkout button | `src/pages/Billing.tsx` — "Use my location"; emphasized when the profile has no saved default address |
| Profile button | `src/pages/Profile.tsx` — fills address fields; user presses Save to make it the default |

On Billing the button is highlighted (`default` variant) when the user has **no
saved default address**, which is the case this feature primarily targets. The
detected address always lands in editable fields — it is a starting point, never
a silent override.

## Privacy properties

- **Consent-gated:** location is requested only on an explicit click; nothing is
  prompted or collected on page load.
- **Coarse persistence:** precise coordinates are used transiently to resolve an
  address and are never written to the database; only city/state/pincode-prefix
  and 3-decimal-rounded coordinates are stored.
- **Best-effort:** the `geoAPI.update()` call is fire-and-forget — failing to
  record the recommendation signal never blocks checkout or profile updates.

## Recommendations (capture now, rank later)

`UserGeo` is currently **captured but not yet used for ranking**. The
recommendation engine reserves a `W_GEO` weight slot (`products/personalization.py`,
alongside `W_CF`) set to `0.0`. Once enough regional data accumulates, a
region-filtered popularity term (scoping the `OrderItem` aggregation to the
user's state) can be blended in by implementing it next to `_popularity()` and
bumping `W_GEO`. Spices are strongly regional, so this is expected to be a
meaningful cold-start signal. See `docs/RECOMMENDATIONS.md`.
