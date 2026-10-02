# Multilingual Support

The storefront supports 6 languages across two independent layers:

| Layer | Tool | What it translates |
|-------|------|--------------------|
| **UI strings** | `i18next` (frontend) | Labels, buttons, placeholders, static copy |
| **Catalog content** | `django-modeltranslation` (backend) | Product/category names, descriptions, ingredients, reviews |

These layers are independent — you can add a UI translation without touching the DB, and vice versa.

---

## Supported Languages

| Code | Language | Script |
|------|----------|--------|
| `en` | English | Latin (default) |
| `hi` | Hindi | Devanagari |
| `hinglish` | Hinglish | Latin (Hindi phonetics) |
| `gu` | Gujarati | Gujarati |
| `mr` | Marathi | Devanagari |
| `pa` | Punjabi | Gurmukhi |

The canonical list lives in two places that must stay in sync:
- **Backend**: `MODELTRANSLATION_LANGUAGES` in `spices_backend/settings.py`
- **Frontend**: `SUPPORTED_LANGUAGES` in `src/i18n/index.ts`

---

## Layer 1 — UI Strings (i18next)

UI-only text (nav labels, button copy, form placeholders, error messages) is handled by
`i18next`. Translation files live at:

```
Frontend/nidhi-brand-forge/src/i18n/locales/
├── en.json
├── hi.json
├── hinglish.json
├── gu.json
├── mr.json
└── pa.json
```

The selected language is stored in `localStorage` under the key `site_lang` and is
automatically read by i18next on every page load. To add or update a UI string, edit the
relevant key in every locale file. English (`en.json`) is the fallback — missing keys in
other locales silently render the English value.

---

## Layer 2 — Catalog Content (django-modeltranslation)

### How it works

`django-modeltranslation` adds per-language database columns for every registered field.
For example, `Product.name` becomes:

```
name_en   (the English source, also the fallback)
name_hi
name_hinglish
name_gu
name_mr
name_pa
```

The abstract `name` attribute on the model returns the column for the currently active
language, falling back to `name_en` if the language-specific column is empty.
**Empty translations never show a blank — they always show English.**

### Registered models and fields

| Model | Translated fields |
|-------|------------------|
| `Product` | `name`, `description`, `ingredients`, `origin_country` |
| `Category` | `name`, `description` |
| `ProductCombo` | `name`, `title`, `description` |
| `Review` | `title`, `comment` |

Registration files: `products/translation.py`, `reviews/translation.py`.

### How the request language is selected

`LanguageQueryMiddleware` (`spices_backend/middleware.py`) activates the correct language
for each request. It reads, in order:

1. `?lang=<code>` query parameter
2. `X-Language` request header

Unknown or missing values leave the Django default (`en`) active. The middleware deactivates
the language after the response so it never leaks between requests.

The middleware also adds `Vary: X-Language` to every response so the browser (and any
CDN/reverse-proxy) stores a separate cache entry per language. Without this header the
HTTP cache ignores the `X-Language` request header and returns a stale-language response
for previously-visited URLs.

The **frontend** sends the active `site_lang` value as an `X-Language` header with every
authenticated API request (set in `lib/api/config.ts → getLangHeader()`). Public fetch
calls also include it. This means API responses (product names, descriptions, category
names) automatically come back in the selected language.

---

## Workflows

### 1. Adding a new product

No translation work required. Enter English values in the Django admin. All language columns
default to empty, which transparently falls back to English. Translations can be added later.

### 2. Machine-translating catalog content

The `translate_content` management command calls the configured LLM (OpenRouter) to fill
empty per-language columns. It is idempotent — already-translated fields are skipped unless
`--force` is given.

```bash
# Preview what would be translated (no writes, no LLM calls)
python manage.py translate_content --dry-run

# Translate all gaps across all models and languages
python manage.py translate_content

# Translate only Hindi and Gujarati for products
python manage.py translate_content --models product --langs hi,gu

# Re-translate everything (overwrite existing translations)
python manage.py translate_content --force

# Rate-limit friendly: pause 0.5s between LLM calls
python manage.py translate_content --sleep 0.5
```

**Name vs description behaviour:** fields named `name` or `title` are *transliterated* (the
brand stays recognizable); all other fields are fully translated. This is controlled by
`NAME_FIELDS` in the command.

