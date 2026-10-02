# AI Search Engine

Everything behind the storefront search box: the autocomplete dropdown, the
`/search` results page, the LLM-generated synonym knowledge base that makes
`"haldi"` find *Turmeric Powder*, the caching that keeps it off the database, and
the analytics that tell you what shoppers typed and failed to find.

**Design goal:** an Indian shopper types whatever comes to mind — Hindi,
Hinglish, a regional name, a typo, a pack size — and still lands on the right
product. There is **no vector database and no LLM call at query time**. The LLM
runs *offline*, once per product, to expand the vocabulary; matching at request
time is pure in-process fuzzy string scoring over a Redis-cached corpus.

---

## 1. Files & responsibilities

| File | What lives there |
|---|---|
| `products/recommendations.py` | The whole engine: corpus building, scoring, suggestions, LLM synonym generation, `SpiceSearchEngine` |
| `products/cache.py` | Corpus cache key, `get_cached_or_set`, prefix invalidation |
| `products/signals.py` | `post_save`/`post_delete` hooks that refresh the KB and bust the corpus |
| `products/utils.py` | `run_in_background` — daemon-thread offload for LLM calls |
| `products/views.py` | `unified_search` (full search) and `search_suggest` (autocomplete) HTTP views |
| `products/serializers.py` | `SearchProductSerializer`, `SearchComboSerializer` — safe result shaping |
| `products/models.py` | `ProductSearchKB`, `ProductComboSearchKB` (synonym storage) |
| `products/management/commands/populate_search_kb.py` | Bulk/forced KB regeneration |
| `spices_backend/limits.py` | `MAX_SEARCH_Q`, `SEARCH_TOP_K_MAX`, threshold clamps |
| `analytics/…` | `SearchTermStat` rollup — top terms + zero-result terms |
| `assistant/tools.py` | `tool_search_products` — the AI chat assistant reuses `build_suggestions` |
| Frontend `src/components/SearchAutocomplete.tsx` | Debounced dropdown, product + page results |
| Frontend `src/pages/SearchResults.tsx` | `/search` results page, client-side re-sorting |
| Frontend `src/lib/searchablePages.ts` | Client-side "jump to page" registry (cart, policies, orders…) |

Note the structural split: `build_search_corpus`, `get_search_corpus`,
`_score_matches` and `build_suggestions` are **module-level functions** (no LLM
dependency, importable and testable in isolation). `SpiceSearchEngine` is the
class, and it only exists to own the LangChain client plus the search
orchestration methods.

---

## 2. The two endpoints

| | `GET /api/search/suggest/` | `GET /api/search/` |
|---|---|---|
| Purpose | Autocomplete dropdown (per keystroke) | Full results page |
| Params | `q`, `limit` (1–15, default 8) | `q`, `top_k` (1–100, default 20), `threshold` (0–100, default 70) |
| Auth | Public | Public |
| Throttle | `search_suggest` scope — **60/min** per user *or* per IP | Generic anon/user scope |
| Min query | 2 chars (shorter → empty list, no work done) | 1 char |
| Response cached | Yes — `search:suggest:<lang>:<q>:<limit>`, TTL_MEDIUM (300 s) | No (only the corpus underneath is) |
| Payload | `{query, suggestions:[{id,name,slug,type,price,image}]}` | products + combos + `suggestions` + `stats` |
| Implementation | `build_suggestions()` | `SpiceSearchEngine.unified_search()` |

Both are registered at the project root in `spices_backend/urls.py`
(`api/search/suggest/` **before** `api/search/`).

### Input hardening

`unified_search` rejects `q` longer than `MAX_SEARCH_Q` (200) with a 400 — a
megabyte query would otherwise drive a full fuzzy pass over the corpus. `top_k`
and `threshold` must parse as integers (400 otherwise) and are then `clamp()`ed
into `[1, 100]` and `[0, 100]`, so a caller cannot request 10 000 results or a
negative threshold. All limits are env-overridable via `spices_backend/limits.py`.

`search_suggest` is deliberately more forgiving: a bad `limit` silently falls
back to 8 rather than 400ing, because it is called on every keystroke.

The autocomplete endpoint has its **own throttle class** (`SearchSuggestThrottle`)
keyed on user PK when authenticated and on IP otherwise. Without it, a shopper
typing normally would burn through the shared anonymous budget and start getting
429s on unrelated endpoints.

