# Availability gaps — fix plan (2026-10-02)

**Status:** implemented 2026-10-02 (working tree, NOT deployed). All of Step 0 and
Gaps 1–7 are done with the tests named in each step green; `llm.py` was left
untouched per §1.2.
**Scope:** gaps 1–7 from the 2026-10-02 audit. Gap 8 (hard deletes through the Django
admin) is **excluded by the owner** — do not touch it.
**Written for:** whoever implements this. Every gap below was reproduced with a test
before this plan was written, so the "today" behaviour described is observed, not guessed.

All seven gaps are one problem seen from different sides: **something is switched off,
retired or sold out, and one part of the system has not been told.** So the plan starts
with one shared set of availability rules (Step 0) and makes every surface read from it.

---

## 1. Read this before changing anything

1. **Never run anything against production** (`nidhigrahudyog.com`, `34.0.5.162`). Use the
   local recipe in `.claude/skills/verify/SKILL.md`. Never source `Backend/.env.local`.
2. **The working tree already holds uncommitted work. Do not revert, reformat or commit it.**
   - Storefront, someone else's work in progress: `Frontend/nidhi-brand-forge/src/pages/Cart.tsx`,
     `src/context/CartContext.tsx`, `src/components/Navbar.tsx`, `FloatingWhatsApp.tsx`,
     `UspRibbon.tsx`, `src/i18n/locales/{en,hi,hinglish}.json`. This plan edits `Cart.tsx`,
     `CartContext.tsx` and the locale files — **build on what is there**, change only the
     lines this plan names.
   - `Backend/spices_backend/llm.py`: do not touch, do not commit (see `CLAUDE.md`).
   - The size / combo / recycle-bin work from 2026-10-02 (also uncommitted). This plan
     depends on it: `ProductCombo.available_stock`, `products/combo_membership.py`,
     `admin_panel/recycle.py`.
3. **Line numbers are "about here" markers.** Find the quoted code by searching for it.
4. **Many backend files use CRLF line endings.** Edit them in place; do not rewrite whole files.
5. **Run backend tests from `Backend/`:** `venv/Scripts/python.exe -m pytest -q`.
   Four failures are known and unrelated — two SQLite concurrency tests
   (`orders/test_concurrency.py` G4/G5) and two in `assistant/test_chat_limits.py` caused by
   the local `.env`. Any other failure is yours.
6. **Do not** change order money maths, GST allocation, invoice or stock-decrement logic
   beyond the single checks named below. **Do not** expose exact stock counts to
   non-staff (rule AP8/S12 — the public gets booleans only).
7. **Every new user-facing string** goes into all locale files: storefront has six
   (`en, hi, hinglish, gu, mr, pa` under `Frontend/nidhi-brand-forge/src/i18n/locales/`),
   the admin panel has two (`en`, `hi` under `Admin Panel/e-commerce-command-center/src/i18n/locales/`).
8. **Keep `Backend/docs/API.md` current** — every changed response field or status code
   gets its row updated in the same change.
9. Leave the changes uncommitted and undeployed unless the owner says otherwise.

---

## 2. Decisions for the owner

Each has a default. The plan is written for the default; if the owner picks otherwise,
the affected step says what changes.

| # | Question | Default (plan assumes this) | Alternative |
|---|---|---|---|
| D1 | Hiding a category that still has active products | **Refuse**, and say which products are in it. Move or switch them off first. Same pattern as retiring a size. | (a) Hiding the category takes all its products off the shop. (b) Allow it; products stay on sale with no shelf. |
| D2 | A cart contains a line that can no longer be bought | **Block checkout** until the line is removed; offer one "Remove unavailable items" button. | Place the order for the remaining lines only. Not recommended: it changes order creation. |
| D3 | Which low-stock alert level applies to a size | **The product's level applies to each of its sizes.** It is the only level the panel lets the owner set. | Make each size's own level editable in the product form. |
| D4 | A combo whose component is sold out | **Show it as "Out of stock"**, add-to-cart disabled. | Hide it from the shop until it can be built again. |
| D5 | Reviews of a switched-off product | **Hidden from shoppers** (home page and review lists) until the product is back. Admin still sees them. | Leave them visible. |

