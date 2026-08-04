"""Issue tax invoices for orders that are due one but don't have it.

Two jobs:

1. **Migration.** Every historical order that was paid or dispatched before
   invoices existed as records. They were being served a PDF numbered
   `ORD-{id}` that was regenerated from live data on every download; this gives
   each one a real number in the series and freezes its contents.
2. **Repair.** `maybe_issue_invoice` deliberately swallows failures so a bug in
   document generation can never roll back a payment capture. An order that hits
   such a bug ends up paid but uninvoiced; re-running this picks it up.

    python manage.py backfill_invoices --dry-run    # report, change nothing
    python manage.py backfill_invoices              # issue them
    python manage.py backfill_invoices --limit 100  # work in batches

Orders are processed OLDEST FIRST, so the numbers the series hands out follow
the order the supplies actually happened in. A series whose dates run backwards
against its numbers invites exactly the question you don't want asked.

Note the dates: a backfilled invoice is stamped `issued_at` = the order's own
date (the closest honest tax point available in hindsight), NOT today — but its
NUMBER comes from the series for whichever financial year that date falls in.
Backfilling across an April boundary therefore fills several series, each in its
own date order, which is the correct outcome.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from orders.invoicing import invoice_is_due, issue_invoice
from orders.models import Order


class Command(BaseCommand):
    help = "Issue tax invoices for paid/dispatched orders that have none."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Report what would be issued without writing anything.")
        parser.add_argument(
            '--limit', type=int, default=None,
            help="Process at most this many orders (oldest first).")

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']

        # Oldest first so the series runs in the same order as the supplies.
        # `invoice_is_due` does the per-order eligibility test — including the
        # "already has one" check — so this stays the single definition of when
        # an invoice is owed, shared with the live issuing paths.
        #
        # The PK list is materialised up front rather than streamed: the loop
        # CREATES the very rows the `invoice__isnull=True` filter selects on, so
        # iterating the live queryset would be reading a result set while
        # invalidating it. Order ids are small; even a large store's history is
        # a trivial list to hold.
        pks = list(Order.objects.filter(invoice__isnull=True)
                   .order_by('created_at')
                   .values_list('pk', flat=True))
        if limit:
            pks = pks[:limit]
        self.stdout.write(f"{len(pks)} order(s) without an invoice; checking each.")

        issued = skipped = failed = 0
        for order in self._orders_in_order(pks):
            if not invoice_is_due(order):
                skipped += 1
                continue
            if dry_run:
                self.stdout.write(
                    f"  would issue for order #{order.pk} "
                    f"({order.payment_method}/{order.status}, {order.total_amount})")
                issued += 1
                continue
            try:
                # Each order in its own transaction: one bad row must not roll
                # back the invoices already issued in this run.
                with transaction.atomic():
                    invoice, created = issue_invoice(order, when=order.created_at)
                if created:
                    issued += 1
                    self.stdout.write(f"  {invoice.number}  order #{order.pk}")
                else:
                    skipped += 1
            except Exception as exc:  # noqa: BLE001 — report and keep going
                failed += 1
                self.stderr.write(
                    self.style.WARNING(f"  order #{order.pk} failed: {exc}"))

        verb = "Would issue" if dry_run else "Issued"
        msg = f"{verb} {issued} invoice(s); skipped {skipped} not due."
        if failed:
            # Non-zero exit so a deploy script or cron notices. The run is
            # re-entrant, so the fix is to resolve the cause and run it again.
            raise CommandError(f"{msg} {failed} FAILED — see the warnings above.")
        self.stdout.write(self.style.SUCCESS(msg))

    def _orders_in_order(self, pks):
        """Yield the orders for `pks`, oldest first, in batches.

        Batched so a long history doesn't load every order (and its prefetched
        lines) at once, while still preserving the created_at ordering that the
        numbering depends on. The prefetches match what `build_invoice_snapshot`
        reads, so each order costs a constant number of queries rather than one
        per line.
        """
        BATCH = 200
        for start in range(0, len(pks), BATCH):
            chunk = pks[start:start + BATCH]
            batch = (Order.objects
                     .filter(pk__in=chunk)
                     .select_related('user', 'coupon')
                     .prefetch_related('items__components')
                     .order_by('created_at'))
            for order in batch:
                yield order
