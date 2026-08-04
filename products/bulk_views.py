"""Admin-only bulk product tools: export, spreadsheet-style bulk edit, and a
validated CSV import for prices & stock.

All three speak the SAME small vocabulary — a product identified by its id (or,
for import, its exact name) plus optional `price`, `discount_price`, `stock` —
so the frontend can drive edit and import through one apply path.

Everything here is staff-only and read/write on Product (and, when a change names
a `variant_id`, that product's ProductVariant size row). No raw SQL: each
change is a validated ORM update inside a transaction (all-or-nothing).
"""
import csv
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
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


def _resolve_variant(product, size, line_no):
    """Return (variant, error) for a CSV row: the named size, or the default.

    A blank `size` means "the default size" — that is what a sheet written
    before variants existed meant, and it keeps old sheets importable. An
    unmatched size is an error rather than a silent fallback, because quietly
    repricing the wrong packaging is worse than refusing the row.
    """
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
                'low_stock_threshold', 'hsn_code', 'tax_rate')
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
            'variants': variants_by_product.get(p['id'], []),
        })
    return Response(rows)


@api_view(['POST'])
@permission_classes([IsStaff])
def bulk_products_apply(request):
    """Apply a batch of price/stock changes, all-or-nothing.

    Body: {"changes": [{"id": 3, "price": "120", "stock": 40}, …]}
    A change may also carry "variant_id" — then the named SIZE of that product is
    updated instead of the legacy product-level fields.
    Only the keys present on each change are updated. Validates every row first;
    if ANY row is invalid nothing is saved and the errors are returned.
    """
    changes = request.data.get('changes')
    if not isinstance(changes, list) or not changes:
        return Response({'error': 'Send {"changes": [{"id": …, "price"/"discount_price"/"stock": …}, …]}.'},
                        status=status.HTTP_400_BAD_REQUEST)

    ids = [c.get('id') for c in changes if isinstance(c, dict)]
    products = {p.id: p for p in Product.objects.filter(id__in=ids)}
    variant_ids = [c.get('variant_id') for c in changes
                   if isinstance(c, dict) and c.get('variant_id')]
    variants = {v.id: v for v in ProductVariant.objects.filter(id__in=variant_ids)}

    errors = []
    updates = []  # (instance, {field: value})
    for i, change in enumerate(changes):
        if not isinstance(change, dict) or 'id' not in change:
            errors.append({'row': i, 'error': 'Missing product id.'})
            continue
        product = products.get(change['id'])
        if product is None:
            errors.append({'row': i, 'id': change.get('id'), 'error': 'Product not found.'})
            continue
        # Resolve the edit target: a specific size, or the product itself.
        target = product
        if change.get('variant_id'):
            target = variants.get(change['variant_id'])
            if target is None or target.product_id != product.id:
                errors.append({'row': i, 'id': product.id,
                               'error': 'Size not found for this product.'})
                continue
        fields = {}
        if 'price' in change:
            value, err = _parse_decimal(change['price'])
            if err:
                errors.append({'row': i, 'id': product.id, 'error': f"Price {err}."})
            elif value is not None:
                fields['price'] = value
        if 'discount_price' in change:
            value, err = _parse_decimal(change['discount_price'])
            if err:
                errors.append({'row': i, 'id': product.id, 'error': f"Discounted price {err}."})
            else:
                fields['discount_price'] = value  # may be None to clear
        if 'stock' in change:
            value, err = _parse_int(change['stock'])
            if err:
                errors.append({'row': i, 'id': product.id, 'error': f"Stock {err}."})
            elif value is not None:
                fields['stock'] = value
        if fields:
            updates.append((target, fields))
        # HSN is a property of the GOODS, not of a packaging size — a 100g and a
        # 500g pack of the same masala are the same tariff line. So it is always
        # written to the Product even when the row targets a variant, and it gets
        # its own update entry rather than joining `fields`.
        if 'hsn_code' in change:
            value, err = _parse_hsn(change['hsn_code'])
            if err:
                errors.append({'row': i, 'id': product.id, 'error': f"HSN code: {err}"})
            else:
                updates.append((product, {'hsn_code': value}))

    if errors:
        return Response({'applied': 0, 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

    # Lock the rows while writing so an absolute stock value can't clobber a
    # checkout's concurrent decrement mid-save (checkout locks the same rows).
    with transaction.atomic():
        locked = {}
        for model in (Product, ProductVariant):
            model_ids = [o.id for o, _ in updates if isinstance(o, model)]
            if model_ids:
                locked[model] = model.objects.select_for_update().filter(
                    id__in=model_ids).in_bulk()
        for obj, fields in updates:
            row = locked.get(type(obj), {}).get(obj.id)
            if row is None:  # deleted since validation
                continue
            for field, value in fields.items():
                setattr(row, field, value)
            row.save(update_fields=list(fields.keys()))

    return Response({'applied': len(updates), 'errors': []})


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

    # One lookup of names → product (exact, case-insensitive).
    name_col = normalised['name']
    size_col = normalised.get('size')
    rows_out = []
    ok_count = 0
    hsn_seen = {}  # product id -> code already taken from an earlier row
    for line_no, raw_row in enumerate(reader, start=2):  # row 1 is the header
        name = (raw_row.get(name_col) or '').strip()
        if not name:
            continue  # skip blank lines silently
        product = Product.objects.filter(name__iexact=name).first()
        if product is None:
            rows_out.append({'name': name, 'id': None, 'changes': {},
                             'error': f"Row {line_no}: no product named '{name}'."})
            continue

        # Resolve which SIZE this row edits.
        size = (raw_row.get(size_col) or '').strip() if size_col else ''
        variant, size_error = _resolve_variant(product, size, line_no)
        if size_error:
            rows_out.append({'name': name, 'size': size, 'id': product.id,
                             'variant_id': None, 'changes': {}, 'error': size_error})
            continue

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
            if err:
                row_error = f"Row {line_no}: {field.replace('_', ' ')} {err}."
                break
            if value is not None or (field == 'discount_price' and (raw or '').strip() != ''):
                changes[field] = str(value) if value is not None else ''
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
