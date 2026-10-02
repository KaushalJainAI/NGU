from django.db import migrations


def backfill_order_variants(apps, schema_editor):
    """Best-effort: link historical product order items to their product's
    default variant. The human-readable size is already snapshotted in
    product_weight, so this is only for reference/reorder convenience."""
    OrderItem = apps.get_model('orders', 'OrderItem')
    ProductVariant = apps.get_model('products', 'ProductVariant')

    defaults = {
        v.product_id: v
        for v in ProductVariant.objects.filter(is_default=True)
    }
    for item in OrderItem.objects.filter(item_type='product', variant__isnull=True).iterator():
        variant = defaults.get(item.product_id)
        if variant is not None:
            item.variant = variant
            item.save(update_fields=['variant'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0006_orderitem_variant'),
        ('products', '0018_backfill_default_variants'),
    ]

    operations = [
        migrations.RunPython(backfill_order_variants, noop),
    ]
