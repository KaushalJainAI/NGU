"""
Create a set of curated, recipe-sensible combos for the Nidhi Masala catalog.

The combos were designed from the live catalog, the pushponline.com combo
lineup (Kitchen Favourites box, Sprinkler combo, Chilli/Kashmiri combo, etc.)
and standard Indian-recipe logic (everyday tadka staples, chole base, pickle
kit, masala chai, papad set).

Pricing is COMPUTED from current catalog prices so it stays correct in any
environment:
  * combo.price          = DERIVED by the model — the sum of each component
                           size's regular (MRP) price -> strike-through. Nothing
                           to set here; attaching the items is what sets it.
  * combo.discount_price = a bundle deal a notch below the sum of the items'
                           current selling prices, rounded to a tidy ...9 ending.

Products are matched by a name fragment (case-insensitive). When a fragment
matches several products, an exact full-name match wins (so "Chana Masala"
resolves to the masala, not "Chana Masala Papad"). Idempotent: combos that
already exist (by name) are skipped.

    python manage.py create_curated_combos            # preview (dry run)
    python manage.py create_curated_combos --apply     # commit
"""
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from products.models import (
    Product, ProductCombo, ProductComboItem, ensure_default_variant_for,
)

# Extra discount applied to the sum of the items' *selling* prices to set the
# bundle deal, so a combo always beats buying the items separately.
EXTRA_BUNDLE_OFF = Decimal("0.08")


# Each item is matched by a distinctive substring of the product name.
COMBOS = [
    {
        "name": "Roz Ka Tadka - Everyday Kitchen Essentials",
        "title": "Roz Ka Tadka - Everyday Essentials",
        "subtitle": "4 daily staples every Indian kitchen needs",
        "description": (
            "The four spices behind almost every Indian meal - Turmeric, "
            "Coriander, Garam Masala and our signature Indore Jeeravan. Stock "
            "your kitchen for the whole month and save."
        ),
        "badge": "Bestseller",
        "is_featured": True,
        "items": ["turmeric", "coriander", "garam masala", "jeeravan"],
    },
    {
        "name": "Indore Chatpata - Chaat Sprinkler Combo",
        "title": "Indore Chatpata Sprinkler Combo",
        "subtitle": "Street-food finishers - sprinkle & enjoy",
        "description": (
            "Indore's famous chatpata trio - Jeeravan, Chaat Masala and Garadu "
            "Masala. Sprinkle over chaat, fruit, fries or roasted garadu for "
            "that authentic Sarafa-bazaar tang."
        ),
        "badge": "Indore Special",
        "is_featured": True,
        "items": ["jeeravan", "chat masala", "garadu"],
    },
    {
        "name": "Papad Lover's Hamper",
        "title": "Papad Lover's Hamper",
        "subtitle": "Papads + the masalas to make your own",
        "description": (
            "Crispy Chana and Moong papads paired with our papad masalas so you "
            "can roast, fry or roll your own at home. A perfect accompaniment "
            "for every thali."
        ),
        "badge": "Combo",
        "is_featured": False,
        "items": ["chana masala papad", "moong papad", "moong papad masala", "chana papad masala"],
    },
    {
        "name": "Achar Ghar - Pickle Making Kit",
        "title": "Achar Ghar - Pickle Making Kit",
        "subtitle": "Everything for homemade Indian pickles",
        "description": (
            "Make restaurant-grade aam, nimbu and hari mirch pickles at home. "
            "Our all-purpose Achar Masala plus dedicated green-chilli and lemon "
            "pickle blends - just add oil and sun."
        ),
        "badge": "Seasonal",
        "is_featured": False,
        "items": ["achar masala", "hari mirch achar", "nimbu chutney achar"],
    },
    {
        "name": "Teekha Trio - Red Chilli Collection",
        "title": "Teekha Trio - Red Chilli Collection",
        "subtitle": "Heat, colour & tempering in one box",
        "description": (
            "Three chillies, three jobs - fiery VIP Teja for heat, Desi Tadakan "
            "for the perfect chhaunk, and Kashmiri for a rich red colour without "
            "the burn. Every cook's chilli shelf, sorted."
        ),
        "badge": "Hot",
        "is_featured": True,
        "items": ["vip teja", "desi tadakan", "kashmiri mirch"],
    },
    {
        "name": "Chai Sutta - Masala Chai Combo",
        "title": "Chai Sutta - Masala Chai Combo",
        "subtitle": "Adrak-wali masala chai at home",
        "description": (
            "Brew the perfect cutting chai - our aromatic Tea Masala blend with "
            "pure Sonth (dry ginger) powder for that warming adrak kick on cold "
            "mornings."
        ),
        "badge": "New",
        "is_featured": False,
        "items": ["tea masala", "sonth"],
    },
    {
        "name": "Chole Chana Special",
        "title": "Chole Chana Special",
        "subtitle": "Restaurant-style chole at home",
        "description": (
            "The classic Punjabi chole base - Chana Masala for body, Garam Masala "
            "for warmth and Kasuri Methi for that dhaba aroma. Soak, pressure-cook "
            "and tadka your way to perfect chole."
        ),
        "badge": "Combo",
        "is_featured": False,
        "items": ["chana masala", "garam masala", "kasuri methi"],
    },
    {
        "name": "Kitchen King Box - Blended Masala Collection",
        "title": "Kitchen King Box - 5 Blended Masalas",
        "subtitle": "5 must-have blends for everyday cooking",
        "description": (
            "Our five most-loved ready blends in one value box - Pav Bhaji, "
            "Kitchen King, Chana, Garam and Chaat Masala. From sabzi to street "
            "food, you're covered all week."
        ),
        "badge": "Value Pack",
        "is_featured": True,
        "items": ["pav bhaji", "kitchen king", "chana masala", "garam masala", "chat masala"],
    },
]


