# Adds the 'rejected' payment_status (L3 abandoned-checkout auto-cancel).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0010_alter_order_payment_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='payment_status',
            field=models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('paid', 'Paid'), ('failed', 'Failed'), ('rejected', 'Payment Rejected'), ('refunded', 'Refunded')], default='pending', max_length=20),
        ),
    ]
