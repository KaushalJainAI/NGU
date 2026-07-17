"""
Pure model-logic unit tests for the catalogue.

These exercise the *business rules that live on the models* — pricing
properties, weight formatting, slug uniqueness (the F-1 fix), validation in
clean()/constraints, and the cart total aggregation — rather than the HTTP API.
The goal is industry-grade edge coverage: rounding/truncation, boundary values,
None handling, and collision behaviour.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from conftest import create_test_image
from products.models import (
    Category,
    Product,
    ProductCombo,
    ProductVariant,
    _generate_unique_slug,
)


def _product(category, **overrides):
    data = dict(
        name="Logic Spice",
        category=category,
        description="x",
        price=Decimal("100.00"),
        stock=10,
        weight=Decimal("250.00"),
        unit="g",
        spice_form="powder",
        is_active=True,
        image=create_test_image("logic.jpg"),
    )
    data.update(overrides)
    return Product.objects.create(**data)


# --------------------------------------------------------------------------- #
# final_price
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestFinalPrice:
    def test_no_discount_uses_price(self, test_category):
        p = _product(test_category, price=Decimal("150.00"), discount_price=None)
        assert p.final_price == Decimal("150.00")

    def test_discount_used_when_set(self, test_category):
        p = _product(test_category, price=Decimal("150.00"), discount_price=Decimal("120.00"))
        assert p.final_price == Decimal("120.00")

    def test_zero_discount_price_is_falsy_falls_back_to_price(self, test_category):
        # discount_price of 0 is falsy -> the property returns the regular price,
        # never a free product.
        p = _product(test_category, price=Decimal("150.00"), discount_price=Decimal("0.00"))
        assert p.final_price == Decimal("150.00")


# --------------------------------------------------------------------------- #
# discount_percentage  (rounded to nearest integer — matches frontend cards)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestDiscountPercentage:
    def test_clean_twenty_percent(self, test_category):
        p = _product(test_category, price=Decimal("150.00"), discount_price=Decimal("120.00"))
        assert p.discount_percentage == 20

    def test_rounds_to_nearest(self, test_category):
        # (2/3)*100 = 66.66… -> round() gives 67, matching what the frontend
        # product cards display (see commit 4ddc145: discount_percentage is
        # intentionally rounded, not truncated).
        p = _product(test_category, price=Decimal("3.00"), discount_price=Decimal("1.00"))
        assert p.discount_percentage == 67

    def test_no_discount_is_zero(self, test_category):
        p = _product(test_category, price=Decimal("100.00"), discount_price=None)
        assert p.discount_percentage == 0

    def test_equal_discount_is_zero(self, test_category):
        # discount == price is not "< price", so 0% (and clean() forbids it anyway)
        p = _product(test_category, price=Decimal("100.00"))
        p.discount_price = Decimal("100.00")
        assert p.discount_percentage == 0


# --------------------------------------------------------------------------- #
# in_stock + formatted_weight
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestStockAndWeight:
    def test_in_stock_true(self, test_category):
        assert _product(test_category, stock=1).in_stock is True

    def test_in_stock_false_at_zero(self, test_category):
        assert _product(test_category, stock=0).in_stock is False

    def test_formatted_weight_strips_trailing_zeros(self, test_category):
        assert _product(test_category, weight=Decimal("250.00"), unit="g").formatted_weight == "250g"

    def test_formatted_weight_keeps_fraction(self, test_category):
        assert _product(test_category, weight=Decimal("1.50"), unit="kg").formatted_weight == "1.5kg"

    def test_formatted_weight_integer_kg(self, test_category):
        assert _product(test_category, weight=Decimal("1.00"), unit="kg").formatted_weight == "1kg"


# --------------------------------------------------------------------------- #
# clean() / DB constraints
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestValidation:
    def test_discount_above_price_rejected(self, test_category):
        p = Product(
            name="Bad", category=test_category, description="x",
            price=Decimal("100.00"), discount_price=Decimal("150.00"),
            stock=5, weight=Decimal("100.00"), unit="g", spice_form="powder",
            image=create_test_image("bad.jpg"),
        )
        with pytest.raises(ValidationError):
            p.full_clean()

    def test_discount_equal_to_price_rejected(self, test_category):
        p = Product(
            name="Equal", category=test_category, description="x",
            price=Decimal("100.00"), discount_price=Decimal("100.00"),
            stock=5, weight=Decimal("100.00"), unit="g", spice_form="powder",
            image=create_test_image("eq.jpg"),
        )
        with pytest.raises(ValidationError):
            p.full_clean()

    def test_negative_stock_rejected(self, test_category):
        # stock_non_negative CheckConstraint is validated by full_clean()
        with pytest.raises(ValidationError):
            _product(test_category, stock=-1)


# --------------------------------------------------------------------------- #
# Slug uniqueness — the F-1 fix (bounded exists() instead of an infinite loop)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestUniqueSlug:
    def test_duplicate_product_names_get_distinct_slugs(self, test_category):
        a = _product(test_category, name="Garam Masala", weight=Decimal("250.00"))
        b = _product(test_category, name="Garam Masala", weight=Decimal("250.00"))
        c = _product(test_category, name="Garam Masala", weight=Decimal("250.00"))
        slugs = {a.slug, b.slug, c.slug}
        assert len(slugs) == 3
        assert a.slug and b.slug.endswith("-1") and c.slug.endswith("-2")

    def test_categories_collide_safely(self, db):
        # Category.name is unique, but distinct names can still slugify to the
        # same base ("Blends" and "Blends!" -> "blends"); slugs must stay unique.
        a = Category.objects.create(name="Blends", is_active=True)
        b = Category.objects.create(name="Blends!", is_active=True)
        assert a.slug == "blends"
        assert b.slug != a.slug

    def test_combo_collision(self, db):
        a = ProductCombo.objects.create(name="Festive Box", price=Decimal("500.00"), is_active=True)
        b = ProductCombo.objects.create(name="Festive Box!", price=Decimal("500.00"), is_active=True)
        assert a.slug != b.slug

    def test_helper_excludes_self_on_update(self, test_category):
        p = _product(test_category, name="Stable", weight=Decimal("100.00"))
        # Recomputing for the same row must not append a counter to its own slug.
        same = _generate_unique_slug(Product, p.slug, fallback="product", current_pk=p.pk)
        assert same == p.slug

    def test_helper_empty_base_uses_fallback(self, db):
        # slugify("---") -> "" so the fallback is used.
        assert _generate_unique_slug(Product, "", fallback="product") == "product"


# --------------------------------------------------------------------------- #
# Cart total aggregation
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestCartTotal:
    def test_empty_cart_is_zero(self, test_cart):
        assert test_cart.total_price == Decimal("0")
        assert test_cart.total_items == 0

    def test_sums_discounted_prices_times_quantity(self, test_cart, test_category):
        from cart.models import CartItem
        p1 = _product(test_category, name="A", price=Decimal("200.00"), discount_price=Decimal("150.00"))
        p2 = _product(test_category, name="B", price=Decimal("100.00"))
        CartItem.objects.create(cart=test_cart, product=p1, item_type="product", quantity=2)
        CartItem.objects.create(cart=test_cart, product=p2, item_type="product", quantity=3)
        # 150*2 + 100*3 = 600
        assert test_cart.total_price == Decimal("600.00")
        assert test_cart.total_items == 5
