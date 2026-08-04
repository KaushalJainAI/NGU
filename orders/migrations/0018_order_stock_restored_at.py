from django.db import migrations, models


class Migration(migrations.Migration):
    """Marker for 'this order's stock has already been given back'.

    Backfilled NULL for every existing row, including cancelled ones. That is
    deliberate: the flag guards FUTURE restocks, and no existing order can be
    restocked again anyway — 'cancelled' is uncancellable, and the refund path
    that reads this flag ships in the same change.
    """

    dependencies = [
        ('orders', '0017_order_item_component'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='stock_restored_at',
            field=models.DateTimeField(
                blank=True, editable=False, null=True,
                help_text="When this order's stock was returned to inventory. Set once; "
                          "guarantees cancel + refund can't both credit the same units."),
        ),
    ]