---

## 3. Step 0 — one place that answers "can this be bought?"

Create **`Backend/products/availability.py`**. Nothing else in the plan may re-derive
these rules; every step below calls these helpers.

| Helper | Returns | Rule |
|---|---|---|
| `in_stock_products(qs)` | the queryset, filtered | product has at least one size with `is_active=True` and `stock > 0`. Implement with `Exists(ProductVariant.objects.filter(product=OuterRef('pk'), is_active=True, stock__gt=0))` — a subquery, not a join, so it cannot multiply rows. |
| `product_has_stock(product)` | bool | same rule for one instance. Use `product.variants.all()` so an existing `prefetch_related('variants')` is reused. If the product has **no size rows at all** (legacy), fall back to `product.stock > 0`. |
| `combo_can_be_built(combo, quantity=1)` | bool | `combo.is_active and combo.available_stock >= quantity`. `available_stock` already returns 0 for a retired size, a switched-off component product, or an empty combo. |
| `line_problem(cart_item)` | `None` or a reason code | see table below |
| `line_max_quantity(cart_item)` | int | size stock for a product line (legacy line without a size: `product.stock`); `combo.available_stock` for a combo |
| `low_stock_sizes()` / `out_of_stock_sizes()` | `ProductVariant` querysets | see Gap 4 |

Reason codes for `line_problem` — checked in this order, first match wins:

| Code | When |
|---|---|
| `product_off` | product line and `product.is_active` is False |
| `size_retired` | product line with a size and `variant.is_active` is False |
| `combo_off` | combo line and `combo.is_active` is False |
| `combo_unavailable` | combo line and `combo.available_stock == 0` (covers retired size, switched-off component, empty combo, sold-out component) |
| `out_of_stock` | `line_max_quantity == 0` |
| `insufficient_stock` | `0 < line_max_quantity < cart_item.quantity` |

Tests: new `Backend/products/test_availability.py`, one test per row of both tables.

---

## 4. The gaps

### Gap 7 — the cart does not flag lines that cannot be bought *(do this first; Gaps 1 and 2 build on it)*

**Today:** a switched-off product, a retired size, or an unbuildable combo sits in the cart
reported as `in_stock: true`. The customer learns at checkout.

**Useful fact:** the storefront cart page **already** handles this. `Cart.tsx` splits lines
into `inStockItems` / `outOfStockItems` on `item.inStock === false`, greys the unavailable
ones and leaves them out of the totals. The server simply never sends `false` for these
cases. Most of this gap is therefore a backend fix.

Backend — `Backend/cart/serializers.py`, `CartItemResponseSerializer`:

1. Add two fields: `available` (bool) and `unavailable_reason` (a code from Step 0, or `null`).
2. `get_in_stock` returns `False` whenever `line_problem(obj)` is not `None`. This alone
   makes the existing storefront grey the line out, even before the frontend changes ship.
3. `get_stock` returns `line_max_quantity(obj)`. Today a combo reports a hard-coded `999`.
4. `CartResponseSerializer.get_summary`: compute `subtotal`, `tax` and the tax breakdown
   from **available lines only**, and add `unavailable_count`. Today it uses
   `cart.total_price`, which includes lines the customer cannot buy, and `Billing.tsx`
   renders this summary. Do not change any formula — only which lines are fed in.
5. `get_items` and `get_summary` call `select_related(...)`. Extend it so `line_problem`
   costs no extra query per line: add `variant__product`, and
   `prefetch_related('combo__productcomboitem_set__variant', 'combo__productcomboitem_set__product')`.

Storefront:

6. `src/context/CartContext.tsx`: add `unavailable_reason` to the API item type and
   `unavailableReason` to the mapped cart line (the mapping is the function that already
   sets `inStock: item.in_stock ?? true`).
