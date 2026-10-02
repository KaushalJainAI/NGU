from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0020_productcombo_description_en_and_more'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='category',
            name='products_ca_is_acti_5a5180_idx',
        ),
    ]
