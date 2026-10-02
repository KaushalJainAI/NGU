"""Apply the "a switched-off product is not in any combo" rule to existing data.

From now on `Product.save()` takes a product out of its combos the moment it is
switched off (products/combo_membership.py). This is the one-off for products
that were ALREADY off when that rule arrived, or that were switched off behind
save()'s back since (a queryset `.update()`, a script, bulk SQL).

    python manage.py detach_inactive_products_from_combos --dry-run   # report only
    python manage.py detach_inactive_products_from_combos

⚠ Every combo that is on sale and loses a line is SWITCHED OFF, so that it is
never sold at a price set for a bigger bundle. Run the dry-run first and read
the list: those combos leave the shop until someone reviews and re-activates
them. Nothing is deleted — switching the product back on restores the lines.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from products.combo_membership import detach_product_from_combos
from products.models import Product, ProductComboItem


class Command(BaseCommand):
    help = "Remove switched-off products from the combos that still contain them."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Report what would change without changing anything.")

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        products = (Product.objects.filter(is_active=False, productcomboitem__isnull=False)
                    .distinct().order_by('name'))
        if not products:
            self.stdout.write("No switched-off product is in any combo. Nothing to do.")
            return

        touched = 0
        for product in products:
            lines = ProductComboItem.objects.filter(product=product).select_related('combo')
            names = sorted({line.combo.name for line in lines})
            going_off = sorted({line.combo.name for line in lines if line.combo.is_active})
            self.stdout.write(
                f"  {product.name}: {'would be removed' if dry_run else 'removed'} from "
                f"{', '.join(names)}"
                + (f" — {'would switch' if dry_run else 'switched'} OFF: {', '.join(going_off)}"
                   if going_off else ''))
            if not dry_run:
                with transaction.atomic():
                    detach_product_from_combos(product)
            touched += 1

        verb = "Would change" if dry_run else "Changed"
        self.stdout.write(self.style.SUCCESS(f"{verb} {touched} product(s)."))
