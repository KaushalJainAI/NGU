"""Seed ProductSlugAlias with the slugs retired by the catalog re-slugging.

28 products were re-slugged (junk slugs like `dummy-slug`, `logo-89900` and
weight-suffixed ones like `sambhar-masala-100g` became clean names). Every URL
already in the wild for those products currently 404s. The old slug -> product
mapping was recorded in Backend/reslug_rollback.json at re-slug time; this
replays it into the alias table so those links resolve again.

Keyed by product PK, so a product that has since been deleted is simply skipped.
"""
import json
from pathlib import Path

from django.db import migrations

# Repo-root-relative: Backend/products/migrations/ -> Backend/
ROLLBACK_FILE = Path(__file__).resolve().parent.parent.parent / "reslug_rollback.json"


def seed_aliases(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    ProductSlugAlias = apps.get_model("products", "ProductSlugAlias")

    if not ROLLBACK_FILE.exists():
        return

    try:
        rollback = json.loads(ROLLBACK_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return

    live = dict(Product.objects.values_list("pk", "slug"))

    for pk_str, entry in rollback.items():
        try:
            pk = int(pk_str)
        except (TypeError, ValueError):
            continue

        old_slug = (entry or {}).get("slug")
        current_slug = live.get(pk)

        # Skip if the product is gone, the slug never changed, or the old slug
        # is now some other product's canonical slug (it can't be both).
        if not old_slug or current_slug is None or old_slug == current_slug:
            continue
        if old_slug in live.values():
            continue

        ProductSlugAlias.objects.update_or_create(
            slug=old_slug, defaults={"product_id": pk}
        )


def unseed_aliases(apps, schema_editor):
    apps.get_model("products", "ProductSlugAlias").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0029_productslugalias"),
    ]

    operations = [
        migrations.RunPython(seed_aliases, unseed_aliases),
    ]