7. `src/pages/Cart.tsx`, `renderLine`: the unavailable badge currently always shows
   `t('product.outOfStock')`. Show a message chosen by `unavailableReason`
   (new keys `cart.unavailable.product_off`, `.size_retired`, `.combo_off`,
   `.combo_unavailable`, `.out_of_stock`, `.insufficient_stock`), falling back to
   `product.outOfStock`.
8. Same file: add a **"Remove unavailable items"** button above the unavailable group. It
   calls the existing remove function for each unavailable line.
9. Same file, **D2**: `checkoutDisabled` is currently
   `isVerifying || inStockItems.length === 0`. Add `|| outOfStockItems.length > 0`, and
   show one line of help text ("Remove the unavailable items to continue"). Apply the same
   condition inside `handleCheckout` after the fresh cart is fetched.
10. `src/pages/Billing.tsx`: on load, if the cart summary has `unavailable_count > 0`,
    send the customer back to `/cart` with a toast. Billing must never be the place they
    discover it.
11. `src/components/FloatingCartBar.tsx` sums every line (`cart.reduce(...)`). Sum only
    lines with `inStock !== false`, so the bar agrees with the cart page.

Check, don't assume: `remove_item` in `Backend/cart/views.py` looks lines up by product /
combo id without an `is_active` filter, so removing an unavailable line should already
work. `update_item` does filter on `is_active` and answers "Cart item not found" for such
a line — that is acceptable (the only valid action is remove), but add a test that
**remove works** for each reason code.

*If D2 = "order the remaining lines":* skip items 9 and 10, and in `OrderViewSet.create`
skip lines where `line_problem` is set instead of returning 400. That path also has to
leave the skipped lines in the cart afterwards. Do not attempt it without the owner's yes.

Tests (`Backend/cart/tests.py` or a new `cart/test_availability.py`): one per reason code
asserting `available`, `unavailable_reason`, `in_stock`; summary excludes the line;
remove works.

---

### Gap 1 — a retired size still in a cart can be ordered

**Today:** `OrderViewSet.create` (`Backend/orders/views.py`) checks `item.is_active` for a
product line but never `variant.is_active`. An order for a retired size is **accepted**.

1. In the product branch of the cart loop (search for the comment
   `G1: never sell a delisted/inactive product`), directly after the `item.is_active`
   check, refuse a retired size:
   `{'error': f'{item_name} ({variant.formatted_weight}) is no longer available'}`, status 400.
   Better: replace both hand-written checks in this loop with one call to
   `line_problem(cart_item)` and map the code to the existing message wording, so cart
   and checkout can never disagree. The combo branch already performs the equivalent
   checks; keep its messages.
2. Inside the transaction, where sizes are re-read under a row lock (search for
   `ProductVariant.objects.select_for_update().filter(pk__in=variant_updates.keys())`),
   add to the existing loop: if `not variant.is_active`, `raise ValueError(...)` with the
   same message. This is the same pattern the "Insufficient stock" check two lines below
   uses; the `except ValueError` at the end of the method turns it into a 400 and the
   transaction rolls back. It closes the race where a size is retired between the first
   check and the lock.
3. Do not touch the legacy branch (`variant is None`).

Tests (`Backend/orders/test_checkout_and_ops.py`): retired size in cart → 400, no `Order`
row created, stock unchanged; the same cart with the size active → 201.

Docs: correct the `ProductVariantViewSet.destroy` docstring and the API.md row. They
already claim customers "hit 'no longer available' at checkout", which only becomes true
with this fix.

---

### Gap 2 — combos never show as unavailable before checkout

**Today:** every combo is treated as stock `999`. A combo with a sold-out or retired
component can be added to the cart, shows as in stock, and the public combo payload has
no availability field at all. Only checkout refuses.

Backend:

1. `Backend/cart/views.py` — three places use `getattr(item, 'stock', 999)` for combos
   (`add_item`, `update_item`, `sync`). Replace each with `line_max_quantity` /
   `combo.available_stock`. When it is 0, answer 400 "This combo is currently unavailable";
   otherwise keep the existing "Only N units available" wording.
