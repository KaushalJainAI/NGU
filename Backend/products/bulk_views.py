"""Admin-only bulk product tools: export, spreadsheet-style bulk edit, and a
validated CSV import for prices & stock.

All three speak the SAME small vocabulary — a product identified by its id (or,
for import, its exact name) plus optional `price`, `discount_price`, `stock` —
so the frontend can drive edit and import through one apply path.

Everything here is staff-only. Price and stock are written to the ProductVariant
(size) row — the one checkout prices and stocks from — never to the Product's
own columns, which only mirror the default size. `hsn_code` alone is written to
the Product. No raw SQL: each change is a validated ORM update inside a
transaction (all-or-nothing).
"""
import csv
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models.functions import Lower
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .hsn import (
    CHAPTERS, HSN_REFERENCE, RATES_AS_OF, RATES_SOURCE, describe,
    validate_hsn_code,
)
from .models import Product, ProductVariant


class IsStaff(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


# Columns the import understands. Matching is case-insensitive.
# `hsn_code` is PRODUCT-level, unlike the other three which belong to a size —
# see the note in bulk_products_import about why that matters when a sheet has
# several rows for the same product.
_IMPORT_FIELDS = ('price', 'discount_price', 'stock', 'hsn_code')

# Most rows one request may carry, for both the edit grid and the CSV import.
# The 5 MB upload limit alone allows ~100k rows, and apply() holds a
# select_for_update on every row it touches inside ONE transaction — the same
# rows checkout locks to decrement stock. A mis-saved spreadsheet could
# therefore stall the shop rather than merely being slow. 5000 is far past any
# real catalogue (a few hundred products x their sizes) and still bounded.
MAX_BULK_ROWS = 5000


def _as_id(value):
    """Coerce a primary key to int, or None if it isn't one.

    Ids arrive from JSON, so a client can send `"abc"` or `null`. Passing that
    to `filter(id__in=…)` raises ValueError from deep inside the ORM and DRF
    renders it as a 500; a bad id belongs in the per-row error list instead.
    Booleans are rejected explicitly — `int(True)` is 1, which would silently
    edit product 1.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_variant(product, size, line_no, actives=None):
    """Return (variant, error) for a CSV row: the named size, or the default.

    A blank `size` means "the default size" — that is what a sheet written
    before variants existed meant, and it keeps old sheets importable. An
    unmatched size is an error rather than a silent fallback, because quietly
    repricing the wrong packaging is worse than refusing the row.

    `actives` lets the caller pass the product's active sizes in, since an import
    sheet lists one row PER SIZE and would otherwise re-run this query once for
    every row of the same product.
    """
    if actives is None:
        actives = list(ProductVariant.objects.filter(product=product, is_active=True)
                       .order_by('display_order', 'weight'))
    if not actives:
        return None, f"Row {line_no}: '{product.name}' has no active size to update."

    if not size:
        default = next((v for v in actives if v.is_default), actives[0])
        return default, None

    wanted = size.strip().lower().replace(' ', '')
    for variant in actives:
        if (variant.formatted_weight or '').lower().replace(' ', '') == wanted:
            return variant, None

    available = ', '.join(v.formatted_weight or '?' for v in actives)
    return None, (f"Row {line_no}: '{product.name}' has no size '{size}'. "
                  f"Available: {available}.")


def _parse_decimal(raw):
    # Values may arrive as JSON numbers (from the edit grid) or strings (from a
    # CSV cell), so coerce to string before trimming.
    raw = ('' if raw is None else str(raw)).strip()
    if raw == '':
        return None, None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None, f"'{raw}' is not a valid number"
    if not value.is_finite():  # reject NaN / Infinity before comparison
        return None, f"'{raw}' is not a valid number"
    if value < 0:
        return None, "cannot be negative"
    return value, None


def _parse_int(raw):
    raw = ('' if raw is None else str(raw)).strip()
    if raw == '':
        return None, None
    try:
        parsed = Decimal(raw)
        if not parsed.is_finite():  # NaN / Infinity → int() would overflow
            raise InvalidOperation
        value = int(parsed)  # tolerate "10.0"
    except (InvalidOperation, ValueError, OverflowError):
        return None, f"'{raw}' is not a whole number"
    if value < 0:
        return None, "cannot be negative"
    return value, None


def _parse_hsn(raw):
    """Validate an HSN cell. Returns (value, error); '' clears the code.

    Blank is a legitimate value here — it means "not classified yet" — so unlike
    price/stock an empty cell WRITES rather than being skipped. That is what
    makes a CSV round-trip able to un-set a code an admin decided was wrong.
    """
    raw = ('' if raw is None else str(raw)).strip()
    # Excel loves to turn 0910 into 910; pad a 3/5/7-digit number back rather
    # than rejecting a sheet that is only wrong because a spreadsheet ate a zero.
    if raw.isdigit() and len(raw) in (3, 5, 7):
        raw = '0' + raw
    try:
        validate_hsn_code(raw)
    except DjangoValidationError as exc:
        return None, exc.messages[0]
    return raw, None


@api_view(['GET'])
@permission_classes([IsStaff])
def hsn_reference(request):
    """The curated HSN code list, with the statutory GST rate for each.

    Powers the admin panel's HSN picker. It is REFERENCE DATA, not policy: the
    panel shows `gst_rate` next to whatever `Product.tax_rate` is actually set
    to and flags a difference, but nothing here ever writes a rate. See the
    module docstring in products/hsn.py for why that boundary is deliberate.

    `rates_as_of` / `rates_source` are returned so the UI can date-stamp the
    figures — they are a snapshot of published rates, not a live feed.
    """
    return Response({
        'rates_as_of': RATES_AS_OF,
        'rates_source': RATES_SOURCE,
        'chapters': CHAPTERS,
        'codes': [
            {
                'code': row['code'],
                'description': row['description'],
                'gst_rate': float(row['gst_rate']),
                'chapter': row['code'][:2],
                'note': row['note'],
                'keywords': row['keywords'],
            }
            for row in HSN_REFERENCE
        ],
    })


@api_view(['GET'])
@permission_classes([IsStaff])
def hsn_coverage(request):
    """Which active products still have no HSN code, and which look mis-rated.

    Two lists, both of which the admin has to act on before a return is filed:

    * `unclassified` — no code at all. Every sale of these lands in the
      "NOT CLASSIFIED" row of the HSN summary.
    * `rate_mismatch` — a code IS set, but the rate charged differs from the
      rate published for that code. Reported, never auto-corrected: the rate is
      the owner's decision (and sometimes legitimately differs, e.g. a blend the
      CA has placed under 21039040 while the code still reads 09109100). The
      point is that it stops being invisible.
    """
    unclassified, mismatched = [], []
    for product in Product.objects.filter(is_active=True).order_by('name').only(
            'id', 'name', 'hsn_code', 'tax_rate'):
        if not product.hsn_code:
            unclassified.append({'id': product.id, 'name': product.name,
                                 'tax_rate': float(product.tax_rate or 0)})
            continue
        ref = describe(product.hsn_code)
        if ref and Decimal(str(product.tax_rate or 0)) != ref['gst_rate']:
            mismatched.append({
                'id': product.id,
                'name': product.name,
                'hsn_code': product.hsn_code,
                'tax_rate': float(product.tax_rate or 0),
                'expected_rate': float(ref['gst_rate']),
                'description': ref['description'],
                'note': ref['note'],
            })
    return Response({
        'rates_as_of': RATES_AS_OF,
        'unclassified': unclassified,
        'rate_mismatch': mismatched,
        'unclassified_count': len(unclassified),
        'rate_mismatch_count': len(mismatched),
    })


@api_view(['GET'])
@permission_classes([IsStaff])
def bulk_products(request):
    """GET the flat editable product table for the bulk editor.

    Returns id, name, category, current price/discount/stock — everything the
    spreadsheet grid shows. Unpaginated: the admin edits the whole catalog.
    """
    products = (
        Product.objects.select_related('category')
        .order_by('name')
        .values('id', 'name', 'price', 'discount_price', 'stock',
                'low_stock_threshold', 'hsn_code', 'tax_rate', 'is_active')
    )
    # category_name via a light second pass to avoid a values() join surprise.
    cat_names = dict(
        Product.objects.select_related('category').values_list('id', 'category__name')
    )
    # Sizes (variants) per product, so the grid can offer a size dropdown and
    # edit that size's own price/stock instead of the legacy product-level ones.
    variants_by_product = {}
    for v in ProductVariant.objects.filter(is_active=True).order_by(
            'product_id', 'display_order', 'weight'):
        variants_by_product.setdefault(v.product_id, []).append({
            'id': v.id,
            'label': v.formatted_weight or 'Default size',
            'price': str(v.price) if v.price is not None else '',
            'discount_price': str(v.discount_price) if v.discount_price is not None else '',
            'stock': v.stock,
            'low_stock_threshold': v.low_stock_threshold,
            'is_default': v.is_default,
        })

    rows = []
    for p in products:
        rows.append({
            'id': p['id'],
            'name': p['name'],
            'category_name': cat_names.get(p['id']) or '',
            'price': str(p['price']) if p['price'] is not None else '',
            'discount_price': str(p['discount_price']) if p['discount_price'] is not None else '',
            'stock': p['stock'],
            'low_stock_threshold': p['low_stock_threshold'],
            # Product-level, so it sits outside `variants` — every size of a
            # product shares one HSN code and one GST rate.
            'hsn_code': p['hsn_code'] or '',
            'tax_rate': str(p['tax_rate']) if p['tax_rate'] is not None else '',
            # So the grid can mark a product that is switched off / in the bin.
            'is_active': p['is_active'],
            'variants': variants_by_product.get(p['id'], []),
        })
    return Response(rows)


@api_view(['POST'])
@permission_classes([IsStaff])
def bulk_products_apply(request):
    """Apply a batch of price/stock changes, all-or-nothing.

    Body: {"changes": [{"id": 3, "variant_id": 9, "price": "120", "stock": 40}, …]}
    `variant_id` names the SIZE to edit. Without it the change lands on the
    product's default size (what a pre-variant client meant). `hsn_code` is the
    one product-level field and is always written to the product.
    Only the keys present on each change are updated. Validates every row first;
    if ANY row is invalid nothing is saved and the errors are returned, each
    carrying the `id`/`variant_id` it belongs to so the grid can mark the row.
    """
    changes = request.data.get('changes')
    if not isinstance(changes, list) or not changes:
        return Response({'error': 'Send {"changes": [{"id": …, "price"/"discount_price"/"stock": …}, …]}.'},
                        status=status.HTTP_400_BAD_REQUEST)
    if len(changes) > MAX_BULK_ROWS:
        return Response(
            {'error': f'Too many changes in one request ({len(changes)}; max '
                      f'{MAX_BULK_ROWS}). Apply them in smaller batches.'},
            status=status.HTTP_400_BAD_REQUEST)

    # Ids are coerced BEFORE they reach the ORM — see `_as_id`. A row whose id
    # doesn't coerce simply matches nothing and is reported as "Product not
    # found" below, which is what it is from the admin's point of view.
    ids = [pk for pk in (_as_id(c.get('id')) for c in changes if isinstance(c, dict))
           if pk is not None]
    products = {p.id: p for p in Product.objects.filter(id__in=ids)}
    variant_ids = [pk for pk in (_as_id(c.get('variant_id')) for c in changes
                                 if isinstance(c, dict) and c.get('variant_id'))
                   if pk is not None]
    variants = {v.id: v for v in ProductVariant.objects.filter(id__in=variant_ids)}
    # Default size per product, for a change that names no size. One query for
    # the whole batch; the flagged default wins, else the first active size.
    default_variants = {}
    for v in ProductVariant.objects.filter(
            product_id__in=list(products), is_active=True
    ).order_by('product_id', '-is_default', 'display_order', 'weight'):
        default_variants.setdefault(v.product_id, v)

    errors = []
    # Keyed by target so two changes to the same row merge into ONE write
    # (later values win) instead of locking and saving it twice.
    size_updates = {}     # variant id -> (variant, {field: value})
    hsn_updates = {}      # product id -> (product, code)
    for i, change in enumerate(changes):
        if not isinstance(change, dict) or 'id' not in change:
            errors.append({'row': i, 'error': 'Missing product id.'})
            continue
        product = products.get(_as_id(change['id']))
        if product is None:
            errors.append({'row': i, 'id': change.get('id'), 'error': 'Product not found.'})
            continue

        def fail(message, variant=None):
            errors.append({'row': i, 'id': product.id,
                           'variant_id': getattr(variant, 'id', None),
                           'name': product.name, 'error': message})

        # HSN is a property of the GOODS, not of a packaging size — a 100g and a
        # 500g pack of the same masala are the same tariff line. So it is always
        # written to the Product even when the row targets a variant.
        if 'hsn_code' in change:
            value, err = _parse_hsn(change['hsn_code'])
            if err:
                fail(f"HSN code: {err}")
            else:
                hsn_updates[product.id] = (product, value)

        if not any(f in change for f in ('price', 'discount_price', 'stock')):
            continue

        # Price and stock live on a SIZE. A change that names one edits it; a
        # change that names none edits the product's default size — never the
        # product's own columns, which only mirror the default size and are
        # overwritten by the next size save (signals._mirror_default_variant).
        if change.get('variant_id'):
            target = variants.get(_as_id(change['variant_id']))
            if target is None or target.product_id != product.id:
                fail('Size not found for this product.')
                continue
        else:
            target = default_variants.get(product.id)
            if target is None:
                fail(f"'{product.name}' has no active size to update. Add or "
                     f"re-activate a size in the product form first.")
                continue

        size = target.formatted_weight
        where = f"{product.name} ({size})" if size else product.name
        _, fields = size_updates.get(target.id, (target, {}))
        fields = dict(fields)
        bad = False
        if 'price' in change:
            value, err = _parse_decimal(change['price'])
            if err:
                fail(f"{where}: price {err}.", target)
                bad = True
            elif value is not None:
                if value <= 0:
                    fail(f"{where}: price must be more than 0.", target)
                    bad = True
                else:
                    fields['price'] = value
        if 'discount_price' in change:
            value, err = _parse_decimal(change['discount_price'])
            if err:
                fail(f"{where}: discounted price {err}.", target)
                bad = True
            else:
                # Blank and 0 both mean "no discount".
                fields['discount_price'] = value or None
        if 'stock' in change:
            value, err = _parse_int(change['stock'])
            if err:
                fail(f"{where}: stock {err}.", target)
                bad = True
            elif value is not None:
                fields['stock'] = value
        if bad:
            continue

        # Cross-field rule, checked against what the row will hold AFTER this
        # change — raising the price or clearing the discount can each make a
        # previously invalid pair valid, and vice versa.
        price = fields.get('price', target.price)
        discount = fields['discount_price'] if 'discount_price' in fields \
            else target.discount_price
        if discount is not None and price is not None and discount >= price:
            fail(f"{where}: discounted price ₹{discount} must be less than the "
                 f"price ₹{price}.", target)
            continue
        if fields:
            size_updates[target.id] = (target, fields)

    if errors:
        return Response({'applied': 0, 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

    # Lock the rows while writing so an absolute stock value can't clobber a
    # checkout's concurrent decrement mid-save (checkout locks the same rows).
    applied = 0
    try:
        with transaction.atomic():
            locked_sizes = ProductVariant.objects.select_for_update().filter(
                id__in=list(size_updates)).in_bulk() if size_updates else {}
            for variant_id, (_, fields) in size_updates.items():
                row = locked_sizes.get(variant_id)
                if row is None:  # removed since validation
                    continue
                for field, value in fields.items():
                    setattr(row, field, value)
                row.save(update_fields=list(fields.keys()))
                applied += 1

            locked_products = Product.objects.select_for_update().filter(
                id__in=list(hsn_updates)).in_bulk() if hsn_updates else {}
            for product_id, (_, code) in hsn_updates.items():
                row = locked_products.get(product_id)
                if row is None:
                    continue
                row.hsn_code = code
                row.save(update_fields=['hsn_code'])
                applied += 1
    except DjangoValidationError as exc:
        # Product.save() runs full_clean(), so an unrelated bad column on an old
        # row can refuse the save. Nothing was committed; say which and why
        # rather than surfacing a bare "Validation error".
        detail = '; '.join(exc.messages) if getattr(exc, 'messages', None) else str(exc)
        return Response(
            {'applied': 0,
             'errors': [{'row': None, 'error': f'Nothing was saved. {detail}'}]},
            status=status.HTTP_400_BAD_REQUEST)

    return Response({'applied': applied, 'errors': []})


@api_view(['POST'])
@permission_classes([IsStaff])
@parser_classes([MultiPartParser, FormParser])
def bulk_products_import(request):
    """Parse an uploaded CSV of price/stock updates and return a validated
    PREVIEW — it does NOT save. The frontend shows the preview, then applies the
    accepted rows via bulk_products_apply.

    Expected columns (case-insensitive; extra columns ignored):
      - `name` (required) — must match a product name exactly
      - `size` (optional) — which packaging the row edits, e.g. "500g". Matched
        against the variant's formatted weight. Omit it and the row targets the
        product's DEFAULT size, which is what a pre-variant sheet meant.
      - any of `price`, `discount_price`, `stock` — these belong to the SIZE
      - `hsn_code` (optional) — belongs to the PRODUCT, so it is taken from the
        first row mentioning each product and later rows must agree

    Every emitted change carries a `variant_id`, so applying it writes the SIZE
    row that checkout actually prices and stocks from. Writing the legacy
    product-level columns instead would look like it worked and then be silently
    overwritten by the next variant save (see signals._mirror_default_variant).

    Response: {"rows": [{name, size, id, variant_id, changes, error}],
               "ok_count", "error_count"}.
    """
    upload = request.FILES.get('file')
    if not upload:
        return Response({'error': 'No file uploaded (expected multipart field "file"). Save your sheet as CSV from Excel.'},
                        status=status.HTTP_400_BAD_REQUEST)
    if upload.size > 5 * 1024 * 1024:
        return Response({'error': 'File too large (max 5 MB).'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        text = upload.read().decode('utf-8-sig')  # tolerate Excel BOM
    except UnicodeDecodeError:
        return Response({'error': 'Could not read the file. Please save it as CSV (UTF-8) from Excel and try again.'},
                        status=status.HTTP_400_BAD_REQUEST)

    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        return Response({'error': 'The file is empty.'}, status=status.HTTP_400_BAD_REQUEST)

    # Map the sheet's headers (any case/spacing) to our known field names.
    normalised = {(h or '').strip().lower(): h for h in reader.fieldnames}
    if 'name' not in normalised:
        return Response({'error': 'The file must have a "name" column matching your product names.'},
                        status=status.HTTP_400_BAD_REQUEST)
    present_fields = [f for f in _IMPORT_FIELDS if f in normalised]
    if not present_fields:
        return Response({'error': 'The file must have at least one of these columns: price, discount_price, stock, hsn_code.'},
                        status=status.HTTP_400_BAD_REQUEST)

    name_col = normalised['name']
    size_col = normalised.get('size')

    # Materialise the sheet first so the row count can be checked before any
    # database work: 5 MB of CSV is ~100k rows, and the loop below used to run a
    # name lookup (plus a variant lookup) for every one of them.
    sheet = [(line_no, raw_row) for line_no, raw_row
             in enumerate(reader, start=2)  # row 1 is the header
             if (raw_row.get(name_col) or '').strip()]
    if len(sheet) > MAX_BULK_ROWS:
        return Response(
            {'error': f'Too many rows ({len(sheet)}; max {MAX_BULK_ROWS}). '
                      f'Split the sheet and import it in parts.'},
            status=status.HTTP_400_BAD_REQUEST)

    # ONE lookup of names → product (exact, case-insensitive), instead of a query
    # per row. Ordering matches Product.Meta (`-created_at`) and the first hit per
    # name wins, so a duplicated product name still resolves to the same row
    # `filter(name__iexact=…).first()` used to return.
    wanted_names = {(raw_row.get(name_col) or '').strip().lower() for _, raw_row in sheet}
    products_by_name = {}
    for product in Product.objects.annotate(_lname=Lower('name')).filter(
            _lname__in=wanted_names):
        products_by_name.setdefault(product._lname, product)

    # Active sizes per product, filled lazily — a sheet lists one row per size,
    # so without this each product is re-queried once per size it sells in.
    actives_by_product = {}

    rows_out = []
    ok_count = 0
    hsn_seen = {}  # product id -> code already taken from an earlier row
    seen_sizes = {}  # variant id -> sheet row that first named it
    for line_no, raw_row in sheet:
        name = (raw_row.get(name_col) or '').strip()
        product = products_by_name.get(name.lower())
        if product is None:
            rows_out.append({'name': name, 'id': None, 'changes': {},
                             'error': f"Row {line_no}: no product named '{name}'."})
            continue

        # Resolve which SIZE this row edits.
        size = (raw_row.get(size_col) or '').strip() if size_col else ''
        if product.id not in actives_by_product:
            actives_by_product[product.id] = list(
                ProductVariant.objects.filter(product=product, is_active=True)
                .order_by('display_order', 'weight'))
        variant, size_error = _resolve_variant(product, size, line_no,
                                               actives=actives_by_product[product.id])
        if size_error:
            rows_out.append({'name': name, 'size': size, 'id': product.id,
                             'variant_id': None, 'changes': {}, 'error': size_error})
            continue

        # The same size on two rows is a slip of the spreadsheet, and applying
        # both would quietly keep whichever came last. Refuse the repeat.
        first_line = seen_sizes.get(variant.id)
        if first_line is not None:
            rows_out.append({
                'name': name, 'size': variant.formatted_weight or '',
                'id': product.id, 'variant_id': variant.id, 'changes': {},
                'error': f"Row {line_no}: '{product.name}' "
                         f"{variant.formatted_weight or 'default size'} is already "
                         f"on row {first_line}. Keep one row per size."})
            continue
        seen_sizes[variant.id] = line_no

        changes = {}
        row_error = None
        for field in present_fields:
            raw = raw_row.get(normalised[field])
            if field == 'hsn_code':
                # Product-level, but the sheet has one row PER SIZE — so a
                # masala sold in 100g/250g/500g repeats its code three times.
                # Take the first row for each product and validate (but ignore)
                # the rest, rather than queueing three identical writes to the
                # same Product row. A later row disagreeing with the first is a
                # data-entry error and is reported as one.
                value, err = _parse_hsn(raw)
                if err:
                    row_error = f"Row {line_no}: HSN code: {err}"
                    break
                if (raw or '').strip() == '':
                    continue
                seen = hsn_seen.get(product.id)
                if seen is None:
                    hsn_seen[product.id] = value
                    changes['hsn_code'] = value
                elif seen != value:
                    row_error = (f"Row {line_no}: HSN code '{value}' conflicts with "
                                 f"'{seen}' given for '{product.name}' on an earlier "
                                 f"row. One product has one HSN code.")
                    break
                continue
            if field == 'stock':
                value, err = _parse_int(raw)
            else:
                value, err = _parse_decimal(raw)
            if not err and field == 'price' and value is not None and value <= 0:
                err = 'must be more than 0'
            if err:
                row_error = f"Row {line_no}: {field.replace('_', ' ')} {err}."
                break
            if value is not None or (field == 'discount_price' and (raw or '').strip() != ''):
                changes[field] = str(value) if value is not None else ''
        # Same cross-field rule bulk_products_apply enforces, checked here so the
        # preview is truthful: a row shown as "ready" must actually apply.
        if not row_error:
            price = Decimal(changes['price']) if 'price' in changes else variant.price
            if 'discount_price' in changes:
                discount = Decimal(changes['discount_price']) if changes['discount_price'] else None
            else:
                discount = variant.discount_price
            if discount and price is not None and discount >= price:
                row_error = (f"Row {line_no}: discounted price ₹{discount} must be "
                             f"less than the price ₹{price}.")
        label = variant.formatted_weight or ''
        if row_error:
            rows_out.append({'name': name, 'size': label, 'id': product.id,
                             'variant_id': variant.id, 'changes': {}, 'error': row_error})
        elif not changes:
            rows_out.append({'name': name, 'size': label, 'id': product.id,
                             'variant_id': variant.id, 'changes': {},
                             'error': f"Row {line_no}: nothing to change."})
        else:
            # variant_id rides along in `changes` so the frontend can hand the
            # row straight to bulk_products_apply unmodified.
            changes['variant_id'] = variant.id
            rows_out.append({'name': name, 'size': label, 'id': product.id,
                             'variant_id': variant.id, 'changes': changes, 'error': None})
            ok_count += 1

    return Response({
        'rows': rows_out,
        'ok_count': ok_count,
        'error_count': len(rows_out) - ok_count,
    })


@api_view(['GET'])
@permission_classes([IsStaff])
def export_products_csv(request):
    """Download the full catalog as CSV (for editing in Excel, then re-importing).

    ONE ROW PER SIZE, not per product — price and stock belong to the variant, so
    a product-level row could not represent a catalogue with multiple packagings
    and would re-import onto the wrong one. The `size` column round-trips back
    through bulk_products_import.
    """
    from admin_panel.utils import csv_response
    from django.utils import timezone

    # `hsn_code` and `tax_rate` are product-level and therefore repeat on every
    # size row of the same product. That redundancy is deliberate: the sheet is
    # the spreadsheet an admin does the classification exercise in, and having
    # to scroll to find the one row carrying the code would be worse. The import
    # takes the first occurrence per product and rejects disagreement.
    # `tax_rate` is exported for reference only — the import does not write it,
    # because changing what is charged belongs in the product form where the
    # statutory rate for the code is shown next to it.
    header = ['name', 'size', 'category', 'price', 'discount_price', 'stock',
              'low_stock_threshold', 'active', 'hsn_code', 'tax_rate']

    def rows():
        variants = (
            ProductVariant.objects
            .select_related('product', 'product__category')
            .order_by('product__name', 'display_order', 'weight')
        )
        for v in variants:
            p = v.product
            yield [
                p.name,
                v.formatted_weight or '',
                p.category.name if p.category else '',
                v.price if v.price is not None else '',
                v.discount_price if v.discount_price is not None else '',
                v.stock,
                v.low_stock_threshold,
                # A size is sellable only if BOTH the product and the size are
                # active, so that is what 'active' has to mean here.
                'yes' if (p.is_active and v.is_active) else 'no',
                p.hsn_code or '',
                p.tax_rate if p.tax_rate is not None else '',
            ]

    return csv_response(f"products-{timezone.now().strftime('%Y%m%d')}.csv", header, rows())
