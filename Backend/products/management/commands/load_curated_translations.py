"""Apply the human-curated translations file to the database.

Reads products/fixtures/curated_translations.json (Claude-authored, high quality)
and writes the per-language modeltranslation columns for the existing catalog
(products, categories, combos and reviews). Newer products are handled
separately by `translate_content` (OpenRouter).

Writes via .update() so it bypasses model save()/full_clean() (avoids the
unrelated image-extension validation).

    python manage.py load_curated_translations
    python manage.py load_curated_translations --dry-run
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings

from products.models import Product, Category, ProductCombo
from reviews.models import Review

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "curated_translations.json"

MODEL_MAP = {
    "products": Product,
    "categories": Category,
    "combos": ProductCombo,
    "reviews": Review,
}


class Command(BaseCommand):
    help = "Load human-curated translations from fixtures/curated_translations.json."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change without writing.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        langs = [c for c, _ in settings.LANGUAGES if c != "en"]
        india = data.get("_origin_country_india", {})

        written = objs = 0
        for section, model in MODEL_MAP.items():
            for pk, fields in data.get(section, {}).items():
                updates = {}
                for field, by_lang in fields.items():
                    if not isinstance(by_lang, dict):
                        continue
                    for lang, value in by_lang.items():
                        if lang in langs and value:
                            updates[f"{field}_{lang}"] = value
                # Fill origin_country for India-origin products.
                if model is Product and india:
                    obj = model.objects.filter(pk=pk).only("origin_country_en").first()
                    if obj and (getattr(obj, "origin_country_en", "") or "").strip().lower() == "india":
                        for lang, value in india.items():
                            if lang in langs and value:
                                updates[f"origin_country_{lang}"] = value
                if not updates:
                    continue
                objs += 1
                if dry:
                    self.stdout.write(f"[dry] {section}#{pk}: {len(updates)} fields")
                    continue
                n = model.objects.filter(pk=pk).update(**updates)
                if n:
                    written += len(updates)
                    self.stdout.write(self.style.SUCCESS(f"{section}#{pk}: wrote {len(updates)} fields"))
                else:
                    self.stderr.write(self.style.WARNING(f"{section}#{pk}: not found, skipped"))

        msg = f"\n{'DRY RUN — ' if dry else ''}{objs} objects, {written} fields written."
        self.stdout.write(self.style.SUCCESS(msg))
