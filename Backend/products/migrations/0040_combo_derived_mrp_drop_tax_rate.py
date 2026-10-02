"""Combo MRP becomes derived; GST moves to the components.

Two columns go away:

* ``price`` — a combo's MRP is by definition the sum of its component sizes'
  prices, so it is now a computed property (``ProductCombo.price``) and can
  never drift from the sizes actually bundled.
* ``tax_rate`` — GST is charged per component at its own product's rate. A
  bundle mixing 0% papad with 5% spices used to be billed at one hand-entered
  blended rate, which is wrong on a tax invoice.

The data step below runs FIRST and exists to stop the drop from silently
repricing the catalogue. Before this migration a combo sold for
``discount_price or price``; afterwards it sells for ``discount_price or
derived MRP``. Those differ whenever the admin-typed price was not exactly the
component sum — which is the normal case, since that gap was the whole point of
the old column. So the current selling price is copied into ``discount_price``
while ``price`` is still readable.

Combos whose selling price is >= the derived MRP (no saving, or a bundle priced
above its parts) get ``discount_price = NULL`` and therefore sell at MRP: the
model forbids a selling price at or above MRP, and leaving one in place would
make the row fail validation on its next admin save.

Dropping ``tax_rate`` loses no history — every placed OrderItem already
snapshots the rate it was charged at, so past invoices reprint unchanged.
"""

from django.db import migrations


def preserve_selling_price(apps, schema_editor):
    ProductCombo = apps.get_model('products', 'ProductCombo')
    ProductComboItem = apps.get_model('products', 'ProductComboItem')

    for combo in ProductCombo.objects.all():
        mrp = sum(
            (ci.variant.price * ci.quantity
             for ci in ProductComboItem.objects.filter(
                 combo=combo).select_related('variant')),
            0,
        )
        selling = combo.discount_price if combo.discount_price else combo.price
        # A combo with no components has no derived MRP to compare against;
        # null the discount so it is not left validating against zero.
        combo.discount_price = selling if (mrp and selling < mrp) else None
        combo.save(update_fields=['discount_price'])


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0039_backfill_missing_variants'),
    ]

    operations = [
        migrations.RunPython(preserve_selling_price, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='productcombo',
            name='price',
        ),
        migrations.RemoveField(
            model_name='productcombo',
            name='tax_rate',
        ),
    ]
