"""
Attach the seed category icons (Backend/products/seed_assets/category_icons/)
to their matching Category rows on Cloudinary.

Uploads directly via cloudinary.uploader (same approach as
upload_local_to_cloudinary) and stores the Cloudinary public_id in
Category.image so MediaCloudinaryStorage.url() builds the CDN URL.

Safe by default:
  * dry run unless --apply is passed
  * only fills categories that currently have NO image
    (pass --force to overwrite existing images too)

Matching is by category name (case-insensitive), so it works regardless of the
auto-generated slug. Add new entries to NAME_TO_FILE as the catalog grows.

Usage:
    python manage.py populate_category_images            # dry run
    python manage.py populate_category_images --apply     # upload + save
    python manage.py populate_category_images --apply --force  # also replace existing
"""
from pathlib import Path

import cloudinary
import cloudinary.uploader
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.models import Category

# Category display name  ->  seed PNG filename (without directory).
NAME_TO_FILE = {
    "Blended Masalas":         "blended-masalas.png",
    "Chilli Powders":          "chilli-powders.png",
    "Ground Spices":           "ground-spices.png",
    "Papad & Snacks":          "papad-and-snacks.png",
    "Pickle Masalas":          "pickle-masalas.png",
    "Sprinklers & Seasonings": "sprinklers-seasonings.png",
}

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "seed_assets" / "category_icons"


def _has_image(cat) -> bool:
    return bool(cat.image and str(cat.image).strip())


class Command(BaseCommand):
    help = "Upload seed category icons to Cloudinary and attach them to Category rows."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Actually upload and save. Default is a safe dry run.")
        parser.add_argument("--force", action="store_true",
                            help="Also replace categories that already have an image.")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        force = options["force"]

        cfg = getattr(settings, "CLOUDINARY_STORAGE", None)
        if not cfg:
            raise CommandError("CLOUDINARY_STORAGE not configured — set USE_CLOUDINARY=True.")
        cloudinary.config(
            cloud_name=cfg["CLOUD_NAME"], api_key=cfg["API_KEY"], api_secret=cfg["API_SECRET"],
        )

        mode = "APPLY" if apply_changes else "DRY RUN"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nCategory icons -> Cloudinary [{mode}]"))
        self.stdout.write(f"Source: {SEED_DIR}  Cloud: {cfg['CLOUD_NAME']}\n")

        totals = {"uploaded": 0, "skipped_has_image": 0, "no_match": 0,
                  "missing_file": 0, "errors": 0}

        # Build a case-insensitive lookup of existing categories.
        by_name = {c.name.strip().lower(): c for c in Category.objects.all()}

        for name, filename in NAME_TO_FILE.items():
            cat = by_name.get(name.strip().lower())
            if cat is None:
                totals["no_match"] += 1
                self.stdout.write(self.style.WARNING(f"  NO CATEGORY named '{name}' — skipped"))
                continue

            if _has_image(cat) and not force:
                totals["skipped_has_image"] += 1
                self.stdout.write(f"  = '{name}' already has an image — skipped (use --force)")
                continue

            local_path = SEED_DIR / filename
            if not local_path.exists():
                totals["missing_file"] += 1
                self.stdout.write(self.style.ERROR(f"  MISSING FILE: {local_path}"))
                continue

            public_id = f"ngu/categories/{local_path.stem}"

            if not apply_changes:
                self.stdout.write(f"  #{cat.pk}  '{name}'  <-  {filename}  ->  {public_id}")
                totals["uploaded"] += 1
                continue

            try:
                result = cloudinary.uploader.upload(
                    str(local_path), public_id=public_id, overwrite=True, resource_type="image",
                )
                stored = result["public_id"]
                Category.objects.filter(pk=cat.pk).update(image=stored)
                totals["uploaded"] += 1
                self.stdout.write(self.style.SUCCESS(f"  #{cat.pk}  '{name}'  ->  {result['secure_url']}"))
            except Exception as exc:  # noqa: BLE001
                totals["errors"] += 1
                self.stdout.write(self.style.ERROR(f"  ERROR '{name}': {exc}"))

        self.stdout.write("\n" + self.style.MIGRATE_HEADING("Summary"))
        self.stdout.write(
            f"  uploaded: {totals['uploaded']}  skipped (has image): {totals['skipped_has_image']}  "
            f"no category match: {totals['no_match']}  missing file: {totals['missing_file']}  "
            f"errors: {totals['errors']}"
        )
        if not apply_changes:
            self.stdout.write(self.style.WARNING("\nRe-run with --apply to actually upload."))
