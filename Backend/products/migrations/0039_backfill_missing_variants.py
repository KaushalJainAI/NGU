"""Guarantee the "every product has at least one variant" invariant.

Migration 0018 backfilled a default variant for every product that existed then,
but nothing since has created one for NEW products — the product write path only
sets the legacy price/stock columns. Those products can be listed but never sold
from a variant, and (post-0038) can't be bundled into a combo.

This backfills the stragglers. Going forward the invariant is held by
`products.signals.auto_update_product_on_save`, which calls
`ensure_default_variant_for` on every product save.
"""
from django.db import migrations
from django.utils.text import slugify


def forwards(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    ProductVariant = apps.get_model('products', 'ProductVariant')

    with_variants = set(
        ProductVariant.objects.values_list('product_id', flat=True).distinct()
    )
    missing = Product.objects.exclude(pk__in=with_variants)

    taken = set(ProductVariant.objects.values_list('slug', flat=True))
    to_create = []
    for product in missing.iterator():
        base = slugify(product.name) or 'variant'
        slug = f"{base}-default"
        counter = 1
        while slug in taken:
            slug = f"{base}-default-{counter}"
            counter += 1
        taken.add(slug)
        to_create.append(ProductVariant(
            product=product,
            weight=product.weight,
            unit=product.unit,
            price=product.price,
            discount_price=product.discount_price,
            stock=product.stock,
            slug=slug,
            is_default=True,
            is_active=True,
        ))
    ProductVariant.objects.bulk_create(to_create, batch_size=500)


def backwards(apps, schema_editor):
    # Backfilled rows are indistinguishable from hand-made ones by now, and the
    # legacy Product columns they were built from are still intact, so there is
    # nothing safe (or necessary) to undo.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0038_combo_item_variant'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
