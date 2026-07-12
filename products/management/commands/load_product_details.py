"""
Populate recipe (how-to-use) text and the nutrition table for products, from the
curated pack-label data in product_details.json.

Keyed by DB product ID (names/slugs were normalised separately, IDs are stable).
Only non-empty values are written; nutrition keeps insertion order. For Safed
Mirch (id 36) the ingredients were blank in the DB, so its ingredients are filled
here too.

Dry run by default; pass --apply to write.

    python manage.py load_product_details            # preview
    python manage.py load_product_details --apply    # commit
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from products.models import Product

# id -> {recipe?, nutrition?, ingredients?}
DETAILS = {
    17: {"nutrition": {"serving_size": "100g", "total_fat": "5.0g", "saturated_fat": "0.0g",
                       "total_carbohydrates": "25.0g", "protein": "11.5g"}},
    18: {"recipe": ("Methi has always been a very important and tasty part of Indian cooking "
                    "which gives cooking a special flavour, taste and freshness. Nidhi Kasuri "
                    "Methi is a unique combination of these qualities. Sprinkle Nidhi Kasuri "
                    "Methi to enrich your dal and other dishes with a farm-fresh fragrance and "
                    "an unforgettable taste. Soak Nidhi Kasuri Methi for 30 min, then rinse it "
                    "to make a Methi-Aloo dish and enjoy the same freshness in every season."),
         "nutrition": {"serving_size": "100g", "total_fat": "3.8g", "total_carbohydrates": "3.9g",
                       "protein": "3.1g", "energy": "5.0 Kcal", "calcium": "500mg", "iron": "7.2mg"}},
    24: {},  # Amchur — no nutrition/recipe in source
    22: {"recipe": ("Add 2g of tea masala to your tea. Storage: keep the jar closed to preserve "
                    "freshness. Refrigeration is recommended for longer storage life."),
         "nutrition": {"serving_size": "100g", "total_fat": "Traces", "total_carbohydrates": "7g",
                       "protein": "19g", "energy": "105 Kcal"}},
    19: {"nutrition": {"serving_size": "100g", "total_fat": "9.5g", "total_carbohydrates": "33.3g",
                       "protein": "0.6g", "energy": "285.10 Kcal", "calcium": "650mg", "iron": "8.2mg"}},
    25: {"nutrition": {"serving_size": "100g", "total_fat": "0.5g", "total_carbohydrates": "60.79g",
                       "protein": "15.27g", "energy": "350.10 Kcal", "sodium": "2.0g"}},
    16: {"recipe": ("Sprinkle on samosa, pakora, roasted cashews, almonds, wafers, sandwiches, "
                    "tikki, papdi, chaat, fruit chaat, potato chaat, burgers, pizzas and all "
                    "roasted delicacies to enjoy a great taste."),
         "nutrition": {"serving_size": "100g", "total_fat": "9.51g", "total_carbohydrates": "33.5g",
                       "protein": "0.8g", "energy": "289.35 Kcal", "calcium": "640mg", "iron": "9.1mg"}},
    26: {"nutrition": {"serving_size": "5g", "total_fat": "0g", "total_carbohydrates": "4g",
                       "protein": "0g", "sugars": "0g", "sodium": "2mg"}},
    2:  {"nutrition": {"serving_size": "100g", "total_fat": "3.9g", "total_carbohydrates": "5.8g",
                       "protein": "15.4g", "energy": "130 Kcal", "sodium": "17.3g"}},
    23: {"recipe": "Contains an admixture of not more than 2% soyabean oil."},
    29: {"nutrition": {"serving_size": "100g", "total_fat": "0.5g", "total_carbohydrates": "60.79g",
                       "protein": "15.27g", "energy": "350.10 Kcal", "sodium": "2.0g"}},
    36: {"ingredients": "White Pepper",
         "nutrition": {"serving_size": "100g", "total_fat": "3.3g", "total_carbohydrates": "64g",
                       "protein": "10g", "energy": "325 Kcal"}},
}


class Command(BaseCommand):
    help = "Populate recipe + nutrition (and Safed Mirch ingredients) from curated pack data."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run).")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        changed = 0
        with transaction.atomic():
            for pid, data in DETAILS.items():
                if not data:
                    continue
                try:
                    p = Product.objects.get(id=pid)
                except Product.DoesNotExist:
                    self.stderr.write(self.style.WARNING(f"#{pid} not found — skipped"))
                    continue
                cols = {}
                labels = []
                # Write the base column AND the English translation column so
                # modeltranslation's fallback serves it in every language.
                if data.get("recipe") and not (p.recipe or "").strip():
                    cols["recipe"] = cols["recipe_en"] = data["recipe"]; labels.append("recipe")
                if data.get("nutrition") and not p.nutrition:
                    cols["nutrition"] = data["nutrition"]; labels.append("nutrition")
                if data.get("ingredients") and not (p.ingredients or "").strip():
                    cols["ingredients"] = cols["ingredients_en"] = data["ingredients"]; labels.append("ingredients")
                if not cols:
                    self.stdout.write(f"#{pid} {p.name!r}: nothing to fill (already set)")
                    continue
                changed += 1
                self.stdout.write(self.style.SUCCESS(f"#{pid} {p.name!r}: +{', '.join(labels)}"))
                if apply:
                    # Raw column update: no thumbnail regen / validation on a backfill.
                    Product.objects.filter(pk=pid).update(**cols)
            if not apply:
                self.stdout.write(self.style.WARNING("\nDRY RUN — re-run with --apply to commit."))
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(f"\n{'Applied' if apply else 'Would change'}: {changed} product(s)."))
