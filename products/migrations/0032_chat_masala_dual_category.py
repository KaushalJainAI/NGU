"""List Chat Masala under Sprinklers & Seasonings as well (audit issue #29).

Chat Masala's canonical category is "Blended Masalas", which is what the
breadcrumb showed. It is also a finishing sprinkler (like Kasuri Methi, which
lives in "Sprinklers & Seasonings"), so shoppers browsing that shelf expect to
find it. Keep the canonical category and add the second one.

Matches by name so it is safe on any environment (ids differ between local and
prod); a no-op where either row is missing.
"""
from django.db import migrations

PRODUCT_NAMES = ["Chat Masala", "Chaat Masala"]
EXTRA_CATEGORY = "Sprinklers & Seasonings"


def add_extra_category(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    Category = apps.get_model("products", "Category")

    category = Category.objects.filter(name=EXTRA_CATEGORY).first()
    if category is None:
        return

    for product in Product.objects.filter(name__in=PRODUCT_NAMES):
        if product.category_id != category.id:
            product.extra_categories.add(category)


def remove_extra_category(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    Category = apps.get_model("products", "Category")

    category = Category.objects.filter(name=EXTRA_CATEGORY).first()
    if category is None:
        return

    for product in Product.objects.filter(name__in=PRODUCT_NAMES):
        product.extra_categories.remove(category)


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0031_product_extra_categories"),
    ]

    operations = [
        migrations.RunPython(add_extra_category, remove_extra_category),
    ]
