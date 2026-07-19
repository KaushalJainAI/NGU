"""Admin-only bulk product tools: export, spreadsheet-style bulk edit, and a
validated CSV import for prices & stock.

All three speak the SAME small vocabulary — a product identified by its id (or,
for import, its exact name) plus optional `price`, `discount_price`, `stock` —
so the frontend can drive edit and import through one apply path.

Everything here is staff-only and read/write on Product only. No raw SQL: each
change is a validated ORM update inside a transaction (all-or-nothing).
"""
import csv
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .models import Product


class IsStaff(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


# Columns the import understands. Matching is case-insensitive.
_IMPORT_FIELDS = ('price', 'discount_price', 'stock')


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
        .values('id', 'name', 'price', 'discount_price', 'stock', 'low_stock_threshold')
    )
    # category_name via a light second pass to avoid a values() join surprise.
    cat_names = dict(
        Product.objects.select_related('category').values_list('id', 'category__name')
    )
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
        })
    return Response(rows)


@api_view(['POST'])
@permission_classes([IsStaff])
def bulk_products_apply(request):
    """Apply a batch of price/stock changes, all-or-nothing.

    Body: {"changes": [{"id": 3, "price": "120", "stock": 40}, …]}
    Only the keys present on each change are updated. Validates every row first;
    if ANY row is invalid nothing is saved and the errors are returned.
    """
    changes = request.data.get('changes')
    if not isinstance(changes, list) or not changes:
        return Response({'error': 'Send {"changes": [{"id": …, "price"/"discount_price"/"stock": …}, …]}.'},
                        status=status.HTTP_400_BAD_REQUEST)

    ids = [c.get('id') for c in changes if isinstance(c, dict)]
    products = {p.id: p for p in Product.objects.filter(id__in=ids)}

    errors = []
    updates = []  # (product, {field: value})
    for i, change in enumerate(changes):
        if not isinstance(change, dict) or 'id' not in change:
            errors.append({'row': i, 'error': 'Missing product id.'})
            continue
        product = products.get(change['id'])
        if product is None:
            errors.append({'row': i, 'id': change.get('id'), 'error': 'Product not found.'})
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
                errors.append({'row': i, 'id': product.id, 'error': f"Discount price {err}."})
            else:
                fields['discount_price'] = value  # may be None to clear
        if 'stock' in change:
            value, err = _parse_int(change['stock'])
            if err:
                errors.append({'row': i, 'id': product.id, 'error': f"Stock {err}."})
            elif value is not None:
                fields['stock'] = value
        if fields:
            updates.append((product, fields))

    if errors:
        return Response({'applied': 0, 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

    # Lock the rows while writing so an absolute stock value can't clobber a
    # checkout's concurrent decrement mid-save (checkout locks the same rows).
    with transaction.atomic():
        update_ids = [p.id for p, _ in updates]
        locked = Product.objects.select_for_update().filter(id__in=update_ids).in_bulk()
        for product, fields in updates:
            target = locked.get(product.id)
            if target is None:  # deleted since validation
                continue
            for field, value in fields.items():
                setattr(target, field, value)
            target.save(update_fields=list(fields.keys()))

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
      - any of `price`, `discount_price`, `stock`

    Response: {"rows": [{name, id, changes, error}], "ok_count", "error_count"}.
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
        return Response({'error': 'The file must have at least one of these columns: price, discount_price, stock.'},
                        status=status.HTTP_400_BAD_REQUEST)

    # One lookup of names → product (exact, case-insensitive).
    name_col = normalised['name']
    rows_out = []
    ok_count = 0
    for line_no, raw_row in enumerate(reader, start=2):  # row 1 is the header
        name = (raw_row.get(name_col) or '').strip()
        if not name:
            continue  # skip blank lines silently
        product = Product.objects.filter(name__iexact=name).first()
        if product is None:
            rows_out.append({'name': name, 'id': None, 'changes': {},
                             'error': f"Row {line_no}: no product named '{name}'."})
            continue

        changes = {}
        row_error = None
        for field in present_fields:
            raw = raw_row.get(normalised[field])
            if field == 'stock':
                value, err = _parse_int(raw)
            else:
                value, err = _parse_decimal(raw)
            if err:
                row_error = f"Row {line_no}: {field.replace('_', ' ')} {err}."
                break
            if value is not None or (field == 'discount_price' and (raw or '').strip() != ''):
                changes[field] = str(value) if value is not None else ''
        if row_error:
            rows_out.append({'name': name, 'id': product.id, 'changes': {}, 'error': row_error})
        elif not changes:
            rows_out.append({'name': name, 'id': product.id, 'changes': {},
                             'error': f"Row {line_no}: nothing to change."})
        else:
            rows_out.append({'name': name, 'id': product.id, 'changes': changes, 'error': None})
            ok_count += 1

    return Response({
        'rows': rows_out,
        'ok_count': ok_count,
        'error_count': len(rows_out) - ok_count,
    })


@api_view(['GET'])
@permission_classes([IsStaff])
def export_products_csv(request):
    """Download the full catalog as CSV (for editing in Excel, then re-importing)."""
    from admin_panel.utils import csv_response
    from django.utils import timezone

    header = ['name', 'category', 'price', 'discount_price', 'stock', 'low_stock_threshold', 'active']

    def rows():
        for p in Product.objects.select_related('category').order_by('name'):
            yield [
                p.name,
                p.category.name if p.category else '',
                p.price if p.price is not None else '',
                p.discount_price if p.discount_price is not None else '',
                p.stock,
                p.low_stock_threshold,
                'yes' if p.is_active else 'no',
            ]

    return csv_response(f"products-{timezone.now().strftime('%Y%m%d')}.csv", header, rows())