After running `translate_content`, **refresh the search KB** so the new language content is
indexed:

```bash
python manage.py populate_search_kb --force
```

### 3. Applying curated translations

Human-reviewed translations for the original catalog are stored in:

```
Backend/products/fixtures/curated_translations.json
```

This fixture covers **products, categories, combos and reviews** — each keyed by
primary key, with full (not summarised) translations of names, titles,
descriptions and ingredients. The loader's `MODEL_MAP` maps the `products`,
`categories`, `combos` and `reviews` sections to their models.

Apply them with:

```bash
python manage.py load_curated_translations          # apply
python manage.py load_curated_translations --dry-run  # preview
```

This is safe to re-run — it uses `.update()` directly on the DB columns, bypassing model
`save()` and image-validation logic. Newer products not in the fixture are unaffected.

After loading, refresh the search KB:

```bash
python manage.py populate_search_kb --force
```

### 4. Adding a new translatable field to an existing model

1. Add the field to the model in `models.py`.
2. Register it in the model's `translation.py`:
   ```python
   @register(Product)
   class ProductTranslationOptions(TranslationOptions):
       fields = ('name', 'description', 'ingredients', 'origin_country', 'new_field')
   ```
3. Run migrations — `makemigrations` will generate columns for every language:
   ```bash
   python manage.py makemigrations products
   python manage.py migrate
   ```
4. Fill translations via `translate_content` or manually in the admin.
5. Refresh the search KB if the field is search-relevant.

### 5. Adding a new language

This touches five places:

**Backend:**

1. Add to `LANGUAGES` and `MODELTRANSLATION_LANGUAGES` in `spices_backend/settings.py`:
   ```python
   LANGUAGES = [
       ...
       ('te', 'Telugu'),
   ]
   MODELTRANSLATION_LANGUAGES = ('en', 'hi', 'hinglish', 'gu', 'mr', 'pa', 'te')
   ```
2. Run `makemigrations` + `migrate` to generate the new `*_te` columns.
3. Run `translate_content --langs te` to fill content.
4. Run `populate_search_kb --force` to index the new language.

**Frontend:**

5. Add to `SUPPORTED_LANGUAGES` in `src/i18n/index.ts`:
   ```typescript
   { code: 'te', label: 'తెలుగు' },
   ```
6. Create `src/i18n/locales/te.json` with UI string translations.

---

## Search KB and Multilingual Content

The AI search corpus (`ngu:search:corpus:v1`) includes translated product and category
names from all language columns. This means a user searching in Hindi or Gujarati matches
against the translated `name_hi` / `name_gu` values as well as LLM-generated synonyms in
those languages.

**Any time translations change, refresh the KB:**

```bash
python manage.py populate_search_kb --force
```

Changes made via the Django admin trigger `post_save` signals that auto-refresh the KB
entry for the affected product in a background thread. Changes made via direct SQL or
`load_curated_translations` do **not** trigger signals — always run `populate_search_kb`
manually after those.

---

## AI Assistant Language

The shopping assistant (`POST /api/assistant/chat/`) reads the `X-Language` header and
replies in the same language. The language codes passed by the frontend match the
`MODELTRANSLATION_LANGUAGES` codes exactly. No additional configuration is needed — the
assistant prompt instructs the LLM to respond in the detected language.

---

## Common Mistakes

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| Bulk SQL update to product names without running `populate_search_kb` | Search corpus is stale — searches hit old names | Run `populate_search_kb --force` |
| Adding a new language to `MODELTRANSLATION_LANGUAGES` without migrating | Server crash on boot | Run `makemigrations` + `migrate` |
| Forgetting to add the language code to the frontend `SUPPORTED_LANGUAGES` | Language picker doesn't show it; `X-Language` never sent for it | Add to `src/i18n/index.ts` |
| Running `translate_content` without `LLM_API_KEY` set | Command exits with error | Set `LLM_API_KEY` in env, or use `--dry-run` to verify config first |
| Editing `curated_translations.json` and not reloading | Fixture and DB are out of sync | Run `load_curated_translations` |
| Removing `patch_vary_headers` from `LanguageQueryMiddleware` | Browser/CDN caches one language and returns it for all subsequent requests to the same URL — products appear "stuck" in English | Keep `Vary: X-Language` in the middleware |
