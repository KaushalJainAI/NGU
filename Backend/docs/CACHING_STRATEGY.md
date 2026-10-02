# Caching Strategy

The NGU backend caches frequently accessed data in Redis. All cache keys are prefixed
with `ngu:` (set via `KEY_PREFIX` in `settings.py`) to prevent collisions across
environments.

## Redis Implementation

The caching backend is **Redis** (via `django-redis`). If `REDIS_URL` is not set,
the system falls back to Django's `LocMemCache`.

```python
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'KEY_PREFIX': 'ngu',
    }
}
```

## Cache Key Namespaces

Key generation lives in `products/cache.py` via `make_cache_key(prefix, *args)`.
The `ngu:` prefix is appended automatically by django-redis.

| Prefix constant | Full Redis pattern | Content |
|---|---|---|
| `products` | `ngu:products:*` | Product list and detail responses |
| `categories` | `ngu:categories:*` | Category listing |
| `combos` | `ngu:combos:*` | Combo list and detail |
| `sections` | `ngu:sections:*` | Homepage section data |
| `search` | `ngu:search:*` | Search corpus (`ngu:search:corpus:v1`) and suggest responses |
| `recs` | `ngu:recs:*` | Per-user recommendation results and global popularity |

## Automatic Invalidation

Django Signals (`post_save`, `post_delete`) in `products/signals.py` selectively
purge caches when data changes.

| Model saved/deleted | Caches invalidated |
|---|---|
| `Product` | `products:*`, `sections:*`, `search:*` |
| `ProductVariant` | `products:*`, `sections:*` |
| `ProductCombo` | `combos:*`, `sections:*`, `search:*` |
| `Category` | `categories:*`, `products:*`, `search:*` |
| `ProductSection` | `sections:*` |
| `ProductSearchKB` | `search:*` |
| `ProductComboSearchKB` | `search:*` |

Notes:
- `Category` also invalidates `products:*` because product list responses embed category names.
- `ProductSearchKB`/`ProductComboSearchKB` trigger a second search-cache invalidation when the background LLM thread finishes writing new synonyms — this is intentional so the corpus refreshes as soon as the new synonyms land.
- `ProductVariant` changes bust product caches because listing/detail responses embed variant prices and stock.

## TTL Settings

Defined in `settings.py` and read by `cache.py`:

| TTL | Seconds | Used for |
|-----|---------|----------|
| `CACHE_TTL_SHORT` | 60 | Frequently changing data (recommendations) |
| `CACHE_TTL_MEDIUM` | 300 | Default — product lists, combo displays, popularity |
| `CACHE_TTL_LONG` | 900 | Mostly-static data (categories) |

## Language-Keyed Cache Entries

Product and category responses vary by language — `name_hi` differs from `name_en`.
Cache keys include the active language (`get_language()` from Django's translation
framework, activated per-request by `LanguageQueryMiddleware`):

```python
make_cache_key('products', request.query_params, get_language())
# → ngu:products:<hash-of-filters>:hi
```

This means the same filter applied in Hindi and English hits **separate** cache entries.
Changing a product's Hindi name invalidates `ngu:products:*` (all language variants),
not just the Hindi entry — the signal invalidation is intentional to keep things simple.

## Dashboard Cache

Dashboard stats (`GET /api/dashboard/`) are cached at `ngu:dashboard:stats` with a
**120-second TTL** (2 minutes). This cache is **not** invalidated on order creation —
stats may lag up to 2 minutes after activity. The tradeoff is deliberate: aggregating
order counts and revenue across all orders on every page load would be expensive.

## Important: Direct SQL Bypasses Signals

Raw SQL updates (e.g. bulk catalog scripts via psql) bypass Django signals and do
**not** invalidate caches. After any direct SQL catalog change:

1. Wait out the TTL, **or** flush `ngu:*` keys on the Redis server.
2. Run `python manage.py populate_search_kb --force` to regenerate search synonyms.