---

## 3. The search corpus — the thing everything matches against

The corpus is a flat list of `{text, id, type, kind}` dicts, built by
`build_search_corpus()` in **one pass over the catalog** (two queries for
products + their KBs, two for combos + their KBs) and cached in Redis under
`ngu:search:corpus:v1` for `TTL_LONG` (900 s).

### What goes in

For every **active product**:

| Entry | `kind` | Example |
|---|---|---|
| Product name | `name` | `nidhi turmeric powder 500g` |
| Slug with hyphens → spaces | `name` | `nidhi turmeric powder 500g` |
| Each name token ≥3 chars | `token` | `nidhi`, `turmeric`, `powder` |
| `"<name> <weight><unit>"` | `token` | `nidhi turmeric powder 500g 500g` |
| Category name | `category` | `masalas` |
| Every KB synonym | `synonym` | `haldi`, `haldee`, `manjal`, `pasupu` |

For every **active combo**: name, slug, name tokens, **the names of up to 5
member products** (so "haldi" can surface a combo containing turmeric), and its
KB synonyms.

Every text is lowercased, whitespace-collapsed, dropped if <2 chars, and deduped
on `(text, object_id, object_type)`.

### Two deliberate decisions worth understanding

**Names/slugs/tokens/categories are always present, independent of the KB.**
The LLM is a *vocabulary amplifier*, never a dependency. A product whose KB row
was never generated (LLM down, brand-new product, API key missing) is still
fully findable by its own name. Test: `test_product_without_kb_still_matchable`.

**Out-of-stock products stay in the corpus on purpose.** Stock is re-filtered at
fetch time (`stock__gt=0` on the final `Product.objects.filter`). If stock had
been baked into the corpus, every single sale would invalidate a 900-second
cache — the corpus would essentially never be warm on a busy store.

### Weight tokens are excluded from `_name_tokens`

```python
# products/recommendations.py
return [t for t in re.split(r'[^a-z0-9]+', name.lower())
        if len(t) >= 3 and not re.fullmatch(r'\d+[a-z]{0,2}', t)]
```

`token_set_ratio` scores *any* shared token at 100. If `500g` were a standalone
token entry, the query `"500g"` — or worse, `"haldi 500g"` — would match every
500 g product in the catalog at a perfect score. The combined `"<name> 500g"`
entry preserves the useful case (weight-qualified search) without the blast
radius.

---

## 4. Scoring — `_score_matches`

Input: query string, the corpus slice for one object type, a threshold.
Output: `{object_id: score}` where score ≤ 100.

### 4a. Short queries (≤3 chars) take a separate path

`token_set_ratio` on a 2-char query matches half the catalog. So for `len(q) ≤ 3`
the engine ignores fuzzy scoring entirely and requires either:

- `text.startswith(query)` → base **90**, or
- `fuzz.ratio(query, text) ≥ 90` → that ratio,

then multiplies by the kind weight and requires the result to clear
`max(threshold, 85)`. Test: `test_short_query_does_not_match_everything`
asserts fewer than 4 direct hits for `"ha"`.

### 4b. Normal queries (≥4 chars)

Two `rapidfuzz` scorers run over the entry texts via `process.extract(...,
score_cutoff=threshold, limit=None)`, and the **max** of the two is the base:

- **`token_set_ratio`** — order-insensitive, handles extra/missing words.
  `"powder haldi"` still matches `"haldi powder"`; `"nidhi haldi"` matches
  `"nidhi turmeric powder 500g"` on the shared token.
- **`WRatio`** — rapidfuzz's weighted composite; better on typos and on length
  mismatch between query and text (`"tumeric"` → `"turmeric"`).

### 4c. Kind weighting

```python
KIND_WEIGHTS = {'name': 1.0, 'token': 0.95, 'category': 0.9, 'synonym': 0.85}
```

An object's actual name outranks a bare token, which outranks its category,
which outranks an LLM-invented synonym. This is what makes
`test_exact_name_outranks_synonyms` pass: searching `"nidhi jeeravan 100g"`
returns the Jeeravan product first even though other products share the "nidhi"
token and have overlapping synonyms.

