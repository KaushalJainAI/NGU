"""Charge 5% on the two papad-MASALA blends, which have been billing 0%.

Migration 0024 zeroed `tax_rate` for every product whose name contained
"papad", because papad and papad katran are NIL-rated (settled by AAAR, branded
or not). That string match also swept up two products that are not papad:

    Chana Papad Masala   (id 25 in the curated catalogue)
    Moong Papad Masala   (id 29)

They are sprinkle seasonings sold to season papad — their own descriptions call
them a "masala mishran ... halka chhidkaav", the storefront shelves them under
"Sprinklers & Seasonings" rather than "Papad & Snacks" (migration 0025), and the
actual papads exist as SEPARATE SKUs (Chana Papad, Moong Papad, Papad Katran)
which keep their NIL rating untouched here. The NIL entry covers papad itself;
a taxable seasoning does not inherit it by being sold alongside one.

Migration 0042 coded them 09109100 (mixtures of spices, 5%) and deliberately
left the rate alone, because what is charged is the owner's call. This is the
owner making it: confirmed 2026-08-04. It clears the standing "2 products charge
a rate that differs from their HSN code" warning on the admin /gst page.

WHAT THIS DOES AND DOES NOT CHANGE
----------------------------------
* Shelf price does NOT move. Product prices are MRP, GST-INCLUSIVE — the rate
  only decides how much tax is EXTRACTED from that MRP for disclosure. The
  customer keeps paying the same rupees; the seller now remits 5/105ths of it.
* Past orders are NOT touched. `tax_rate` is snapshotted onto the order line at
  checkout, so already-issued invoices keep the 0% they were billed at. This
  fixes the rate going forward only; any correction to historical sales is a
  separate, deliberate accounting decision.
* The `hsn_code` is already correct and is not written here.

STILL OPEN
----------
The descriptions promise a "namkeen finish", i.e. these blends contain salt. If
they do materially, the revenue's position pushes them out of Chapter 9 and into
21039040 (mixed condiments) at **18%**, not 5%. That call needs the ingredient
list and a CA — see the note on 21039040 in products/hsn.py. 5% is the correct
floor either way; 0% was not defensible.
"""
from django.db import migrations
from django.db.models import Q


# Narrow on all three axes rather than on the name alone: the name pattern picks
# out the two blends, the code confirms they were classified as blends, and the
# rate ensures we only touch rows still sitting at the 0024 default. An admin who
# has already set a rate by hand (5, or 18 after a CA review) is left alone.
_TARGET = Q(name__icontains='papad masala') & Q(hsn_code='09109100')


def set_papad_masala_taxable(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    Product.objects.filter(_TARGET, tax_rate=0).update(tax_rate=5)


def reverse_papad_masala_taxable(apps, schema_editor):
    """Restore the 0% these carried before, for a clean rollback.

    Mirrors the forward filter, so a product an admin has since moved to 18%
    is not dragged down to zero by an unrelated rollback.
    """
    Product = apps.get_model('products', 'Product')
    Product.objects.filter(_TARGET, tax_rate=5).update(tax_rate=0)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0042_populate_hsn_codes'),
    ]

    operations = [
        migrations.RunPython(set_papad_masala_taxable, reverse_papad_masala_taxable),
    ]