2. `Backend/cart/models.py` — `CartItem.available_stock` and `CartItem.clean` carry the
   same `999`. Same replacement.
3. Public availability flag — add a boolean **`in_stock`** (never the count: AP8/S12) to:
   - `ProductComboSerializer` (`Backend/products/serializers.py`), public field
   - `SectionComboSerializer` and `SearchComboSerializer` (same file)
   - `_combo_public` in `Backend/assistant/tools.py` (hard-codes `'in_stock': True`, with
     a comment saying to revisit once combos track component stock — this is that moment)
   - `_proposal_stock_ok` in the same file, so the assistant stops proposing a combo
     that cannot be built
   - `tool_search` in the same file skips combos entirely when `in_stock is True` is
     requested; include the buildable ones instead.
4. **Query cost.** `available_stock` walks `productcomboitem_set` with each line's size
   and product. Wherever combos are serialized in bulk, add both prefetches
   (`productcomboitem_set__variant`, `productcomboitem_set__product`):
   - `ProductSection.get_combos` in `Backend/products/models.py` (has the size prefetch only)
   - `_fuzzy_search_all` and `build_suggestions` in `Backend/products/recommendations.py`
     (the latter uses `.only(...)` — keep the columns it lists and add the prefetch)
   - `ComboProductViewSet.get_queryset` already has both.
   Add an `assertNumQueries` / `django_assert_num_queries` test on `GET /api/combos/` and
   `GET /api/products/sections/` with 3+ combos to prove there is no per-combo query.
5. **Known and accepted:** the public combo list is cached for five minutes, and checkout
   lowers stock with `bulk_update`, which fires no signal. A combo can therefore show as
   in stock for up to five minutes after its last unit sells. The server still refuses at
   add-to-cart and at checkout. Product `in_stock` has the same lag today. Do not try to
   fix the cache here.

Storefront — treat a missing `in_stock` as `true` (older cached payloads):

6. `src/lib/api/combos.ts`: add `in_stock?: boolean` to the combo type.
7. Disable add-to-cart and show the existing `product.outOfStock` label when
   `combo.in_stock === false` in: `components/ComboCard.tsx`, `components/ComboStoryCard.tsx`,
   `pages/ComboDetail.tsx` (two add buttons — main and sticky bar), `pages/OfferZone.tsx`,
   and any add control in `pages/Combos.tsx`.

*If D4 = "hide":* instead of item 7, filter `in_stock === false` combos out of the lists,
and keep the detail page showing "Out of stock" for direct links.

Tests: add / update / sync refuse an unbuildable combo; public combo payload carries
`in_stock` false for sold-out, retired-size and switched-off-component cases and true
otherwise; non-staff payload still has no `available_stock`
(`products/test_catalog_privacy.py` must keep passing).

---

### Gap 3 — search, recommendations and "in stock" look at the default size only

**Today:** all of these read `Product.stock`, which is a mirror of the **default** size.
Reproduced: default size sold out, 500 g with 40 in stock → the product vanished from
search and suggestions, and the product list said `in_stock: false`.

Backend — replace every "default size only" read with the Step 0 helpers:

| File | Where | Change |
|---|---|---|
| `products/recommendations.py` | four querysets filtering `stock__gt=0` (in `build_suggestions`, `_fuzzy_search_all`, and twice in `_other_recommendations`) | drop `stock__gt=0`, wrap with `in_stock_products(...)` |
| `products/personalization.py` | three querysets filtering `stock__gt=0` (`recommend`, and twice in `_fallback_queryset`) | same |
| `products/models.py` | `Product.in_stock` property (`return self.stock > 0`) | return `product_has_stock(self)`. Import inside the method to avoid a circular import. |
| `products/serializers.py` | `SearchProductSerializer.get_in_stock` (reads `obj.stock`) | `product_has_stock(obj)`; make sure its callers `prefetch_related('variants')` |
| `products/signals.py` | `if instance.is_active and instance.stock > 0:` (decides whether to refresh search keywords) | use `product_has_stock(instance)` |
| `assistant/tools.py` | `'in_stock': p.stock > 0`; `pq.filter(stock__gt=0)`; `_proposal_stock_ok` fallback | helpers |

