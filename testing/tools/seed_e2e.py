#!/usr/bin/env python
"""
Seed the file-backed e2e SQLite DB with a minimal catalog so the HTTP e2e suite
exercises real data (products list/detail, search, cart add, etc.).

Run from the Backend directory with the e2e settings:
    python ../testing/tools/seed_e2e.py
(the orchestrator sets DJANGO_SETTINGS_MODULE / cwd for you).
"""
import os
import sys
import django
from decimal import Decimal

# Ensure the Backend dir (which contains the `spices_backend` package) is on the
# path regardless of the cwd this script is invoked from.
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spices_backend.e2e_settings")
os.environ.setdefault("USE_CLOUDINARY", "False")
os.environ.setdefault("USE_S3", "False")
os.environ.setdefault("SECRET_KEY", "e2e-insecure-do-not-use-in-prod")
django.setup()

from datetime import timedelta  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.utils import timezone  # noqa: E402
from django.utils.text import slugify  # noqa: E402
from products.models import Category, Product  # noqa: E402
from admin_panel.models import Coupon  # noqa: E402

User = get_user_model()


def _seed_coupons():
    """Coupons the e2e coupon-message tests rely on (one per failure reason)."""
    specs = [
        # code, kwargs
        ("E2E10", dict(discount_percent=10, is_active=True,
                       valid_until=timezone.now() + timedelta(days=30))),
        ("E2EOLD", dict(discount_percent=10, is_active=True,
                        valid_until=timezone.now() - timedelta(days=1))),          # expired
        ("E2EMIN500", dict(discount_percent=10, is_active=True,
                           minimum_order_amount=Decimal("500.00"),
                           valid_until=timezone.now() + timedelta(days=30))),      # min-order
    ]
    for code, kw in specs:
        Coupon.objects.get_or_create(code=code, defaults=kw)


def run():
    cat, _ = Category.objects.get_or_create(
        name="Whole Spices",
        defaults={"description": "Whole spice seeds and pods", "is_active": True},
    )

    samples = [
        ("Turmeric Powder", "powder", Decimal("150.00"), Decimal("120.00"), 100),
        ("Cumin Seeds", "whole", Decimal("200.00"), None, 60),
        ("Garam Masala", "powder", Decimal("250.00"), Decimal("220.00"), 40),
        ("Red Chilli Powder", "powder", Decimal("180.00"), None, 0),  # out of stock
    ]
    # NOTE: we deliberately build objects and bulk_create them, bypassing
    # Product.save()'s custom slug-retry + full_clean() path which deadlocks on a
    # constraint-validation savepoint (see SECURITY_AUDIT.md F-1). bulk_create
    # issues a plain INSERT, so the seed is fast and reliable.
    to_create = []
    for name, form, price, disc, stock in samples:
        if Product.objects.filter(name=name).exists():
            continue
        to_create.append(Product(
            name=name,
            slug=slugify(f"{name}-250g"),
            category=cat,
            description=f"Premium {name.lower()} from Nidhi Masala.",
            price=price,
            discount_price=disc,
            stock=stock,
            weight=Decimal("250.00"),
            unit="g",
            spice_form=form,
            is_active=True,
            is_featured=(name == "Turmeric Powder"),
        ))
    if to_create:
        Product.objects.bulk_create(to_create)
    created = len(to_create)

    # An admin so admin-only guard tests have a real staff account to contrast.
    if not User.objects.filter(username="e2e_admin").exists():
        User.objects.create_superuser(
            username="e2e_admin", email="e2e_admin@example.com", password="AdminPass123!"
        )

    _seed_coupons()

    print(f"seed: categories={Category.objects.count()} "
          f"products={Product.objects.count()} coupons={Coupon.objects.count()} (new={created})")


if __name__ == "__main__":
    run()
