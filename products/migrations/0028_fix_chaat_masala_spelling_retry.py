"""Forward-only retry of the 'Chat Masala' -> 'Chaat Masala' rename.

0026 was recorded as applied on production but the row was left unchanged.
This migration redoes the rename at the database level with a single
queryset .update() (case-insensitive REPLACE) instead of per-object save(),
which removes any dependency on model save() behaviour.

Slugs are intentionally left untouched so existing URLs / SEO keep working.
Idempotent: re-running is a no-op once the names are correct.
"""
from django.db import migrations
from django.db.models.functions import Replace
from django.db.models import Value


def fix_chaat_spelling(apps, schema_editor):
    for model_name in ("Product", "ProductCombo"):
        model = apps.get_model("products", model_name)
        # Handle the casings that actually occur, most-specific first.
        for wrong in ("Chat Masala", "chat masala", "Chat masala", "chat Masala"):
            model.objects.filter(name__contains=wrong).update(
                name=Replace("name", Value(wrong), Value("Chaat Masala"))
            )


def reverse_noop(apps, schema_editor):
    # Correcting a spelling mistake is not meaningfully reversible.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0027_product_nutrition_product_recipe_product_recipe_en_and_more"),
    ]

    operations = [
        migrations.RunPython(fix_chaat_spelling, reverse_noop),
    ]
