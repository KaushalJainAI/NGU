"""Sale-price update, 2026-10 (see PRICING_STRATEGY.md section 5b).

Run through `manage.py shell` so it works against any environment without a
rebuild. DRY RUN by default - it prints what it would do and writes nothing.

    # on the server, from the stack directory - preview:
    docker exec -i ngu-backend python manage.py shell < price_update_2026_10.py
    # apply:
    docker exec -e APPLY=1 -i ngu-backend python manage.py shell < price_update_2026_10.py

    # locally on Windows (from Backend/) - Django's shell does not read a piped
    # stdin on win32, so exec the file instead:
    venv/Scripts/python.exe manage.py shell -c "exec(open('../price_update_2026_10.py', encoding='utf-8').read())"

Only `discount_price` (the sale price) is written; MRP is printed on the pack
and is left alone. Price lives on ProductVariant - the Product columns are a
display mirror the variant signal keeps in sync, so each variant is saved (not
.update()'d) to fire that signal and bust the caches.

The plan is keyed on the variant ids read from the live catalogue on
2026-10-01. Every row is guarded: the variant must still belong to the expected
product, be the expected pack size, and carry the sale price the plan was
written against. Anything that fails a guard is SKIPPED and reported, never
guessed at. FORCE=1 waives the current-price guard only.

Combos are not touched: a combo carries its own sale price.
"""
import json
import os
from decimal import Decimal

from django.db import transaction

from products.models import ProductVariant

APPLY = os.environ.get('APPLY') == '1'
FORCE = os.environ.get('FORCE') == '1'

# (variant id, product id, pack size in grams, sale price the plan assumed, new sale price)
PLAN = [
    # Blends and seasonings
    (1,  32, 100,  79,  75),   # Pav Bhaji Masala
    (5,  28, 100,  78,  74),   # Kitchen King Masala
    (14, 19, 100,  78,  74),   # Chana Masala
    (48, 17, 50,   47,  43),   # Garam Masala (Box)
    (16, 17, 100,  87,  78),
    (17, 16, 100,  73,  66),   # Chat Masala
    (24, 2,  100,  44,  42),   # Jeeravan
    (6,  27, 100,  60,  55),   # Garadu Masala
    (11, 22, 50,   53,  49),   # Tea Masala
    (52, 34, 100,  78,  68),   # Sambhar Masala
    (10, 23, 100,  104, 96),   # Kashmiri Mirch Powder
    (7,  26, 100,  86,  79),   # Sonth Powder (Dry Ginger)
    (15, 18, 25,   28,  26),   # Kasuri Methi
    (50, 18, 100,  100, 92),
    (12, 21, 200,  79,  72),   # Hari Mirch Achar Masala
    (13, 20, 200,  79,  72),   # Nimbu Chutney Achar Masala
    (23, 3,  500,  191, 175),  # Achar Masala
    # Turmeric Powder
    (37, 5,  100,  45,  42),
    (38, 5,  200,  85,  78),
    (21, 5,  500,  202, 185),
    (39, 5,  1000, 382, 349),
    # Coriander Powder
    (34, 11, 100,  40,  37),
    (35, 11, 200,  76,  71),
    (19, 11, 500,  180, 169),
    (36, 11, 1000, 340, 319),
    # Desi Tadakan Mirch Powder
    (22, 4,  500,  227, 209),
    # Chilli Powder (VIP Teja)
    (43, 6,  100,  62,  57),
    (44, 6,  200,  118, 105),
    (20, 6,  500,  280, 255),
    (45, 6,  1000, 529, 479),
    # Chilli Powder (Patna)
    (40, 15, 100,  72,  65),
    (41, 15, 200,  137, 119),
    (18, 15, 500,  324, 289),
    (42, 15, 1000, 612, 545),
    # Amchur Powder
    (47, 24, 100,  53,  49),
    (9,  24, 500,  238, 219),
    # Papad Katran - the one increase (weight slab, see PRICING_STRATEGY.md)
    (51, 1,  500,  108, 119),
    (25, 1,  1000, 205, 229),
]
# Held on purpose (not in PLAN): Moong Papad, Chana Papad, both papad masalas,
# Sev Masala, Safed Mirch Powder, and the 9g Garam Masala sachet.


def grams(variant):
    if variant.weight is None:
        return None
    w = Decimal(variant.weight)
    return w * 1000 if (variant.unit or '').lower() in ('kg', 'l') else w


changed, skipped, backup = [], [], []

with transaction.atomic():
    for vid, pid, size_g, expected, new in PLAN:
        variant = ProductVariant.objects.select_related('product').filter(pk=vid).first()
        if variant is None:
            skipped.append((vid, '?', 'no size with this id'))
            continue
        label = f'{variant.product.name} {size_g}g'
        if variant.product_id != pid:
            skipped.append((vid, label, f'belongs to product {variant.product_id}, plan expected {pid}'))
            continue
        if grams(variant) != size_g:
            skipped.append((vid, label, f'pack size is {variant.weight}{variant.unit}, plan expected {size_g}g'))
            continue
        if not variant.is_active:
            skipped.append((vid, label, 'size is inactive'))
            continue

        current = variant.discount_price if variant.discount_price is not None else variant.price
        if Decimal(current) == Decimal(new):
            skipped.append((vid, label, f'already at {new}'))
            continue
        if Decimal(current) != Decimal(expected) and not FORCE:
            skipped.append((vid, label,
                            f'sale price is {current}, plan assumed {expected} (FORCE=1 to override)'))
            continue
        if Decimal(new) >= variant.price:
            skipped.append((vid, label, f'new price {new} is not below MRP {variant.price}'))
            continue

        backup.append({'variant_id': variant.pk,
                       'discount_price': str(variant.discount_price)
                       if variant.discount_price is not None else None})
        changed.append((vid, variant.product.name, size_g, variant.price, current, new))

        if APPLY:
            variant.discount_price = Decimal(new)
            variant.full_clean()
            variant.save(update_fields=['discount_price', 'updated_at'])

print()
print('APPLIED' if APPLY else 'DRY RUN - nothing written (set APPLY=1 to write)')
print(f'{"size id":>7}  {"product":<34} {"pack":>6} {"MRP":>7} {"now":>7} {"new":>5}')
for vid, name, size_g, mrp, current, new in changed:
    print(f'{vid:>7}  {name[:34]:<34} {size_g:>5}g {mrp:>7} {current:>7} {new:>5}')
print(f'\n{len(changed)} to change, {len(skipped)} skipped')
for vid, label, why in skipped:
    print(f'  SKIPPED size {vid} {label}: {why}')
print('\nROLLBACK DATA (previous sale prices) - keep this:')
print(json.dumps(backup))