### 4d. Exact / prefix bonus — and why tokens are excluded from it

```python
if entry['kind'] != 'token':
    if fuzz.ratio(query, text) > 95:                       final += 30   # near-exact
    elif len(query) >= 4 and (text.startswith(query)
         or fuzz.partial_ratio(query, text) > 90):         final += 15   # prefix/substring
final = min(final, 100)
```

Bonuses are skipped for `token` entries deliberately. A shared brand token like
`nidhi` matches at 100 for *every* product; giving it a bonus would push it to
the 100 ceiling everywhere and completely erase the kind weighting that ranks the
correctly-named product first.

An object matched through several entries keeps its **best** score
(`scored[oid] = max(...)`).

### Complexity

`O(len(corpus))` per query per object type, entirely in-process, no DB hit
during scoring. `rapidfuzz` is a C++ extension, so a few-thousand-entry corpus
scores in single-digit milliseconds. The only DB queries in a search request are
the final `id__in` fetches for the top-K winners.

---

## 5. Full search pipeline — `unified_search`

```
GET /api/search/?q=haldi&top_k=20&threshold=70
  │
  ├─ view: length check → int-parse top_k/threshold → clamp
  │
  ▼
SpiceSearchEngine.unified_search(query, top_k, threshold)
  │
  ├─ 1. _fuzzy_search_all(query, top_k, threshold)
  │      ├─ corpus = get_search_corpus()            # Redis, or rebuild + cache
  │      ├─ _score_matches(q, product entries, th)  # {product_id: score}
  │      │     └─ top-K ids → Product.objects.filter(id__in, is_active, stock__gt=0)
  │      │                     .select_related('category')
  │      │                   → SearchProductSerializer  (+ score, score_type='direct')
  │      ├─ _score_matches(q, combo entries, th)    # {combo_id: score}
  │      │     └─ top-K/2 ids → ProductCombo.objects.filter(id__in, is_active)
  │      │                       .prefetch_related('products')
  │      │                     → SearchComboSerializer  (+ score, score_type='direct')
  │      └─ sort by score desc, truncate to top_k
  │
  ├─ 2. if 0 < len(direct) < 3:  _other_recommendations(query, top_k//2)
  │        ├─ Category.objects.filter(name__icontains=q).first()
  │        │     → its in-stock products, score 75, score_type='category'
  │        └─ featured in-stock products, score 60, score_type='trending'
  │
  ├─ 3. _rank_and_dedupe(direct + recs, top_k)
  │        score *= {direct: 1.0, category: 0.8, trending: 0.5}
  │        dedupe on (type, id) keeping the higher weighted score
  │        sort desc, truncate
  │
  ├─ 4. split into products[] / combos[]
  │
  └─ 5. if nothing survived: suggestions = ranked _other_recommendations
```

Response:

```jsonc
{
  "query": "haldi",
  "total_results": 3,
  "products": [ { …, "score": 100, "score_type": "direct" } ],
  "combos":   [ … ],
  "suggestions": [],          // NEVER search results — populated only when there are none
  "stats": { "direct_matches": 3, "other_recs": 0 }
}
```

### `_rank_and_dedupe` — the scale bug it exists to prevent

The score-type weight is folded into the score **once, up front**, *before*
dedupe compares candidates:

```python
final_score = item['score'] * score_weights.get(item['score_type'], 0.5)
existing = scored.get(item_id)
if existing is None or final_score > existing['score']:
    scored[item_id] = {**item, 'score': final_score}
```

The earlier version compared an incoming **raw** score against a stored
**weighted** score — mixing scales, so a weak fallback could evict a genuine
direct hit for the same product. Because direct matches must clear the fuzzy
threshold (≥70 × 1.0) while fallbacks are hard-capped at 75 × 0.8 = 60 and
60 × 0.5 = 30, a real match now always outranks padding. Covered by
`TestRankAndDedupe`.

### No-results vs. padded results — the honesty rule

This distinction is the reason `unified_search` has the shape it does:

- **Some matches, but thin** (`0 < direct < 3`) → top up with category/trending
  recommendations so the page doesn't look broken. They appear inside `products`
  but are tagged `score_type: "category"` / `"trending"` so the UI can tell.
