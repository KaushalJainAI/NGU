# AI Search Engine Integration

The NGU Spices backend uses an LLM to generate extensive lists of regional, phonetic, and
translated synonyms for every product and combo, powering the search autocomplete and
full-text matching.

The search logic lives in `products/recommendations.py`. Corpus building and fuzzy matching are implemented as standalone functions (`build_search_corpus`, `get_search_corpus`, `_score_matches`, `build_suggestions`). `SpiceSearchEngine` is the class that wraps LangChain and handles LLM synonym generation.

## Architecture

1. **Provider:** Configurable via env vars — `MODEL_PROVIDER` + `LLM_MODEL` + `LLM_API_KEY`.
   The default production setup uses **OpenRouter** (`minimax/minimax-m2.5`). Any provider
   supported by LangChain's `init_chat_model` works.
2. **Framework:** [LangChain](https://python.langchain.com/) (`langchain-core`,
   `langchain`) for prompts, chat model initialization, and JSON output parsing.
3. **Storage:** `ProductSearchKB` and `ProductComboSearchKB` models store synonyms in
   PostgreSQL `JSONField`s (one row per product/combo).
4. **Matching:** `rapidfuzz` `token_set_ratio` + `WRatio` with entry-kind weighting
   (`name: 1.0`, `token: 0.95`, `category: 0.9`, `synonym: 0.85`), exact/prefix bonuses,
   and strict guards for very short queries (1–3 chars) that require prefix or exact matches.

## The Search Logic

When a user searches for `"haldi"` on the storefront:

1. The backend loads the **search corpus** from Redis (key `ngu:search:corpus:v1`,
   built by `build_search_corpus()`). The corpus contains product/combo names, slugs,
   name tokens, category names, and the LLM-generated synonyms.
2. `rapidfuzz` scores every entry with `token_set_ratio` + `WRatio`; entry-kind weights
   (exact names outrank synonyms) and an exact/prefix bonus shape the final score.
3. Because the LLM was prompted to generate multilingual Indian variations, `"turmeric
   powder"` matches `"haldi"`, `"pasupu"`, `"manjal"`, and Hinglish spellings.
4. **The LLM is optional at query time.** Names/slugs/tokens/categories are always in
   the corpus; deterministic fallback synonyms are written to the KB when the LLM is
   unavailable, so search degrades gracefully.
5. Featured/category recommendations are mixed in only when a query yields fewer than
   3 direct matches.

## Keeping the KB Fresh

The KB auto-refreshes via `post_save` signals when products/combos/categories are saved
through Django (entries older than 7 days regenerate in a background thread).

**Important:** direct-SQL catalog changes (e.g. bulk price/description updates) bypass
Django signals. After any such change run:

```bash
python manage.py populate_search_kb --force
```

This regenerates every active product/combo KB entry and invalidates the search cache.

## Non-Blocking Background Generation

LLM synonym generation is slow (several seconds per product). To avoid blocking the
HTTP response, generation runs in a **native Python daemon thread**
(`products/utils.py → run_in_background`), removing the need for Celery.

### Flow

1. Admin saves a `Product` in the Django Admin.
2. `post_save` signal fires instantly.
3. Signal delegates `a_ensure_search_kb` to a background thread.
4. HTTP response returns immediately.
5. Background thread uses `asyncio` to call LangChain `ainvoke()`.
6. Synonyms are stored in `ProductSearchKB`; the thread calls
   `django.db.close_old_connections()` to prevent connection-pool exhaustion.

## No-Results vs. Suggestions

`unified_search` distinguishes an honest empty state from a padded one:

- When a query has **some** direct matches but fewer than 3, it tops the list up
  with related recommendations (`0 < len(direct_results) < 3`) so a thin page still
  feels full.
- When a query matches **nothing** (`zzzzqqq`), it returns **no** products/combos.
  The recommendations instead ride along under a separate `suggestions` key — never
  counted in `total_results` — so the UI can render a real "no results, but you might
  like…" state instead of passing featured products off as hits.

## SEO: sitemap & robots

`products/sitemaps.py` serves `GET /sitemap.xml` (catalog-driven: active products,
combos, categories, and static routes) and `GET /robots.txt` (points crawlers at the
sitemap; keeps cart/billing/profile out of the index). Both are wired at the **site
root** in `spices_backend/urls.py` and proxied there by nginx — previously the SPA
catch-all swallowed `/sitemap.xml` and served `index.html`.

## Multilingual Support

The backend stores and returns translated content for Products and Categories via
`django-modeltranslation`. Language is selected at request time via a `?lang=` query
parameter or `X-Language` header. Supported languages: `en`, `hi`, `hinglish`, `gu`,
`mr`, `pa`. The assistant also replies in the user's language.

## Environment Variables

```env
# Required for synonym generation and the AI assistant
LLM_API_KEY=sk-or-v1-...         # API key for the LLM provider
MODEL_PROVIDER=openrouter         # LangChain provider name
LLM_MODEL=minimax/minimax-m2.5   # Model used for synonym generation

# Optional: separate stronger model for the shopping assistant
ASSISTANT_MODEL_PROVIDER=openrouter
ASSISTANT_LLM_MODEL=openai/gpt-4o-mini
```

If `LLM_API_KEY` is absent, synonym generation falls back to deterministic terms and
the shopping assistant returns a polite fallback reply — the storefront keeps working.
