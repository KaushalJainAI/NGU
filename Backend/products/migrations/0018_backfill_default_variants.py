from django.db import migrations
from django.utils.text import slugify


def _formatted_weight(weight, unit):
    if weight and unit:
        w = float(weight)
        if w.is_integer():
            w = int(w)
        return f"{w}{unit}"
    return str(weight or "")


def backfill_default_variants(apps, schema_editor):
    """Create exactly one is_default ProductVariant for every existing Product,
    copying its legacy per-size fields. Idempotent: products that already have a
    default variant are skipped. The legacy Product fields are left untouched."""
    Product = apps.get_model('products', 'Product')
    ProductVariant = apps.get_model('products', 'ProductVariant')

    used_slugs = set(ProductVariant.objects.values_list('slug', flat=True))

    for product in Product.objects.all().iterator():
        if ProductVariant.objects.filter(product=product, is_default=True).exists():
            continue

        weight_part = _formatted_weight(product.weight, product.unit)
        base_slug = slugify(f"{product.name}-{weight_part}") if weight_part else slugify(product.name)
        if not base_slug:
            base_slug = f"variant-{product.pk}"
        slug = base_slug
        counter = 1
        while slug in used_slugs:
            slug = f"{base_slug}-{counter}"
            counter += 1
        used_slugs.add(slug)

        ProductVariant.objects.create(
            product=product,
            weight=product.weight,
            unit=product.unit,
            price=product.price,
            discount_price=product.discount_price,
            stock=product.stock or 0,
            slug=slug,
            is_default=True,
            is_active=True,
            display_order=0,
        )


def remove_default_variants(apps, schema_editor):
    """Reverse: drop only the auto-generated default variants."""
    ProductVariant = apps.get_model('products', 'ProductVariant')
    ProductVariant.objects.filter(is_default=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0017_productvariant'),
    ]

    operations = [
        migrations.RunPython(backfill_default_variants, remove_default_variants),
    ]