- **Zero matches** (`"zzzzqqq"`) → return **no** products and **no** combos.
  The recommendations ride along under a separate `suggestions` key and are
  **never counted in `total_results`**.

Before this split, a nonsense query returned a featured product as a "result"
and the UI could never render an honest "no results" state — and zero-result
analytics were silently useless. Tests: `test_search_no_matches_returns_no_products`
and friends in `products/test_admin_and_seo.py`.

> Frontend note: `SearchResults.tsx` currently renders `products` and shows the
> "no results, try something different" empty state — it does **not** yet render
> the `suggestions` array. The backend contract is there for the UI to adopt.

---

## 6. Autocomplete pipeline — `build_suggestions`

A deliberately cheaper, differently-ranked path. It is **not** `unified_search`
with a small `top_k`.

```
GET /api/search/suggest/?q=hal&limit=8
  │
  ├─ view: q.strip().lower(); if len < 2 → {suggestions: []}   (zero work)
  ├─ response cache: search:suggest:<lang>:<q>:<limit>, TTL 300 s
  ▼
build_suggestions(query, limit)
  │
  ├─ Pass 1 — PREFIX. Every corpus entry where text.startswith(query).
  │            Sort key = (KIND_RANK[kind], 0)  with
  │            KIND_RANK = {name:0, token:1, category:2, synonym:3}
  │
  ├─ Pass 2 — FUZZY TOP-UP, only if pass 1 yielded < limit candidates.
  │            process.extract(WRatio, score_cutoff=75, limit=30)
  │            Sort key = (4, -score) → always ranked below every prefix match.
  │
  ├─ Order candidates by sort key; split ids into products / combos
  ├─ Hydrate with .only('id','name','slug','price','discount_price','image','thumbnail')
  │            products additionally filtered is_active + stock__gt=0
  └─ Emit up to `limit` rows: {id, name, slug, type, price, image}
```

Why prefix-first: an autocomplete that reorders under you as you type is
infuriating. Prefix matching is stable and predictable — typing `h → ha → hal`
narrows monotonically. Fuzzy only fills empty space at the bottom.

Why `.only(...)`: the dropdown needs six fields. Loading full product rows (with
descriptions, recipes, per-language translation columns) on every keystroke is
pure waste.

`thumbnail` is preferred over `image`; `final_price` (the discount-aware
property) is what's sent as `price`.

### The AI chat assistant shares this path

`assistant/tools.py → tool_search_products` calls `build_suggestions(query[:100],
limit=6)`. So when a shopper asks the chat assistant "do you have haldi?", it
resolves through the exact same corpus and ranking as the search box — one
vocabulary, one behaviour, no second index to keep in sync. See
`docs/ASSISTANT.md`.

---

## 7. The knowledge base — LLM synonym generation

### Storage

`ProductSearchKB` / `ProductComboSearchKB`: a `OneToOneField` to the product or
combo, a `synonyms` `JSONField(default=list)`, and `last_updated`
(`auto_now=True`, indexed). `get_synonyms_list()` guards against a non-list value
ever having been written.

### Model configuration

```env
MODEL_PROVIDER=openrouter          # LangChain provider name
LLM_MODEL=minimax/minimax-m2.5     # model used for synonym generation
LLM_API_KEY=sk-or-v1-...
```

`SpiceSearchEngine.__init__` special-cases `openrouter` (constructs `ChatOpenAI`
against `https://openrouter.ai/api/v1`) and otherwise defers to LangChain's
`init_chat_model`. `temperature=0.1` — this is a vocabulary task, not a creative
one. **A failed init is caught and logged, leaving `self.llm = None`**; search
keeps working, only generation is disabled.

### The prompt (`SYNONYM_PROMPT`)

Asks for 25–35 terms an Indian shopper would actually type, with required
coverage of: regional Indian names, Hindi/English (Hinglish) mixes,
transliteration variants, real misspellings, weight-qualified terms matching the
actual pack size, and forms (powder/whole/raw) only where applicable. Strict
rules forbid standalone generics, marketing phrases, and names of unrelated
products. Output must be `{"synonyms": [...]}` — parsed by
`JsonOutputParser`.

Prompt context comes from `_build_kb_context()`, which feeds the model the
object's *real* catalog content: category, spice form, pack size, ingredients
(200 chars), description (400 chars) — or, for combos, the member product names
plus description. Grounded context is what keeps the terms product-specific
instead of generic spice vocabulary.

