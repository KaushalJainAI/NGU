"""Switch to GST-inclusive pricing.

New orders carry `tax_inclusive=True`: the price the customer sees already
contains GST, so `tax` is a disclosure figure inside `subtotal` rather than an
amount added to reach `total_amount`.

Every order that already exists was placed under the old additive convention and
is backfilled to False. Their stored money columns are deliberately NOT
recomputed — the totals customers were actually charged are correct as written,
and the flag is what lets `orders/invoice.py` reprint those bills so they still
add up.
"""

from django.db import migrations, models


def mark_existing_orders_exclusive(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    Order.objects.update(tax_inclusive=False)


def unmark(apps, schema_editor):
    """Reverse: the column is dropped by the AddField reversal anyway, so there
    is nothing meaningful to restore."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0013_order_delivery_bill_order_delivery_bill_uploaded_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='tax_inclusive',
            field=models.BooleanField(
                default=True,
                help_text='True: prices include GST (tax is part of subtotal). '
                          'False (legacy): GST was added on top of subtotal.'),
        ),
        migrations.AlterField(
            model_name='order',
            name='tax',
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=10,
                help_text='GST on the discounted amount. When tax_inclusive is True this is '
                          'CONTAINED IN subtotal (disclosure only); on legacy orders it was '
                          'ADDED to reach total_amount.'),
        ),
        migrations.RunPython(mark_existing_orders_exclusive, unmark),
    ]
