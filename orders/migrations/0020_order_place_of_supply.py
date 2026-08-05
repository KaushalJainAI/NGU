"""Structured destination + GST place of supply on Order.

Existing rows get '' for all three. That is deliberate and load-bearing: a blank
`place_of_supply_state_code` means "placed before this was captured", and
`place_of_supply.is_interstate('')` returns False, so historical orders keep
being treated — and reprinted — as the intra-state supplies they were billed and
filed as. Backfilling them by parsing their address text would re-head invoices
that have already gone into returns.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0019_order_cod_confirmed_by_order_cod_paid_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='shipping_state',
            field=models.CharField(
                blank=True, default='', max_length=100,
                help_text='Destination state as the customer entered it. Free text — '
                          'place_of_supply_state_code is the resolved, authoritative value.'),
        ),
        migrations.AddField(
            model_name='order',
            name='shipping_pincode',
            field=models.CharField(
                blank=True, default='', max_length=10,
                help_text='Destination PIN code as entered. Reported alongside place of '
                          'supply on GST returns.'),
        ),
        migrations.AddField(
            model_name='order',
            name='place_of_supply_state_code',
            field=models.CharField(
                blank=True, db_index=True, default='', max_length=2,
                help_text="GST state code of the destination (e.g. '23' = Madhya Pradesh). "
                          'Blank = historical order, treated as intra-state.'),
        ),
    ]
