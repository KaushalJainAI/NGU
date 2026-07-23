"""Empty the admin Recycle Bin on a rolling retention window.

The admin panel's Recycle Bin holds soft-deleted items:
  * Orders    — is_deleted=True, timestamped by Order.deleted_at
  * Products  — is_active=False, timestamped by Product.deactivated_at
  * Combos    — is_active=False, timestamped by ProductCombo.deactivated_at

Each item is purged permanently once it has sat in the bin longer than
RECYCLE_BIN_RETENTION_DAYS (default 30) — a rolling, per-item countdown from the
moment it was deleted, NOT a fixed calendar sweep. Restoring an item clears its
timestamp, so the clock only ever runs while the item is actually in the bin.

    python manage.py purge_recycle_bin            # honour the retention setting
    python manage.py purge_recycle_bin --days 7   # override the window
    python manage.py purge_recycle_bin --dry-run  # report, change nothing

The scheduler runs this nightly (see run_scheduler). Set the retention to 0 to
disable purging entirely.

Deletion is permanent:
  * Orders cascade to their line items, payment, and payment events (all FKs are
    on_delete=CASCADE). Orders are financial records — this is deliberate and
    irreversible; it runs only because the store opted into purging orders too.
  * Products/combos that appear in ANY historical order are protected at the DB
    level (OrderItem FKs are on_delete=PROTECT). Those CANNOT be deleted, so the
    job skips them (they simply stay in the bin) instead of failing.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import ProtectedError
from django.utils import timezone

from orders.models import Order, OrderItem
from products.models import Product, ProductCombo


class Command(BaseCommand):
    help = "Permanently delete Recycle Bin items older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=None,
            help="Override RECYCLE_BIN_RETENTION_DAYS (the retention window).")
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Report what would be purged without deleting anything.")

    def handle(self, *args, **options):
        days = options['days']
        if days is None:
            days = getattr(settings, 'RECYCLE_BIN_RETENTION_DAYS', 30)
        dry_run = options['dry_run']

        if days <= 0:
            self.stdout.write("Recycle Bin retention is disabled (days <= 0); nothing purged.")
            return

        cutoff = timezone.now() - timedelta(days=days)
        self.stdout.write(
            f"Purging Recycle Bin items deleted before {cutoff.isoformat()} "
            f"(retention {days} days){' [dry-run]' if dry_run else ''}.")

        orders = self._purge_orders(cutoff, dry_run)
        products = self._purge_soft_deleted(Product, cutoff, dry_run, "product")
        combos = self._purge_soft_deleted(ProductCombo, cutoff, dry_run, "combo")

        verb = "Would purge" if dry_run else "Purged"
        self.stdout.write(self.style.SUCCESS(
            f"{verb}: {orders} order(s), {products} product(s), {combos} combo(s)."))

    def _purge_orders(self, cutoff, dry_run):
        """Hard-delete soft-deleted orders past the cutoff (cascades line items,
        payment, and payment events)."""
        qs = Order.objects.filter(is_deleted=True, deleted_at__lt=cutoff)
        count = qs.count()
        if count and not dry_run:
            # Iterate so each Order's CASCADE runs through the ORM (collectors),
            # matching how the app deletes elsewhere; the volume here is tiny.
            for order in qs.iterator():
                order.delete()
        return count

    def _purge_soft_deleted(self, model, cutoff, dry_run, label):
        """Hard-delete soft-deleted (is_active=False) products/combos past the
        cutoff, skipping any protected by a historical order reference."""
        qs = model.objects.filter(
            is_active=False, deactivated_at__isnull=False, deactivated_at__lt=cutoff)
        # OrderItem.product / .combo are on_delete=PROTECT, so an item referenced
        # by any order can never be hard-deleted. Which relation depends on the
        # model; check it up front so the dry-run reports the same count the real
        # run would actually purge.
        ref_field = 'product' if model is Product else 'combo'
        purged = 0
        for obj in qs.iterator():
            if OrderItem.objects.filter(**{ref_field: obj}).exists():
                self.stdout.write(
                    f"  {'would skip' if dry_run else 'skipped'} {label} #{obj.pk} "
                    f"'{obj.name}' — referenced by an order.")
                continue
            if dry_run:
                purged += 1
                continue
            try:
                obj.delete()
                purged += 1
            except ProtectedError:
                # Belt-and-braces: a reference created between the check and the
                # delete still can't be hard-deleted — leave it in the bin.
                self.stdout.write(
                    f"  skipped {label} #{obj.pk} '{obj.name}' — referenced by an order.")
        return purged
