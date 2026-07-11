# Generated for shipment tracking + status emails

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0008_alter_order_payment_method'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='tracking_number',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
