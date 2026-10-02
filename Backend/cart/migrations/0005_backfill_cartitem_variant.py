from django.db import migrations


def backfill_cart_variants(apps, schema_editor):
    """Point existing product cart lines at their product's default variant."""
    CartItem = apps.get_model('cart', 'CartItem')
    ProductVariant = apps.get_model('products', 'ProductVariant')

    defaults = {
        v.product_id: v
        for v in ProductVariant.objects.filter(is_default=True)
    }
    for item in CartItem.objects.filter(item_type='product', variant__isnull=True).iterator():
        variant = defaults.get(item.product_id)
        if variant is not None:
            item.variant = variant
            item.save(update_fields=['variant'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('cart', '0004_remove_cartitem_unique_cart_product_cartitem_variant_and_more'),
        ('products', '0018_backfill_default_variants'),
    ]

    operations = [
        migrations.RunPython(backfill_cart_variants, noop),
    ]