class CommandMatchError(Exception):
    pass


def deal_price(sell_total):
    """A tidy bundle price below the items' selling total, ending in 9."""
    base = sell_total * (Decimal("1") - EXTRA_BUNDLE_OFF)
    n = int(base)
    n = n - (n % 10) + 9          # snap to nearest ...9
    if n > base:
        n -= 10
    return Decimal(max(n, 9))


class Command(BaseCommand):
    help = "Create curated recipe-sensible combos (idempotent). Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Commit the combos. Without this flag the command only previews.",
        )

    def _match_product(self, fragment):
        """Resolve a name fragment to exactly one product (exact match wins)."""
        frag = fragment.strip()
        matches = list(Product.objects.filter(name__icontains=frag))
        if not matches:
            raise CommandMatchError(f"no product matches '{fragment}'")
        if len(matches) == 1:
            return matches[0]
        exact = [p for p in matches if p.name.strip().lower() == frag.lower()]
        if len(exact) == 1:
            return exact[0]
        raise CommandMatchError(
            f"fragment '{fragment}' is ambiguous: " + ", ".join(p.name for p in matches)
        )

    def handle(self, *args, **options):
        apply = options["apply"]

        # The ProductCombo post_save signal spawns a background thread (own DB
        # connection) to build the search KB via the LLM. That thread can't see
        # this command's open transaction (FK error), and we don't want LLM
        # calls here anyway - the KB is regenerated with `populate_search_kb
        # --force` afterwards. Disabling background tasks mirrors test mode.
        prev_testing = getattr(settings, "TESTING", False)
        settings.TESTING = True
        try:
            self._run(apply)
        finally:
            settings.TESTING = prev_testing

    def _run(self, apply):
        created = skipped = 0
        try:
            with transaction.atomic():
                for spec in COMBOS:
                    if ProductCombo.objects.filter(name=spec["name"]).exists():
                        self.stdout.write(f"SKIP (exists): {spec['name']}")
                        skipped += 1
                        continue

                    # Price off the VARIANT, not the legacy Product columns.
                    # `ProductCombo.total_original_price` sums `variant__price`,
                    # so pricing the bundle from the product mirror would make
                    # the printed savings disagree with what the API reports the
                    # moment the mirror drifts.
                    resolved = [
                        ensure_default_variant_for(self._match_product(f))
                        for f in spec["items"]
                    ]

                    sell = sum((Decimal(str(v.final_price)) for v in resolved), Decimal("0"))
                    deal = deal_price(sell)

                    combo = ProductCombo(
                        name=spec["name"],
                        title=spec["title"],
                        subtitle=spec["subtitle"],
                        description=spec["description"],
                        badge=spec["badge"],
                        is_featured=spec["is_featured"],
                        is_active=True,
                        # No `price`: the MRP is derived from the components
                        # attached just below (sum of variant prices).
                        discount_price=deal,
                    )
                    combo.save()
                    for variant in resolved:
                        ProductComboItem.objects.create(
                            combo=combo, variant=variant, quantity=1)

                    # MRP is DERIVED from the components just attached, so it can
                    # only be read after they exist — there is no `price` to set
                    # on the combo itself any more. Guarded against a zero MRP
                    # (every component priced at 0), which would divide by zero.
                    mrp = combo.total_original_price
                    off = int((mrp - deal) / mrp * 100) if mrp else 0
                    self.stdout.write(self.style.SUCCESS(f"CREATE: {spec['name']}"))
                    self.stdout.write(
                        f"        MRP Rs{mrp} | buy-separately Rs{sell} | "
                        f"bundle Rs{deal} ({off}% off MRP, save Rs{sell - deal} vs separate)"
                    )
                    # `resolved` holds VARIANTS (sizes), not products — name the
                    # size, since that is what the combo actually bundles.
                    self.stdout.write("        items: " + ", ".join(
                        f"{v.product.name} ({v.formatted_weight})" for v in resolved))
                    created += 1

                if not apply:
                    transaction.set_rollback(True)
        except CommandMatchError as exc:
            self.stderr.write(self.style.ERROR(f"Aborted (nothing written): {exc}"))
            return

        self.stdout.write("")
        self.stdout.write(
            f"created={created} skipped={skipped} "
            f"total_combos_now={ProductCombo.objects.count()}"
        )
        if apply:
            self.stdout.write(self.style.SUCCESS(">>> COMMITTED."))
        else:
            self.stdout.write(self.style.WARNING(">>> DRY RUN - nothing written. Re-run with --apply."))
