# Database Filling — Product Catalog Content Update

**Date:** 2026-06-11
**Scope:** All 25 products in the production catalog (`products_product` table)
**Fields updated:** `description`, `ingredients`, `origin_country`, `price`, `discount_price`, `updated_at`
**Fields never touched:** `name`, `slug`, `image`, `stock`, `weight`, `unit`, `category`

## What was done

The production database was filled with rewritten product descriptions, ingredient lists, and benchmarked prices for all 25 Nidhi Masala products. Content was **adapted (not copied)** from competitor [pushponline.com](https://pushponline.com) — their descriptions were used as a structural/factual reference, then rewritten under the Nidhi brand (Pushp brand mentions, ISO certificate claims, and "trusted since 1974" lines removed; bullets rephrased).

## Target environment

- **Database:** production Postgres `ngu_db` at `3.109.47.72:6432` (credentials in `backend_remote.env` — use its `DATABASE_URL`)
- **Live API:** https://nidhimasala.com/api/
- The local `Backend/db.sqlite3` is **stale with an outdated schema** — it was not used and must not be trusted.

## Pipeline (5 steps)

### 1. Snapshot the live catalog
Fetched current products from the live API into `live_products.json` (25 products) and `live_combos.json` (empty).

### 2. Scrape the reference data — `pushp_scrape.py`
Pulled Pushp product data from their public WooCommerce Store API
(`https://pushponline.com/wp-json/wc/store/v1/products/{id}`).

- The endpoint rate-limits aggressively (HTTP 429); the script sleeps 3s between requests and backs off 15s × attempt on 429, up to 6 tries.
- All responses are cached on disk in `pushp_fetch_cache.json` so re-runs don't re-hit the API.
- For variable products it resolves the **variation matching the Nidhi pack weight** (preferring pouch packaging) and reads that variation's regular/sale price (WooCommerce prices are in paise, divided by 100).
- Output: `pushp_matched.json` — per Nidhi product ID: matched Pushp product, cleaned description/short description, attributes, and prices.

### 3. Manual product mapping
The Nidhi → Pushp mapping is hardcoded in `MAPPING` inside `pushp_scrape.py` (20 entries). Non-obvious matches:

| Nidhi product | Pushp equivalent |
|---|---|
| Patna Mirchi 500g | Shahi Rangat |
| VIP Teja Mirchi 500g | Tikha Tadka |
| Desi Tadka Mirchi 500g | Red Chilli Powder |
| Jeeravan 100g | Jeeravan Sprinkler 100g |
| Nimbu Chatani Achar Masala 200g | Achar Masala (same as Hari Mirchi Achar, id 1956) |

**Pushp sells no papad or papad-masala products.** The 5 Nidhi papad items (e.g., Chana Papad 200g, Moong Papad 200g, Chana Papad Masala 130g) had no price reference, so they **kept their regular price with a ~18% discount applied** to stay consistent with the rest of the catalog.

### 4. Author the update payload — `catalog_update.json`
The final content for all 25 products, keyed by Nidhi product ID:

```json
{
  "32": {
    "name": "Nidhi Pav Bhaji masala 100g",   // used as a safety check, never written
    "price": 96.0,
    "discount_price": 79.0,
    "origin_country": "India",
    "ingredients": "...",
    "description": "..."                      // intro paragraph + "- " bullet list
  }
}
```

Pricing rule: `price` = Pushp regular price for the same pack weight, `discount_price` = Pushp sale price. Products without a `price` key (the papads) keep their DB price and only get the discount applied.

### 5. Apply to production — `apply_catalog_update.py`

```powershell
# preview (rolls back, writes nothing)
python apply_catalog_update.py --dry-run --db <DATABASE_URL>

# write (single transaction)
python apply_catalog_update.py --apply --db <DATABASE_URL>
```

Safety behavior:
- Reads `DATABASE_URL` from env or `--db`; requires `psycopg2`.
- For each product it verifies the **DB name matches the JSON name** (case-insensitive); mismatches and missing IDs are skipped and reported.
- All updates run in **one transaction** — dry-run rolls back, `--apply` commits at the end.

**Result on 2026-06-11: 25 products updated, 0 skipped, committed.**

## Verification

`live_check.json` was fetched from the live API *after* the apply and matches `catalog_update.json` (e.g., Pav Bhaji Masala 100g shows ₹96 / ₹79 discounted). 25 products returned.

Note: the server caches product lists in Redis (django-redis, key prefix `ngu:`, TTL 5–15 min). Raw SQL updates bypass the signal-based cache invalidation, so the API can serve stale data for up to ~15 minutes after an update. This is acceptable; to force it, flush the `ngu:` keys on the server.

## File inventory (repo root)

| File | Role |
|---|---|
| `pushp_scrape.py` | Scrapes Pushp Store API, resolves variations/prices |
| `pushp_fetch_cache.json` | Disk cache of raw API responses (avoid re-hitting rate limits) |
| `pushp_products_p1.json` / `_p2.json` | Raw paginated product list dumps |
| `pushp_matched.json` | Nidhi ID → matched Pushp content + prices |
| `pushp_descriptions.txt` | Cleaned Pushp description text for reference while rewriting |
| `catalog_update.json` | **Final payload** — the content now in production |
| `apply_catalog_update.py` | Applies the payload to Postgres (dry-run / apply) |
| `live_products.json` | Live API snapshot **before** the update |
| `live_check.json` | Live API snapshot **after** the update (verification) |

## How to re-run / update again

1. Edit `MAPPING` in `pushp_scrape.py` if products changed; run it to refresh `pushp_matched.json` (the cache makes this cheap).
2. Edit `catalog_update.json` with the new content/prices.
3. `python apply_catalog_update.py --dry-run --db <url>` and review the printed diff of prices.
4. Re-run with `--apply`.
5. **Regenerate the search knowledge base** — raw SQL bypasses the Django signals that refresh search synonyms, so on the server run:
   ```bash
   python manage.py populate_search_kb --force
   ```
   (See `Backend/docs/AI_SEARCH_ENGINE.md` for details.)
6. Wait out the Redis TTL (or flush `ngu:` keys), then re-fetch the live API to confirm.
