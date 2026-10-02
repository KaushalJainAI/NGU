from django.db import migrations
from django.db.models import Q


def set_papad_tax_zero(apps, schema_editor):
    """Papad and papad katran are GST-exempt: set their tax_rate to 0.

    Matches by name (case-insensitive 'papad'), which covers both 'Papad' and
    'Papad Katran'. Combos are left at the default 5% — an admin can zero a
    papad-only combo manually if needed.
    """
    Product = apps.get_model('products', 'Product')
    Product.objects.filter(Q(name__icontains='papad')).update(tax_rate=0)


def reverse_papad_tax(apps, schema_editor):
    """Restore the 5% default for papad products on rollback."""
    Product = apps.get_model('products', 'Product')
    Product.objects.filter(Q(name__icontains='papad')).update(tax_rate=5)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0023_product_tax_rate_productcombo_tax_rate'),
    ]

    operations = [
        migrations.RunPython(set_papad_tax_zero, reverse_papad_tax),
    ]
