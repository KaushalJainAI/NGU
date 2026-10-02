"""Reorganise the catalog into practical, shopper-friendly categories.

The store previously had only two broad buckets ("Blended Masalas" and
"Dried"), which mixed chilli powders, single ground spices, pickle masalas,
papads and seasonings together. This migration introduces a richer taxonomy —
inspired by how established spice retailers (e.g. pushponline.com) group their
range — and spreads every product across the new categories.

Products are classified by name keywords (case-insensitive), so the migration
is robust to name prefixes/suffixes (brand name, pack weight) and does not rely
on hard-coded primary keys. Empty leftover categories are removed afterwards.
"""
from django.utils.text import slugify
from django.db import migrations


# name -> shopper-facing description for the new category set.
NEW_CATEGORIES = {
    "Blended Masalas": "Ready-to-cook spice blends for everyday and special dishes.",
    "Chilli Powders": "Pure red chilli powders — from mild colour to fiery heat.",
    "Ground Spices": "Single, freshly ground everyday spices for your kitchen.",
    "Pickle Masalas": "Achar masalas to make traditional Indian pickles at home.",
    "Sprinklers & Seasonings": "Finishing sprinkles and seasonings that lift any plate.",
    "Papad & Snacks": "Crisp papads and fryums to fry, roast and enjoy.",
}


def categorize(name: str) -> str:
    """Map a product name to one of the new categories (first rule wins)."""
    n = (name or "").lower()

    # Pickle (achar) masalas — check before chilli so "Hari Mirch Achar" lands here.
    if "achar" in n:
        return "Pickle Masalas"

    # Papad seasoning vs papad snack. "papad masala" (a sprinkle) must beat the
    # generic "papad" rule; "masala papad" is still an actual papad.
    if "papad masala" in n:
        return "Sprinklers & Seasonings"
    if "masala papad" in n or "papad" in n:
        return "Papad & Snacks"

    # Sprinklers / seasonings / dried herbs.
    if "jeeravan" in n or "methi" in n:
        return "Sprinklers & Seasonings"

    # Chilli powders — exclude "safed mirch" (white pepper), which is a ground spice.
    if "safed" not in n and any(k in n for k in ("mirchi", "mirch", "chilli", "chili")):
        return "Chilli Powders"

    # Single ground spices.
    if any(k in n for k in (
        "turmeric", "haldi", "coriander", "dhaniya", "dhania",
        "amchur", "aamchur", "sonth", "saunth", "ginger",
        "safed", "pepper", "kali mirch",
    )):
        return "Ground Spices"

    # Everything else is a multi-spice blend.
    return "Blended Masalas"


def apply_recategorization(apps, schema_editor):
    Category = apps.get_model("products", "Category")
    Product = apps.get_model("products", "Product")

    # Create / fetch the new categories.
    cat_by_name = {}
    for cat_name, desc in NEW_CATEGORIES.items():
        cat, _ = Category.objects.get_or_create(
            name=cat_name,
            defaults={"slug": slugify(cat_name), "description": desc, "is_active": True},
        )
        # Backfill slug/description/active on any pre-existing row (e.g. "Blended Masalas").
        changed = False
        if not cat.slug:
            cat.slug = slugify(cat_name)
            changed = True
        if not cat.description:
            cat.description = desc
            changed = True
        if not cat.is_active:
            cat.is_active = True
            changed = True
        if changed:
            cat.save()
        cat_by_name[cat_name] = cat

    # Reassign every product.
    for product in Product.objects.all():
        target = cat_by_name[categorize(product.name)]
        if product.category_id != target.id:
            product.category = target
            product.save(update_fields=["category"])

    # Remove categories that are now empty and not part of the new taxonomy
    # (cleans up the old "Dried" bucket without touching anything still in use).
    keep = set(NEW_CATEGORIES.keys())
    for cat in Category.objects.all():
        if cat.name not in keep and not Product.objects.filter(category_id=cat.id).exists():
            cat.delete()


def reverse_recategorization(apps, schema_editor):
    """No-op reverse.

    The original two-bucket split cannot be reconstructed unambiguously, and the
    new taxonomy is a strict improvement. Rolling back simply leaves the richer
    categories in place; re-running the forward migration is idempotent.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0024_papad_zero_tax"),
    ]

    operations = [
        migrations.RunPython(apply_recategorization, reverse_recategorization),
    ]