### LLM output is untrusted — `_clean_synonyms`

Every returned term must survive:

| Check | Reason |
|---|---|
| `isinstance(item, str)` | model may emit objects/numbers |
| no `\n` in term | multi-line output is prose, not a search term |
| whitespace collapsed, lowercased, stripped | corpus normalization |
| `2 ≤ len ≤ 60` | rejects noise and sentences |
| not `term.isdigit()` | bare numbers match nothing useful |
| no `{`, `}`, `http` | template leakage / injected URLs |
| not in `GENERIC_BLOCKLIST` | 34 words like `powder`, `masala`, `organic`, `best`, `online` that would match the whole catalog |
| `term != name.lower()` | the name is already in the corpus |
| dedupe, cap at `cap` (30 default, 35 after merge) | bounds corpus growth |

### Three-source merge — `_finalize_synonyms`

```
LLM terms  +  COMMON_BOOSTS[matching base]  +  deterministic terms  → _clean_synonyms(cap=35)
```

- **`COMMON_BOOSTS`** — hand-curated variants for the highest-traffic spices
  (`haldi`, `turmeric`, `mirch`, `chilli`), including regional names (`manjal`,
  `pasupu`) and the misspelling `tumeric`. These are the queries you cannot
  afford to get wrong, so they don't depend on the model.
- **`_deterministic_synonyms`** — derived purely from the object: name, name
  tokens, slug tokens, category name, `"<name> powder"` when
  `spice_form == 'powder'`, and `"<name> <weight><unit>"`. **A KB row is never
  empty**, even with the LLM completely unavailable.

`generate_synonyms` retries twice, catches every exception, and on total failure
returns `_finalize_synonyms([], name, deterministic)` — i.e. the deterministic
set. **It never raises and never returns empty.**

### Freshness — `ensure_search_kb`

```python
kb, created = kb_model.objects.get_or_create(**{kb_field: obj})
if created or force or (timezone.now() - kb.last_updated).days > 7:
    …regenerate…
```

Created, forced, or older than 7 days. Everything else is a no-op, so signals
firing on unrelated saves cost one indexed lookup.

---

## 8. Non-blocking generation & cache invalidation

LLM generation takes seconds per product. It must never sit inside an HTTP
request, and NGU has **no Celery** — `products/utils.py → run_in_background`
starts a **daemon thread** instead:

```
Admin saves a Product
      │
      ├─ post_save fires synchronously
      │     ├─ run_in_background(search_engine.a_ensure_search_kb, instance)   ── returns instantly
      │     ├─ invalidate_product_cache()
      │     └─ invalidate_search_cache()
      │
      └─ HTTP 200 returned to the admin  ◄── does not wait for the LLM
                │
   (thread)     ├─ asyncio.run(a_ensure_search_kb(...))  → chain.ainvoke()
                ├─ kb.synonyms = […]; kb.save()
                │      └─ post_save on ProductSearchKB → invalidate_search_cache()  ◄── critical
                └─ finally: close_old_connections()
```

Three details that matter:

1. **`close_old_connections()` in a `finally`** — each thread gets its own DB
   connection. Without the cleanup, a bulk import spawning hundreds of threads
   exhausts the Postgres/PgBouncer pool.
2. **The KB-model signal is not redundant.** The product's own `post_save`
   invalidated the corpus *before* the LLM finished. When the KB row lands
   seconds later, the corpus must be invalidated **again** — otherwise the freshly
   generated synonyms sit in the DB unused for up to 900 s.
   `invalidate_search_cache_on_kb_change` covers both KB models, save and delete.
3. **`run_in_background` is a no-op under `TESTING`.** A background thread on its
   own connection can't see a test's rolled-back transaction (FK errors), and
   would fire real LLM calls. Tests call `ensure_search_kb` directly.

### Which signals touch the search corpus

| Sender | Signal | Effect |
|---|---|---|
| `Product` | `post_save` | KB refresh in background (if active & in stock) + product cache + **search cache** |
| `Product` | `post_delete` | product cache + **search cache** |
| `ProductCombo` | `post_save` / `post_delete` | same, for combos |
| `Category` | `post_save` | KB refresh for **every active product in the category** (the category name is a corpus entry) + all three caches |
| `ProductSearchKB` / `ProductComboSearchKB` | `post_save` / `post_delete` | **search cache only** — the deferred-write hook above |

