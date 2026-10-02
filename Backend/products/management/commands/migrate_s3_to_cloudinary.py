"""
One-time migration: copy every existing image/file from AWS S3 into Cloudinary.

Why: the `default` storage backend has been switched to Cloudinary
(`cloudinary_storage.storage.MediaCloudinaryStorage`). New uploads now land in
Cloudinary automatically, but rows already in the database still reference files
that physically live in the S3 bucket. This command reads each existing file's
bytes straight from S3 and re-saves them through the (now Cloudinary) default
storage, which uploads the file and rewrites the stored field name on the row.

It covers every image/file field in the project:
  - products.Category.image
  - products.Product.image, products.Product.thumbnail
  - products.ProductImage.image
  - products.ProductCombo.image, products.ProductCombo.thumbnail
  - users.User.profile_picture
  - support.ChatMessage.attachment

Safe to run repeatedly (idempotent): rows whose field already points at a
Cloudinary asset are skipped. Defaults to a DRY RUN; pass --apply to write.

    python manage.py migrate_s3_to_cloudinary                  # preview counts
    python manage.py migrate_s3_to_cloudinary --apply          # do the migration
    python manage.py migrate_s3_to_cloudinary --apply --model products.Product
"""
from django.apps import apps
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# (app_label.Model, field_name) pairs to migrate.
TARGETS = [
    ('products.Category', 'image'),
    ('products.Product', 'image'),
    ('products.Product', 'thumbnail'),
    ('products.ProductImage', 'image'),
    ('products.ProductCombo', 'image'),
    ('products.ProductCombo', 'thumbnail'),
    ('users.User', 'profile_picture'),
    ('support.ChatMessage', 'attachment'),
]


def _build_s3_storage():
    """Instantiate an S3 storage pointed at the legacy media/ location.

    `default_storage` is now Cloudinary, so we need an explicit S3 client to
    read the original bytes. Mirrors the S3 STORAGES["default"] OPTIONS in
    settings.py (location="media").
    """
    from storages.backends.s3boto3 import S3Boto3Storage
    return S3Boto3Storage(location='media')


def _looks_like_cloudinary(name):
    """A field already migrated stores a Cloudinary public id / URL."""
    if not name:
        return True  # empty field: nothing to migrate
    return 'res.cloudinary.com' in name or name.startswith('ngu/') or '/ngu/' in name


class Command(BaseCommand):
    help = 'Copy existing S3 media into Cloudinary and rewrite DB references.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually upload and write changes. Without this, only previews.',
        )
        parser.add_argument(
            '--model', default=None,
            help='Limit to one "app_label.Model" (e.g. products.Product).',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        only_model = options['model']

        targets = TARGETS
        if only_model:
            targets = [t for t in TARGETS if t[0].lower() == only_model.lower()]
            if not targets:
                raise CommandError(
                    f'No image/file fields registered for model "{only_model}". '
                    f'Known models: {sorted({t[0] for t in TARGETS})}'
                )

        try:
            s3_storage = _build_s3_storage()
        except Exception as exc:  # noqa: BLE001 - surface a clear setup error
            raise CommandError(
                f'Could not initialise S3 storage (needed to read source files): {exc}. '
                f'Ensure boto3/django-storages are installed and AWS_* env vars are set.'
            )

        mode = 'APPLY' if apply_changes else 'DRY RUN'
        self.stdout.write(self.style.MIGRATE_HEADING(f'S3 -> Cloudinary migration [{mode}]'))

        totals = {'migrated': 0, 'skipped': 0, 'missing': 0, 'errors': 0}

        for label, field_name in targets:
            model = apps.get_model(label)
            qs = model.objects.exclude(**{field_name: ''}).exclude(**{f'{field_name}__isnull': True})
            count = qs.count()
            self.stdout.write(f'\n{label}.{field_name}: {count} row(s) with a file')

            for obj in qs.iterator():
                field_file = getattr(obj, field_name)
                name = getattr(field_file, 'name', None)

                if _looks_like_cloudinary(name):
                    totals['skipped'] += 1
                    continue

                if not s3_storage.exists(name):
                    totals['missing'] += 1
                    self.stdout.write(self.style.WARNING(f'  MISSING in S3: {label}#{obj.pk} {name}'))
                    continue

                if not apply_changes:
                    totals['migrated'] += 1
                    self.stdout.write(f'  would migrate: {label}#{obj.pk} {name}')
                    continue

                try:
                    with s3_storage.open(name, 'rb') as fh:
                        data = fh.read()
                    with transaction.atomic():
                        # save() through the Cloudinary default storage uploads the
                        # bytes and updates obj.<field>.name to the new asset, then
                        # persists the row.
                        field_file.save(name, ContentFile(data), save=True)
                    totals['migrated'] += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  migrated: {label}#{obj.pk} -> {getattr(obj, field_name).url}'
                    ))
                except Exception as exc:  # noqa: BLE001 - keep going, report per row
                    totals['errors'] += 1
                    self.stdout.write(self.style.ERROR(f'  ERROR {label}#{obj.pk} {name}: {exc}'))

        self.stdout.write('\n' + self.style.MIGRATE_HEADING('Summary'))
        self.stdout.write(
            f"  migrated: {totals['migrated']}  skipped: {totals['skipped']}  "
            f"missing-in-s3: {totals['missing']}  errors: {totals['errors']}"
        )
        if not apply_changes:
            self.stdout.write(self.style.WARNING('\nDry run only — re-run with --apply to perform the migration.'))