`ProductListSerializer` / `ProductDetailSerializer` expose `in_stock` through the model
property and their viewsets already prefetch `variants`, so they pick the fix up for free.
**Prove it with a query-count test on `GET /api/products/`** — the property must not add
a query per product.

Storefront:

1. `src/pages/ProductDetail.tsx`, where the first size is chosen (the block using
   `productData.selected_variant_id` then `vs.find((v) => v.is_default)`): new order of
   preference — the size named in the URL; else the default size **if it is in stock**;
   else the first in-stock size; else the default. Otherwise the page opens on a sold-out
   size while another is available.
2. Same file, sticky bottom bar: it uses `product.in_stock` for both the label and the
   button's `disabled`. Change both to `effectiveInStock` (already computed above for the
   main button). Once `product.in_stock` means "any size", leaving this would enable the
   button for a sold-out selected size.
3. `src/components/ProductCard.tsx` receives no stock information, so a sold-out
   single-size product still shows an active add button. Add an optional `inStock` prop
   (default `true`), pass `in_stock` from every place that renders the card — there are
   six: `pages/Products.tsx`, `pages/ProductDetail.tsx` (similar products),
   `components/ProductCarousel.tsx` (home-page sections), `pages/Favorites.tsx`,
   `pages/SearchResults.tsx`, `pages/OfferZone.tsx` — and disable the button with the
   out-of-stock label when false. Where the data feeding a card has no `in_stock` field
   (favourites, home sections), add it to that backend payload as a boolean rather than
   guessing on the client. Multi-size products keep linking to the detail page.

**Out of scope, note only:** the price shown on a card is still the default size's price
even when that size is sold out. Mention it to the owner; do not change pricing display here.

Tests (`Backend/products/test_search_suggest.py` and a personalization test): default
sold out + another size stocked → present in suggest, search and recommendations with
`in_stock: true`; all sizes sold out → absent; a **retired** size with stock does not count.

---

### Gap 4 — low-stock reporting looks at the default size only

**Today:** dashboard, daily digest, weekly summary and the admin assistant all use
`Product.objects.filter(is_active=True, stock__lte=F('low_stock_threshold'))`. Reproduced:
500 g down to 1 unit, default size at 50 → low-stock count 0.

**Rule (D3):** a size is low when `stock <= its product's low_stock_threshold`. The
product form's "Low-stock alert level" is the only level the owner can set; a size's own
`low_stock_threshold` column is not editable anywhere in the panel and is 5 everywhere.

Step 0 helpers:
- `low_stock_sizes()` → `ProductVariant.objects.filter(is_active=True, product__is_active=True, stock__lte=F('product__low_stock_threshold')).select_related('product').order_by('stock')`
- `out_of_stock_sizes()` → same base, `stock__lte=0`

| File | Where | Change |
|---|---|---|
| `admin_panel/views.py` | `low_stock_qs` / `low_stock_items` in the dashboard actions | `low_stock_count` = number of **distinct products** with at least one low size (so it matches the Products page filter the dashboard links to). `low_stock_items` = the five lowest **sizes**, each `{id: product id, variant_id, name, size, stock}`. |
| `admin_panel/views.py` | `out_of_stock_count` | distinct products with at least one size at 0 |
| `admin_panel/management/commands/send_daily_digest.py` | `low = list(Product.objects.filter(...))` and the `"{name} — {stock} left"` line | sizes; print `"{name} ({size}) — {stock} left"` |
| `admin_panel/management/commands/send_weekly_summary.py` | same pattern | same |
| `assistant/admin_tools.py` | `admin_low_stock` | sizes; add `size` to each row; `count` = distinct products |
| `orders/views.py` | checkout low-stock alert: `threshold = variant.low_stock_threshold` | use the product's level. Fetch the levels for the affected products in **one** query before the loop (a dict `product_id → low_stock_threshold`); do not lazy-load `variant.product` inside the locked loop. Change nothing else there. |