`invalidate_search_cache()` calls `delete_pattern('search:*')` on django-redis
**and** explicitly deletes the corpus key, because the locmem backend used in
dev/tests has no pattern matching and would otherwise serve a stale corpus.

Pass the **raw** prefix to `delete_pattern` — django-redis prepends `KEY_PREFIX`
and version itself (`ngu:1:`). Hard-coding `ngu:` produces `ngu:1:ngu:search:*`
and matches nothing.

---

## 9. Keeping the KB fresh in production

Signals only fire on Django ORM saves. **Direct SQL bypasses them entirely** —
bulk price updates, catalog imports run against the DB, `queryset.update()`.
After any such change:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py populate_search_kb --force
```

`--force` regenerates every active product and combo unconditionally (ignoring
the 7-day freshness window) and, via the KB `post_save` signal, invalidates the
search cache when each row lands. Without `--force` the command only fills gaps
and refreshes rows older than a week.

Expect it to take roughly *(products + combos) × a few seconds* — it is
synchronous and sequential by design, so it doesn't stampede the LLM provider.

---

## 10. Caching summary

| Key | Contents | TTL | Invalidated by |
|---|---|---|---|
| `ngu:search:corpus:v2:<lang>` | Whole matchable corpus (all products + combos), one per language | `TTL_LONG` 900 s | product/combo/category/KB save+delete |
| `ngu:search:suggest:<lang>:<q>:<limit>` | Rendered autocomplete payload | `TTL_MEDIUM` 300 s | `delete_pattern('search:*')` — same triggers |

`/api/search/` itself is **not** response-cached: `top_k`/`threshold` are
caller-controlled, so the key space is wide and the scoring is cheap anyway. The
expensive part (corpus assembly) is what's cached.

The `v2` in the corpus key is a manual schema version. **If you change the shape
of corpus entries, bump it** in `products/cache.py → get_search_corpus_key()` —
otherwise a rolling deploy will have new code reading old-shaped cached entries.
The key also carries the active language: the corpus embeds translated names, so
a single global key would serve the first language's terms to everybody until TTL.

---

## 11. Failure modes & degradation

| Failure | Behaviour |
|---|---|
| `LLM_API_KEY` missing / provider down | `self.llm = None`, logged once at init. Deterministic synonyms only. Search fully functional, vocabulary narrower. |
| LLM returns junk / non-JSON | Two attempts, then deterministic fallback. `_clean_synonyms` filters whatever *did* parse. |
| KB row missing for a product | Product still matchable by name, slug, tokens, category. |
| Redis down | `get_cached_or_set` falls through to `build_search_corpus()` — correct results, one extra catalog scan per request. |
| Query >200 chars | 400 before any scoring work. |
| Autocomplete flood | 429 from the dedicated `search_suggest` scope (60/min), other endpoints unaffected. |
| Product goes out of stock | Disappears from results at fetch time — no cache invalidation needed. |

The through-line: **every LLM path is optional and every failure is caught.**
Search is a core storefront function; it degrades, it does not break.

---

## 12. Multilingual behaviour

Product/category/combo `name` and `description` are managed by
`django-modeltranslation` (`products/translation.py`), with per-language columns
and English fallback. Language is chosen per request via `?lang=` or the
`X-Language` header. Supported: `en`, `hi`, `hinglish`, `gu`, `mr`, `pa`.

Two things to know:

- The **suggest response cache is language-scoped** (`get_language()` is in the
  key), so a Hindi shopper never gets an English-cached dropdown.
- The **corpus cache key is not language-scoped** — it's a single
  `search:corpus:v1`. The corpus therefore holds names in whichever language was
  active when it was built. In practice this is benign, because product names in
  this catalog are largely untranslated (translation.py notes names are curated
  manually, not machine-translated, so most fall back to English) and because
  the KB synonyms are explicitly *multilingual by construction* — `haldi`,
  `manjal`, and `pasupu` are all in the same English-language corpus row. **If
  curated per-language names are ever rolled out broadly, the corpus key must
  become language-scoped**; that is the known limitation to watch.

See `docs/MULTILINGUAL.md`.

---

## 13. Frontend experience

### Autocomplete (`SearchAutocomplete.tsx`)

- Built on `cmdk` with `shouldFilter={false}` — **the server ranks, the client
  never re-filters**. Client-side filtering would silently drop synonym matches
  (the dropdown shows "Turmeric Powder" for the query "haldi"; a naive substring
  filter would discard it).
- **250 ms debounce** into `debouncedQuery`, and the query is `enabled` only at
  ≥2 characters, so short/fast typing never hits the network.
- TanStack Query with `staleTime: 60_000` and a `["suggest", lang, query]` key —
  backspacing to a previous prefix is served from the client cache instantly.
  Combined with the server's 300 s response cache and the 60/min throttle, a
  normal typing session costs a handful of requests.
- The dropdown mixes **two sources**: server product/combo suggestions, and
  **client-side page matches** from `src/lib/searchablePages.ts`. Typing "cart",
  "track order", "refund" jumps straight to the page — `matchPages` scores
  exact title (100) > title prefix (80) > keyword exact (75) > keyword prefix
  (60) > title contains (45) > loose contains (35). Pages render above products.
- A permanent last row — *"Search for «query»"* — always offers the full results
  page. Enter with nothing highlighted goes there too.
- Selecting a suggestion navigates directly to `/products/:slug` or
  `/combos/:slug` — one keystroke less than going via the results page.
- On navigation the dropdown closes; on `/search` the input stays populated with
  the active query (editable), everywhere else it resets.

### Results page (`SearchResults.tsx`)

- Calls `searchAPI.search(query)` (`top_k=20`), then fires an analytics
  `search` event with `{results, zero}`.
- Sort control overlays the backend ranking client-side: **Relevance** (default,
  sorts by the backend `score`), Featured, Price ↑/↓, Name. Relevance is the
  backend's opinion; the rest are user overrides on the same result set — there
  is no refetch.
- Matching pages render above the product grid here too.
- `/search` with no query renders a prompt + "Browse all" rather than a blank page.

---

## 14. Search analytics — closing the loop

Every results-page search emits a `search` `UserEvent` with the query and
`metadata: {results, zero}`. The nightly/interval `rollup_analytics` job
(`_rollup_search`) aggregates a day's events into `SearchTermStat`
(`date`, `term`, `count`, `zero_result`), deleting and rebuilding that day's rows
so re-runs are idempotent. A term is flagged `zero_result` if **any** occurrence
that day returned nothing.

`GET /api/analytics/insights/search/` (admin only) then serves:

- `top_terms` — what shoppers actually search for
- `zero_result_terms` — **the direct feedback loop into this engine**: every term
  here is either a product you don't stock (a merchandising signal) or a synonym
  the KB is missing (add it to `COMMON_BOOSTS`, or improve the prompt context)
- `viewed_not_bought` — products with views but no purchases in the window

This is why the "no results means no results" rule in §5 matters operationally:
padding a zero-result query with featured products would have poisoned
`zero_result_terms` and hidden the gaps.

See `docs/ANALYTICS.md`.

---

## 15. What this is *not*

- **Not a vector/semantic search.** No embeddings, no ANN index, no pgvector.
  `_semantic_recommendations` exists as a stub returning `[]`, kept for API
  compatibility. Conceptual queries ("something for biryani") are handled by the
  **AI assistant** (`docs/ASSISTANT.md`), not by this engine.
- **Not the DRF `?search=` filter.** `ProductViewSet` also exposes
  `filters.SearchFilter` over `name`/`description`/`ingredients` for plain
  catalog filtering. That is a database `icontains` — no synonyms, no fuzzy
  matching, no ranking. The AI engine is `/api/search/`.
- **Not personalized.** Ranking depends only on the query. Per-user
  recommendations are a separate system (`products/personalization.py`,
  `GET /api/recommendations/`, `docs/RECOMMENDATIONS.md`).
- **No LLM call at query time.** Worth repeating: search latency is independent
  of the LLM provider's availability and pricing.

---

## 16. Tuning guide

| Symptom | Lever |
|---|---|
| Too many loose matches | Raise `threshold` (default 70) or `SEARCH_THRESHOLD_MIN` |
| A known synonym doesn't work | Add it to `COMMON_BOOSTS`, then `populate_search_kb --force` |
| A generic word matches everything | Add it to `GENERIC_BLOCKLIST` |
| Synonyms outrank real names | Lower the `synonym` weight in `KIND_WEIGHTS` |
| Autocomplete feels unstable while typing | It's prefix-first by design; check pass 2's `score_cutoff=75` |
| Corpus stale after a bulk DB change | `populate_search_kb --force` (signals never fired) |
| Corpus entry shape changed | Bump `v2` in `get_search_corpus_key()` |
| Autocomplete 429s in normal use | Raise the `search_suggest` throttle in `settings.py` (currently 60/min) |
| Search slow on a large catalog | Corpus scan is O(n) per query — profile `build_search_corpus`, consider trigram/`pg_trgm` prefiltering |

---

## 17. Test coverage

| Test | Location | Asserts |
|---|---|---|
| `TestSynonymCleaning` | `products/tests.py` | junk filtering, 30-term cap, deterministic terms include name/token/category/weight and exclude bare `500g` |
| `TestSearchCorpus` | `products/tests.py` | KB-less product still matchable; corpus cache invalidation |
| `TestSearchRanking` | `products/tests.py` | Hinglish (`jiravan`, `haldi`), typo (`tumeric`), regional (`mirchi`), weight-qualified (`haldi 500g`), exact name outranks synonyms, KB-less found by name, junk query → 0 direct matches, 2-char query doesn't return the catalog |
| `TestRankAndDedupe` | `products/tests.py` | weight applied exactly once; direct always outranks fallback |
| no-results contract | `products/test_admin_and_seo.py` | `"zzzzqqqxyzzy"` returns no products/combos; recommendations appear under `suggestions` only |
| query-length abuse | `spices_backend/test_limits_and_abuse.py` | `q` over `MAX_SEARCH_Q` → 400 |

The `search_catalog` fixture disconnects `auto_update_product_on_save` before
seeding and reconnects it in a `finally`, and clears the locmem cache — the
in-process cache survives between tests and would otherwise leak stale product
IDs into the corpus.

Run from `Backend/` (which owns `pytest.ini`):

```bash
cd Backend && venv/Scripts/python.exe -m pytest -q products/tests.py
```

---

## 18. Environment variables

```env
# Synonym generation (also used by the AI assistant unless overridden)
LLM_API_KEY=sk-or-v1-...          # provider API key
MODEL_PROVIDER=openrouter          # LangChain provider name
LLM_MODEL=minimax/minimax-m2.5     # model for synonym generation

