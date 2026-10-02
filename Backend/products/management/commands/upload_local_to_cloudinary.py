"""
One-time upload: push local product images to Cloudinary and rewrite DB references.

Uploads directly via cloudinary.uploader (bypasses Django field validators).
Stores the Cloudinary public_id in the DB field so MediaCloudinaryStorage.url()
builds the CDN URL automatically.

For thumbnails: because the thumbnail field was cleared during a previous
correction, the command scans the local filesystem for the canonical thumbnail
file (shortest name matching thumb_<pk>_*.png) rather than reading the DB field.

Covers:
  - products.Product.image
  - products.Product.thumbnail  (filesystem scan, pk-matched)
  - products.ProductImage.image

After running, use --export-sql to write UPDATE statements for the production DB
(files are already in Cloudinary; no re-upload needed on prod, just DB patch).

Usage:
    python manage.py upload_local_to_cloudinary            # dry run
    python manage.py upload_local_to_cloudinary --apply    # upload + update DB
    python manage.py upload_local_to_cloudinary --apply --export-sql prod_patch.sql
"""
import glob
import os
from pathlib import Path

import cloudinary
import cloudinary.uploader
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.models import Product, ProductImage


def _is_cloudinary(name: str) -> bool:
    """True only if the stored name is already a Cloudinary public_id/URL."""
    if not name:
        return False  # empty = not yet uploaded
    return name.startswith('ngu/') or 'res.cloudinary.com' in name or name.startswith('http')


def _public_id(rel_path: str, prefix: str = 'ngu') -> str:
    """Cloudinary public_id from a relative media path (strips extension)."""
    return f"{prefix}/{os.path.splitext(rel_path)[0]}"


def _find_canonical_thumbnail(media_root: Path, pk: int) -> Path | None:
    """Return the shortest (original) thumbnail file for a given product pk.

    Ignores files under doubled paths (products/thumbnails/products/...) that
    were created by a previous mis-run against local filesystem storage.
    """
    pattern = str(media_root / 'products' / 'thumbnails' / f'thumb_{pk}_*.png')
    candidates = [
        p for p in glob.glob(pattern)
        # exclude the doubled-path duplicates created during the bad run
        if 'products/thumbnails/products' not in p.replace('\\', '/')
    ]
    if not candidates:
        return None
    # Prefer the shortest filename (original, no Django dedup suffix)
    return Path(min(candidates, key=lambda p: len(os.path.basename(p))))


