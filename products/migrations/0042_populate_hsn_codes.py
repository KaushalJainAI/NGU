"""Populate `Product.hsn_code` for the existing catalogue.

Classification is done by keyword from the product name (see
`products/hsn.py::suggest`), which resolves every item in the live 25-product
catalogue:

    chilli powders (mirchi/teja/patna/kashmari/desi tadka) -> 09042211
    dhaniya powder                                         -> 09092200
    haldi powder                                           -> 09103030
    dry ginger powder                                      -> 09101210
    kasuri methi                                           -> 09109924
    amchur powder                                          -> 09109990
    every masala blend (garam, chat, pav bhaji, chana,
      kitchen king, tea/chai, jeeravan, garadu, achar,
      nimbu chatani, chana/moong papad masala)             -> 09109100
    papad + papad katran                                   -> 19059040

TWO THINGS THIS MIGRATION DELIBERATELY DOES NOT DO
--------------------------------------------------
1. **It never touches `tax_rate`.** Assigning a code is a statement of fact
   about the goods; changing what is charged is a pricing/tax decision that
   belongs to the owner and their CA. The admin panel now shows, per product,
   the statutory rate published for the assigned HSN next to the rate actually
   charged, and flags a mismatch — the admin decides.

   That flag will fire on the two papad-MASALA products. Migration 0024 zeroed
   `tax_rate` for every name containing "papad", which swept up
   "Chana papad masala" and "Moong papad masala". Those are spice blends, not
   papad: papad is NIL under 19059040, a masala is taxable under 09109100.
   Coding them correctly here makes that visible instead of silent — but the
   rate correction is the owner's call to make, not this migration's.

2. **It never overwrites a code an admin already set.** Only blank fields are
   filled, so re-running (or applying to a database an admin has already
   curated) cannot undo human classification work.
"""
from django.db import migrations


def populate(apps, schema_editor):
    from products.hsn import suggest

    Product = apps.get_model('products', 'Product')
    for product in Product.objects.filter(hsn_code='').only(
            'id', 'name', 'ingredients', 'hsn_code'):
        code, _confidence = suggest(product.name, getattr(product, 'ingredients', ''))
        if code:
            product.hsn_code = code
            product.save(update_fields=['hsn_code'])


def unpopulate(apps, schema_editor):
    """Clear every code on rollback.

    Blanket rather than selective: this migration is the only thing that has
    written the column at this point in history, so clearing it restores the
    pre-migration state exactly.
    """
    Product = apps.get_model('products', 'Product')
    Product.objects.exclude(hsn_code='').update(hsn_code='')


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0041_product_hsn_code'),
    ]

    operations = [
        migrations.RunPython(populate, unpopulate),
    ]
