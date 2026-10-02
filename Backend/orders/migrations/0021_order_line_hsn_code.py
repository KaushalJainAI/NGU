"""Snapshot the HSN code onto order lines.

Hand-scoped to the two `hsn_code` columns and nothing else. `makemigrations`
also wanted to sweep in the Invoice / InvoiceCounter models being developed
alongside this; those belong to their own migration, so that neither change can
hold the other hostage on the way to production.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0020_order_place_of_supply'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='hsn_code',
            field=models.CharField(
                blank=True, default='', max_length=8,
                help_text='HSN code billed on this line at order time (snapshot).'),
        ),
        migrations.AddField(
            model_name='orderitemcomponent',
            name='hsn_code',
            field=models.CharField(
                blank=True, default='', max_length=8,
                help_text='HSN code of this component at order time (snapshot).'),
        ),
    ]