class Command(BaseCommand):
    help = 'Upload local product images/thumbnails to Cloudinary and rewrite DB references.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Actually upload and save. Default is a safe dry run.')
        parser.add_argument('--export-sql', default=None, metavar='FILE',
                            help='After applying, write SQL UPDATE statements to FILE '
                                 'so the production DB can be patched without re-uploading.')

    def handle(self, *args, **options):
        apply_changes = options['apply']
        export_sql = options['export_sql']

        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if not media_root:
            raise CommandError('MEDIA_ROOT not set — ensure USE_S3=False in .env.')

        media_root = Path(media_root)

        cfg = settings.CLOUDINARY_STORAGE
        cloudinary.config(
            cloud_name=cfg['CLOUD_NAME'],
            api_key=cfg['API_KEY'],
            api_secret=cfg['API_SECRET'],
        )

        mode = 'APPLY' if apply_changes else 'DRY RUN'
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\nProduct images -> Cloudinary [{mode}]'
        ))
        self.stdout.write(f'Source: {media_root}  Cloud: {cfg["CLOUD_NAME"]}\n')

        totals = {'uploaded': 0, 'skipped': 0, 'missing': 0, 'errors': 0}
        sql_lines: list[str] = []

        # ── 1. Product.image ──────────────────────────────────────────────────
        self.stdout.write('\nProduct.image')
        for obj in Product.objects.all().order_by('pk'):
            name = obj.image.name if obj.image else ''
            if not name:
                totals['missing'] += 1
                self.stdout.write(self.style.WARNING(f'  NO IMAGE: #{obj.pk}'))
                continue
            if _is_cloudinary(name):
                totals['skipped'] += 1
                continue
            local_path = media_root / name
            if not local_path.exists():
                totals['missing'] += 1
                self.stdout.write(self.style.WARNING(f'  MISSING: #{obj.pk}  {name}'))
                continue
            public_id = _public_id(name)
            if not apply_changes:
                self.stdout.write(f'  #{obj.pk}  {name}  ->  {public_id}')
                totals['uploaded'] += 1
                continue
            try:
                result = cloudinary.uploader.upload(
                    str(local_path), public_id=public_id, overwrite=True, resource_type='image'
                )
                stored = result['public_id']
                Product.objects.filter(pk=obj.pk).update(image=stored)
                totals['uploaded'] += 1
                sql_lines.append(
                    f"UPDATE products_product SET image = '{stored}' WHERE id = {obj.pk};"
                )
                self.stdout.write(self.style.SUCCESS(f'  #{obj.pk}  ->  {result["secure_url"]}'))
            except Exception as exc:  # noqa: BLE001
                totals['errors'] += 1
                self.stdout.write(self.style.ERROR(f'  ERROR #{obj.pk}  {name}: {exc}'))

        # ── 2. Product.thumbnail (filesystem scan by pk) ──────────────────────
        self.stdout.write('\nProduct.thumbnail (scanning local files by product pk)')
        for obj in Product.objects.all().order_by('pk'):
            thumb_name = obj.thumbnail.name if obj.thumbnail else ''
            if _is_cloudinary(thumb_name):
                totals['skipped'] += 1
                continue

            local_path = _find_canonical_thumbnail(media_root, obj.pk)
            if local_path is None:
                totals['missing'] += 1
                self.stdout.write(self.style.WARNING(f'  MISSING thumb: product #{obj.pk}'))
                continue

            rel = local_path.relative_to(media_root).as_posix()
            public_id = _public_id(rel)

            if not apply_changes:
                self.stdout.write(f'  #{obj.pk}  {rel}  ->  {public_id}')
                totals['uploaded'] += 1
                continue

            try:
                result = cloudinary.uploader.upload(
                    str(local_path), public_id=public_id, overwrite=True, resource_type='image'
                )
                stored = result['public_id']
                Product.objects.filter(pk=obj.pk).update(thumbnail=stored)
                totals['uploaded'] += 1
                sql_lines.append(
                    f"UPDATE products_product SET thumbnail = '{stored}' WHERE id = {obj.pk};"
                )
                self.stdout.write(self.style.SUCCESS(f'  #{obj.pk}  ->  {result["secure_url"]}'))
            except Exception as exc:  # noqa: BLE001
                totals['errors'] += 1
                self.stdout.write(self.style.ERROR(f'  ERROR #{obj.pk}  {rel}: {exc}'))

        # ── 3. ProductImage.image (gallery) ───────────────────────────────────
        self.stdout.write('\nProductImage.image (gallery)')
        gallery_qs = ProductImage.objects.exclude(image='').exclude(image__isnull=True)
        for obj in gallery_qs.order_by('pk'):
            name = obj.image.name if obj.image else ''
            if _is_cloudinary(name):
                totals['skipped'] += 1
                continue
            local_path = media_root / name
            if not local_path.exists():
                totals['missing'] += 1
                self.stdout.write(self.style.WARNING(f'  MISSING: #{obj.pk}  {name}'))
                continue
            public_id = _public_id(name)
            if not apply_changes:
                self.stdout.write(f'  #{obj.pk}  {name}  ->  {public_id}')
                totals['uploaded'] += 1
                continue
            try:
                result = cloudinary.uploader.upload(
                    str(local_path), public_id=public_id, overwrite=True, resource_type='image'
                )
                stored = result['public_id']
                ProductImage.objects.filter(pk=obj.pk).update(image=stored)
                totals['uploaded'] += 1
                sql_lines.append(
                    f"UPDATE products_productimage SET image = '{stored}' WHERE id = {obj.pk};"
                )
                self.stdout.write(self.style.SUCCESS(f'  #{obj.pk}  ->  {result["secure_url"]}'))
            except Exception as exc:  # noqa: BLE001
                totals['errors'] += 1
                self.stdout.write(self.style.ERROR(f'  ERROR #{obj.pk}  {name}: {exc}'))

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write('\n' + self.style.MIGRATE_HEADING('Summary'))
        self.stdout.write(
            f"  uploaded: {totals['uploaded']}  skipped (already Cloudinary): {totals['skipped']}  "
            f"missing: {totals['missing']}  errors: {totals['errors']}"
        )

        if export_sql and sql_lines and apply_changes:
            sql_path = Path(export_sql)
            sql_path.write_text(
                '-- Production DB patch: apply after deploying Cloudinary-enabled image.\n'
                '-- Run on prod: psql $DATABASE_URL -f ' + sql_path.name + '\n\n'
                + '\n'.join(sql_lines) + '\n'
            )
            self.stdout.write(self.style.SUCCESS(f'\nSQL patch written to {sql_path}'))

        if not apply_changes:
            self.stdout.write(self.style.WARNING('\nRe-run with --apply to actually upload.'))