Admin panel:
- `src/api/dashboard.ts`: add `size?: string` and `variant_id?: number` to `LowStockItem`.
- `src/pages/Dashboard.tsx`: where `low_stock_items` names are joined, show `name (size)`.
- `src/pages/Products.tsx`: `sizeIsLow` currently prefers the size's own level
  (`v.low_stock_threshold ?? p.low_stock_threshold ?? 5`). Make it
  `p.low_stock_threshold ?? 5` so the list, the filter and the dashboard agree.

Existing tests that will break and must be updated, not deleted: `admin_panel/tests.py`
sets `test_product.stock = 3` directly (the mirror column) in the dashboard and digest
tests. Set the **size's** stock instead (`default_variant_for(test_product.pk)`).

New tests: a non-default size low while the default is healthy → counted and named with
its size; a retired size at 0 → not counted; a switched-off product → not counted.

*If D3 = "each size has its own level":* add the field to the size rows in the product
form and to the `syncVariants` payload, use `F('low_stock_threshold')` in the helpers, and
back-fill existing sizes from their product's level with a `--dry-run` command.

---

### Gap 5 — a hidden category's products stay on sale

**Today:** hiding a category 404s the category page, but its products stay in the product
list, in search, and `?category=<id>` still returns them. The panel tells the admin the
category "is no longer shown in the store", which is only half true.

**Default (D1): refuse to hide a category that still has active products.**

Backend — `Backend/products/views.py`, `CategoryViewSet`:

1. `destroy`: before setting `is_active = False`, look for active products whose
   **primary** category is this one (`Product.objects.filter(category=instance, is_active=True)`).
   If any exist → **409** with
   `{'detail': '"<name>" still has N active product(s): A, B, C… Move them to another category or switch them off first.', 'count': N, 'products': [up to 10 names]}`.
2. Add `perform_update` with the same check when `is_active` goes from True to False
   (raise `ValidationError`, as `ProductVariantViewSet.perform_update` does). The panel's
   show/hide toggle uses PATCH, so `destroy` alone is not enough.
3. `extra_categories` (secondary shelves) do **not** block hiding — the product still has
   its primary shelf.

Make already-hidden categories consistent (rows that exist today, or are changed outside
the panel):

4. `ProductFilter.filter_category` (same file): for non-staff (`self.request.user`),
   return `queryset.none()` when the category is inactive.
5. `build_search_corpus` in `products/recommendations.py`: only add the category name as
   a search term (`add(product.category.name, …, 'category')`) when the category is active.
6. `_other_recommendations` in the same file: `Category.objects.filter(name__icontains=query)`
   → add `is_active=True`.

Admin panel — `src/pages/Categories.tsx`: `handleHide` has a bare `catch` that shows the
generic `categories.hideFailed`. Show the server's message (`error.message`, already
extracted by the axios interceptor) so the admin sees which products are in the way. Do
the same in the show/hide toggle handler.

Owner aid, read-only: give the owner a shell one-liner (in the hand-over notes, not a new
endpoint) listing categories that are already hidden while holding active products, so
they can be tidied by hand.

*If D1 = (a) "hide its products too":* skip items 1–3. Instead exclude products whose
primary category is inactive from every public surface — product list and detail,
sections, search corpus, recommendations, sitemap — and make `line_problem` return a new
`category_off` code so cart and checkout refuse them. This is a much larger change and
puts whole shelves of products off sale with one click; get an explicit yes first.

Tests: hide with active products → 409 and still active; hide after moving them → 204;
PATCH path → 400; public `?category=<hidden>` → empty; staff still see it.

---

### Gap 6 — reviews of switched-off products still show to shoppers