# Optional: a separate (stronger) model for the shopping assistant
ASSISTANT_MODEL_PROVIDER=openrouter
ASSISTANT_LLM_MODEL=openai/gpt-4o-mini

# Query limits (spices_backend/limits.py — all optional, defaults shown)
MAX_SEARCH_Q=200
SEARCH_TOP_K_MAX=100
SEARCH_THRESHOLD_MIN=0
SEARCH_THRESHOLD_MAX=100

# Cache TTLs (settings.py)
CACHE_TTL_MEDIUM=300               # suggest responses
CACHE_TTL_LONG=900                 # search corpus
```

If `LLM_API_KEY` is absent, synonym generation falls back to deterministic terms
and the assistant returns a polite fallback reply — the storefront keeps working.

---

## 19. SEO: sitemap & robots

`products/sitemaps.py` serves `GET /sitemap.xml` (catalog-driven: active
products, combos, categories, plus static routes) and `GET /robots.txt` (points
crawlers at the sitemap; keeps cart/billing/profile out of the index). Both are
wired at the **site root** in `spices_backend/urls.py` and proxied there by
nginx — previously the SPA catch-all swallowed `/sitemap.xml` and served
`index.html`.

---

## Related docs

- `docs/ASSISTANT.md` — AI shopping assistant (reuses `build_suggestions`)
- `docs/RECOMMENDATIONS.md` — per-user personalized recommendations
- `docs/ANALYTICS.md` — search term rollups and the Insights API
- `docs/CACHING_STRATEGY.md` — Redis strategy across the backend
- `docs/MULTILINGUAL.md` — translation setup
- `docs/API.md` — full endpoint map
