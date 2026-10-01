"""Issue credit notes for refunds that have none.

Companion to `backfill_invoices`: every `OrderRefund` whose order has an
invoice is owed a `CN/<FY>/<seq>` credit note. Run once after deploying
credit notes, then again any time `maybe_issue_credit_note_for_refund` may
have swallowed a failure.

    python manage.py backfill_credit_notes --dry-run    # report, change nothing
    python manage.py backfill_credit_notes              # issue them
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from orders.credit_notes import issue_credit_note_for_refund
from orders.models import OrderRefund


class Command(BaseCommand):
    help = "Issue credit notes for refunds that have none."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Report what would be issued without writing anything.")
        parser.add_argument(
            '--limit', type=int, default=None,
            help="Process at most this many refunds (oldest first).")

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']

        pks = list(OrderRefund.objects.filter(credit_note__isnull=True)
                   .order_by('created_at')
                   .values_list('pk', flat=True))
        if limit:
            pks = pks[:limit]
        self.stdout.write(f"{len(pks)} refund(s) without a credit note; checking each.")

        issued = skipped = failed = 0
        for refund in self._refunds_in_order(pks):
            has_invoice = hasattr(refund, '_invoice_exists') and refund._invoice_exists
            if not has_invoice:
                # Checked explicitly: the issuer returns None for these too, but
                # counting them as "skipped, no invoice" (rather than failed)
                # keeps the summary honest about what remains.
                from orders.models import Invoice
                if not Invoice.objects.filter(order_id=refund.order_id).exists():
                    skipped += 1
                    continue
            if dry_run:
                self.stdout.write(
                    f"  would issue for refund #{refund.pk} "
                    f"(order #{refund.order_id}, {refund.amount})")
                issued += 1
                continue
            try:
                with transaction.atomic():
                    note = issue_credit_note_for_refund(refund)
                if note is not None:
                    issued += 1
                    self.stdout.write(f"  {note.number}  refund #{refund.pk}")
                else:
                    skipped += 1
            except Exception as exc:  # noqa: BLE001 — report and keep going
                failed += 1
                self.stderr.write(
                    self.style.WARNING(f"  refund #{refund.pk} failed: {exc}"))

        verb = "Would issue" if dry_run else "Issued"
        msg = f"{verb} {issued} credit note(s); skipped {skipped} with no invoice."
        if failed:
            raise CommandError(f"{msg} {failed} FAILED — see the warnings above.")
        self.stdout.write(self.style.SUCCESS(msg))

    def _refunds_in_order(self, pks):
        BATCH = 200
        for start in range(0, len(pks), BATCH):
            chunk = pks[start:start + BATCH]
            batch = (OrderRefund.objects
                     .filter(pk__in=chunk)
                     .select_related('order')
                     .order_by('created_at'))
            for refund in batch:
                yield refund
