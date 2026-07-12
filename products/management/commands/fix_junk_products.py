"""
Data fix: find and neutralise "junk" catalog products that were created by
accident — e.g. a logo/asset image uploaded as a product, which surfaces on the
storefront with a corrupted auto-slug like ``logo2-50000`` (name "logo2", weight
50000).

Matching is deliberately conservative. A product is flagged when EITHER:
  * its slug matches one of ``--slug`` (repeatable, exact), OR
  * its name matches ``--name-regex`` (default ``^\\s*logo\\d*\\s*$`` — a bare
    "logo" / "logo2" style name and nothing else).

Default action is DEACTIVATE (``is_active=False``): the product vanishes from the
storefront (all public querysets filter on ``is_active``) with zero cascade risk.
Pass ``--delete`` to remove the rows instead; because ``OrderItem.product`` is
``on_delete=PROTECT`` a product that was ever ordered cannot be deleted — those
are reported and left for ``--deactivate`` instead of failing the whole run.

Dry run by default; pass --apply to write.

    python manage.py fix_junk_products                       # preview matches
    python manage.py fix_junk_products --apply               # deactivate them
    python manage.py fix_junk_products --slug logo2-50000 --apply
    python manage.py fix_junk_products --delete --apply      # delete where safe
"""
import re

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError

from products.models import Product

DEFAULT_NAME_REGEX = r"^\s*logo\d*\s*$"


class Command(BaseCommand):
    help = "Deactivate (or delete) junk products with corrupted slugs/names."

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug", action="append", default=[],
            help="Exact slug to target (repeatable).",
        )
        parser.add_argument(
            "--name-regex", default=DEFAULT_NAME_REGEX,
            help=f"Case-insensitive name regex to match (default: {DEFAULT_NAME_REGEX!r}).",
        )
        parser.add_argument(
            "--delete", action="store_true",
            help="Delete rows instead of deactivating (skips ones protected by orders).",
        )
        parser.add_argument(
            "--apply", action="store_true",
            help="Actually write changes. Without it this is a dry run.",
        )

    def handle(self, *args, **opts):
        slugs = opts["slug"]
        name_regex = opts["name_regex"]
        do_delete = opts["delete"]
        apply = opts["apply"]

        try:
            re.compile(name_regex)
        except re.error as e:
            self.stderr.write(self.style.ERROR(f"Invalid --name-regex: {e}"))
            return

        q = Q()
        if slugs:
            q |= Q(slug__in=slugs)
        if name_regex:
            q |= Q(name__iregex=name_regex)
        if not q:
            self.stderr.write(self.style.ERROR("Nothing to match: pass --slug and/or --name-regex."))
            return

        matches = list(Product.objects.filter(q).order_by("id"))
        if not matches:
            self.stdout.write("No matching products found. Nothing to do.")
            return

        self.stdout.write(f"Matched {len(matches)} product(s):")
        for p in matches:
            order_refs = p.orderitem_set.count() if hasattr(p, "orderitem_set") else 0
            self.stdout.write(
                f"  #{p.id}  slug={p.slug!r}  name={p.name!r}  "
                f"is_active={p.is_active}  ordered={order_refs}x"
            )

        if not apply:
            action = "delete" if do_delete else "deactivate"
            self.stdout.write(self.style.WARNING(
                f"\nDRY RUN — would {action} the above. Re-run with --apply to commit."
            ))
            return

        deactivated = deleted = skipped = 0
        with transaction.atomic():
            for p in matches:
                if do_delete:
                    try:
                        with transaction.atomic():
                            p.delete()
                        deleted += 1
                        self.stdout.write(self.style.SUCCESS(f"Deleted #{p.id} {p.slug!r}"))
                    except ProtectedError:
                        # Referenced by an order — cannot delete; hide instead.
                        Product.objects.filter(pk=p.pk).update(is_active=False)
                        skipped += 1
                        self.stdout.write(self.style.WARNING(
                            f"#{p.id} {p.slug!r} is referenced by orders — deactivated instead of deleting."
                        ))
                else:
                    Product.objects.filter(pk=p.pk).update(is_active=False)
                    deactivated += 1
                    self.stdout.write(self.style.SUCCESS(f"Deactivated #{p.id} {p.slug!r}"))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. deleted={deleted} deactivated={deactivated} "
            f"protected-then-deactivated={skipped}"
        ))
        self.stdout.write(
            "Refresh the AI search KB so hidden products drop out of search:\n"
            "  python manage.py populate_search_kb --force"
        )
