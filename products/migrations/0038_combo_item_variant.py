"""Repoint combo components at a specific SIZE (ProductVariant).

Until now a ProductComboItem referenced a Product, and all combo price/stock
math read the legacy `Product.price/stock` mirror columns. That was only ever
correct because every product had exactly one active variant; with two sizes
active a combo silently meant "whichever size is default today" and its stock
draw hit a mirror column that no sale reads — an oversell path.

Each existing item is migrated to its product's default active variant (falling
back to the cheapest active one, then to any variant, and finally minting one
from the legacy Product fields for the pathological case of a product with no
variants at all).
"""
from django.db import migrations, models
import django.db.models.deletion


def _pick_variant(apps, product):
    """The variant an existing combo line most likely meant: the one whose
    price/stock the legacy Product columns were mirroring."""
    ProductVariant = apps.get_model('products', 'ProductVariant')
    variants = ProductVariant.objects.filter(product=product)
    return (
        variants.filter(is_default=True, is_active=True).first()
        or variants.filter(is_active=True).order_by('weight').first()
        or variants.order_by('weight').first()
    )


def forwards(apps, schema_editor):
    ProductComboItem = apps.get_model('products', 'ProductComboItem')
    ProductVariant = apps.get_model('products', 'ProductVariant')

    for item in ProductComboItem.objects.select_related('product').all():
        variant = _pick_variant(apps, item.product)
        if variant is None:
            # No variant at all — mint one from the legacy Product fields, the
            # same shape migration 0018 created during the original backfill.
            product = item.product
            variant = ProductVariant.objects.create(
                product=product,
                weight=product.weight,
                unit=product.unit,
                price=product.price,
                discount_price=product.discount_price,
                stock=product.stock,
                slug=f"{product.slug}-default",
                is_default=True,
                is_active=True,
            )
        item.variant = variant
        item.save(update_fields=['variant'])


def backwards(apps, schema_editor):
    # `product` was never dropped and is kept in sync with the variant, so
    # reversing needs no data work.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0037_product_deactivated_at_productcombo_deactivated_at_and_more'),
    ]

    operations = [
        # Drop the old (combo, product) key first: the new model allows two
        # sizes of the same product in one combo, which that key forbade.
        migrations.AlterUniqueTogether(
            name='productcomboitem',
            unique_together=set(),
        ),
        migrations.AddField(
            model_name='productcomboitem',
            name='variant',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='combo_items',
                to='products.productvariant',
                help_text='The exact packaging/size of the product this combo consumes.',
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name='productcomboitem',
            name='variant',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='combo_items',
                to='products.productvariant',
                help_text='The exact packaging/size of the product this combo consumes.',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='productcomboitem',
            unique_together={('combo', 'variant')},
        ),
    ]