**Today:** `GET /api/reviews/featured/` (the home-page testimonial strip) and the public
review list return reviews whose product or combo is switched off. The home page can
link to a product that no longer exists for shoppers.

Backend — `Backend/reviews/views.py`:

1. Define one filter and reuse it:
   `Q(item_type='product', product__is_active=True) | Q(item_type='combo', combo__is_active=True)`.
2. `featured`: apply it to `visible`. The existing top-up logic then fills the freed
   slot, so the strip still shows three.
3. `get_queryset`: apply it for non-staff — but a customer must still see **their own**
   reviews, as with hidden ones: `(is_hidden=False AND item is active) OR user=<me>`.
   Staff see everything.
4. `set_featured`: refuse to feature a review whose item is switched off (400), next to
   the existing "a hidden review can't be featured" check.
5. Nothing is deleted or modified: the reviews come back the moment the product does.
   Rating averages need no change (a switched-off product is not listed).

Tests (`Backend/reviews/tests.py`): featured strip skips the off product's review and
still returns up to three; public list omits it; author still sees it; staff still see
it; back on → visible again.

*If D5 = "leave visible":* skip this gap.

---

## 5. Order of work

Each step leaves the test suite green on its own.

1. **Step 0** — helpers and their tests. No behaviour change yet.
2. **Gap 7** — backend, then storefront.
3. **Gap 1.**
4. **Gap 2** — backend, then storefront.
5. **Gap 3** — backend, then storefront.
6. **Gap 4.**
7. **Gap 6.**
8. **Gap 5** — last, because it is the one whose default the owner is most likely to change.

No database migration is expected. Confirm with
`manage.py makemigrations --check --dry-run`; if it wants one, a model was changed that
should not have been.

---

## 6. Proving it works

**Backend:** full suite from `Backend/`; only the four known failures remain.

**Frontends:** in each of `Frontend/nidhi-brand-forge` and
`Admin Panel/e-commerce-command-center`: `npx tsc --noEmit -p tsconfig.app.json` and
`npx vite build`. In the panel, errors under `src/components/ui/` about missing modules
are pre-existing.

**In a browser** (local stack per `.claude/skills/verify/SKILL.md`; seed one product with
three sizes, one single-size product, and one combo) — every row must be seen, not assumed:

| # | Do this | Must see |
|---|---|---|
| 1 | Put a 500 g pack in the cart, then retire that size in the panel | Cart shows the line greyed with a "this size is no longer sold" message; checkout is blocked; "Remove unavailable items" clears it |
| 2 | Force the same order through the API | 400, no order, stock unchanged |
| 3 | Set one combo component's stock to 0 | Combo shows "Out of stock" on the combo list, detail page and home sections; add-to-cart refused |
| 4 | Sell out the default size, leave another stocked | Product appears in search and suggestions; product page opens on the in-stock size; the sold-out size is marked |
| 5 | Take a non-default size below the alert level | Dashboard counts it and names it with its size; `manage.py send_daily_digest` lists it |
| 6 | Hide a category that has active products | Refused, products named; after moving them, hiding works |
| 7 | Feature a review, then switch its product off | It leaves the home-page strip; switch the product on and it returns |
| 8 | Switch a product off while it is in a cart | Cart flags it and blocks checkout |

---

## 7. Not in this plan

- Gap 8 — hard deletes through the Django admin (`Product.category` and `Order.user`
  cascade). Excluded by the owner.
- Prices: nothing here changes what anything costs or which price a card displays.
- The five-minute cache lag on public `in_stock` flags (Gap 2, item 5).
- Deployment. When it is deployed, both frontends and the backend must ship together:
  the storefront reads new fields (`in_stock` on combos, `unavailable_reason` on cart
  lines) and treats them as optional, so backend-first is safe; storefront-first is not
  harmful but shows no improvement.

When done, move the seven entries under "Gaps of the same kind found 2026-10-02" in
`CLAUDE.md` from "NOT fixed" to fixed, each with a one-line pointer to where the rule lives.
