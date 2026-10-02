# Personalized Recommendations

The recommendations system surfaces in-stock products ranked by behavioral signals
collected from each logged-in user. It lives in `products/personalization.py` and is
exposed at `GET /api/recommendations/`.

## Architecture

```
User action on storefront
      │
      │  POST /api/events/  { event_type, product_id?, combo_id?, category_id? }
      ▼
analytics.UserEvent (DB row)
      │
      │  GET /api/recommendations/
      ▼
RecommendationEngine(user).recommend()
      │
      ├── _category_affinity()     ← orders + favorites + cart + recent views
      ├── _copurchase_counts()     ← item-item co-occurrence across all orders
      ├── _recent_viewed_ids()     ← UserEvent views/clicks (last 30 days)
      └── _popularity()           ← global order counts (shared cache)
      │
      └── weighted sum → sort → top-N → cache (TTL_SHORT) → serialize
```

## Signals and Weights

The final score for each candidate product is a weighted sum of independent terms:

| Signal | Weight | Source |
|--------|--------|--------|
| Category affinity | 3.0 | User's orders + favorites + cart + recent views |
| Co-purchase | 2.5 | Products bought alongside this user's purchases |
| Recent view/click | 1.5 | UserEvent `view`/`click` in last 30 days |
| Global popularity | 1.0 | Order count across all users (tie-breaker) |
| Featured flag | 0.5 | `Product.is_featured` merchandising boost |
| Collaborative filtering | 0.0 | Disabled — reserved for phase 2 |
| Regional popularity | 0.0 | Disabled — `W_GEO` slot; geo captured now, ranking deferred (see `LOCATION.md`) |

### Category Affinity Sub-weights

Category affinity aggregates multiple signals with their own weights:

| Behavior | Contribution |
|----------|-------------|
| Past purchase in category | 3.0 |
| Favorited product in category | 2.0 |
| Product in current cart | 1.5 |
| Viewed/clicked product in category (last 30 days) | 1.0 |

A past purchase carries the most signal because it reflects confirmed taste, not just
browsing curiosity.

## Cold-Start Handling

When a user has no behavioral signal (new user, no purchases/favorites/views):

1. `has_signal()` returns `False`
2. `recommend()` falls back to `_fallback()` — featured-first, then any active
   in-stock products
3. This fallback also pads the result when a user has *some* signal but fewer than
   `limit` scored products above zero

## Caching

```
ngu:recs:<user_id>:home:12  →  TTL_SHORT (60s)   per-user
ngu:recs:popularity:v1      →  TTL_MEDIUM (300s)  shared across all users
```

The popularity cache is shared because recomputing it per-user would re-aggregate the
full `OrderItem` table on every cold request. It refreshes every 5 minutes, so very
recent orders affect recommendations within ~5 minutes.

Per-user recommendation caches are invalidated (via `invalidate_user_recommendations`)
after a purchase, so recommendations update immediately after checkout.

## Event Types

Events are sent by the frontend to `POST /api/events/`:

| `event_type` | When fired |
|--------------|-----------|
| `view` | Product/combo detail page rendered |
| `click` | Product clicked in a listing |
| `add_to_cart` | Item added to cart |
| `remove_from_cart` | Item removed from cart |
| `favorite` | Product added to favorites |
| `search` | Search query submitted |
| `purchase` | Order placed (triggers cache invalidation) |

All events are optional — only logged-in users' events are stored. Anonymous browsing
is not tracked.

## Phase 2: Collaborative Filtering

The `W_CF = 0.0` weight and `_cf_score()` method are intentional placeholders. When
ready, a collaborative-filtering model output (e.g., matrix factorization score) can
be blended in by:

1. Implementing `_cf_score(product_id)` to return a normalized `[0, 1]` score from
   the CF model.
2. Bumping `W_CF` to a non-zero value (e.g., `1.5`).

No other code needs to change — the weighted sum already accounts for it.

## API

```
GET /api/recommendations/        (authenticated users only)

→ 200
[
  {
    "id": 5,
    "name": "Nidhi Haldi Powder 100g",
    "slug": "nidhi-haldi-powder-100g",
    "price": "49.00",
    "discount_price": "39.00",
    "image": "https://res.cloudinary.com/...",
    "score": 6.75,
    "score_type": "personalized"   // or "popular" for fallback
  },
  …
]
```

`score` and `score_type` are debug fields — the frontend can ignore them or use them
to show "because you bought X" explanations in future.
