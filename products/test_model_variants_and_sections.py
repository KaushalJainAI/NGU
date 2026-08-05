"""
Product model logic, multiple packaging variants, slug aliases, extra categories, and homepage sections.
"""
from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError
from rest_framework import status

from cart.models import Cart, CartItem
from conftest import create_test_image
from orders.models import Order, OrderItem
from products.models import (
    default_variant_for,
    Category,
    Product,
    ProductCombo,
    ProductSection,
    ProductSectionPlacement,
    ProductSlugAlias,
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


# --- From test_model_logic.py ---

@pytest.mark.django_db
class TestFinalPrice:
    def test_no_discount_uses_price(self, test_category):
        p = _product(test_category, price=Decimal("150.00"), discount_price=None)
        assert p.final_price == Decimal("150.00")

    def test_discount_used_when_set(self, test_category):
        p = _product(test_category, price=Decimal("150.00"), discount_price=Decimal("120.00"))
        assert p.final_price == Decimal("120.00")

    def test_zero_discount_price_is_falsy_falls_back_to_price(self, test_category):
        p = _product(test_category, price=Decimal("150.00"), discount_price=Decimal("0.00"))
        assert p.final_price == Decimal("150.00")


@pytest.mark.django_db
class TestDiscountPercentage:
    def test_clean_twenty_percent(self, test_category):
        p = _product(test_category, price=Decimal("150.00"), discount_price=Decimal("120.00"))
        assert p.discount_percentage == 20

    def test_rounds_to_nearest(self, test_category):
        p = _product(test_category, price=Decimal("3.00"), discount_price=Decimal("1.00"))
        assert p.discount_percentage == 67

    def test_no_discount_is_zero(self, test_category):
        p = _product(test_category, price=Decimal("100.00"), discount_price=None)
        assert p.discount_percentage == 0

    def test_equal_discount_is_zero(self, test_category):
        p = _product(test_category, price=Decimal("100.00"))
        p.discount_price = Decimal("100.00")
        assert p.discount_percentage == 0


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
        with pytest.raises(ValidationError):
            _product(test_category, stock=-1)


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
        a = Category.objects.create(name="Blends", is_active=True)
        b = Category.objects.create(name="Blends!", is_active=True)
        assert a.slug == "blends"
        assert b.slug != a.slug

    def test_combo_collision(self, db):
        a = ProductCombo.objects.create(name="Festive Box", is_active=True)
        b = ProductCombo.objects.create(name="Festive Box!", is_active=True)
        assert a.slug != b.slug

    def test_helper_excludes_self_on_update(self, test_category):
        p = _product(test_category, name="Stable", weight=Decimal("100.00"))
        same = _generate_unique_slug(Product, p.slug, fallback="product", current_pk=p.pk)
        assert same == p.slug

    def test_helper_empty_base_uses_fallback(self, db):
        assert _generate_unique_slug(Product, "", fallback="product") == "product"


@pytest.mark.django_db
class TestCartTotal:
    def test_empty_cart_is_zero(self, test_cart):
        assert test_cart.total_price == Decimal("0")
        assert test_cart.total_items == 0

    def test_sums_discounted_prices_times_quantity(self, test_cart, test_category):
        p1 = _product(test_category, name="A", price=Decimal("200.00"), discount_price=Decimal("150.00"))
        p2 = _product(test_category, name="B", price=Decimal("100.00"))
        CartItem.objects.create(cart=test_cart, product=p1, item_type="product", quantity=2)
        CartItem.objects.create(cart=test_cart, product=p2, item_type="product", quantity=3)
        assert test_cart.total_price == Decimal("600.00")
        assert test_cart.total_items == 5


# --- From test_variants.py ---

@pytest.fixture
def product_with_variants(db, test_product):
    # Every product is auto-given one default size (products.signals), so the
    # admin's first act is to EDIT that size, not add a second one beside it.
    # Creating a fresh 250g row here would leave the product with four sizes.
    default = default_variant_for(test_product.pk)
    default.weight = Decimal('250')
    default.unit = 'g'
    default.price = Decimal('150.00')
    default.discount_price = Decimal('120.00')
    default.stock = 100
    default.display_order = 0
    default.save()
    big = ProductVariant.objects.create(
        product=test_product, weight=Decimal('500'), unit='g',
        price=Decimal('280.00'), discount_price=Decimal('230.00'),
        stock=40, display_order=1,
    )
    huge = ProductVariant.objects.create(
        product=test_product, weight=Decimal('1'), unit='kg',
        price=Decimal('520.00'), stock=10, display_order=2,
    )
    return test_product, default, big, huge


@pytest.mark.django_db
class TestProductVariantAPI:
    base_url = '/api/products/'

    def test_detail_includes_variants(self, api_client, product_with_variants):
        product, default, big, huge = product_with_variants
        resp = api_client.get(f'{self.base_url}{product.slug}/')
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['variant_count'] == 3
        slugs = [v['slug'] for v in data['variants']]
        assert big.slug in slugs and huge.slug in slugs
        assert data['variants'][0]['id'] == default.id
        assert data['variants'][1]['id'] == big.id
        v500 = next(v for v in data['variants'] if v['id'] == big.id)
        assert v500['final_price'] == 230.0
        assert v500['formatted_weight'] == '500g'

    def test_variant_slug_resolves_to_product(self, api_client, product_with_variants):
        product, default, big, huge = product_with_variants
        resp = api_client.get(f'{self.base_url}{big.slug}/')
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['id'] == product.id
        assert data['selected_variant_id'] == big.id


@pytest.mark.django_db
class TestCartVariants:
    base_url = '/api/cart/'

    def test_legacy_variantless_line_is_still_updatable(
        self, authenticated_client, test_cart, test_product
    ):
        """A cart row added before its product had any size must stay editable.

        Every product now auto-gets a default size, so update_item resolves one
        and looks for a row carrying it — while the old row has variant=NULL.
        Without a fallback those rows answer 404 forever and the customer can
        neither change the quantity nor (via the same id) get rid of it.
        """
        from cart.models import CartItem
        CartItem.objects.create(
            cart=test_cart, product=test_product, item_type='product', quantity=2
        )
        resp = authenticated_client.post(
            f'{self.base_url}update_item/',
            {'product_id': test_product.id, 'item_type': 'product', 'quantity': 5},
            format='json',
        )
        assert resp.status_code == status.HTTP_200_OK
        line = CartItem.objects.get(cart=test_cart, product=test_product)
        assert line.quantity == 5

    def test_add_with_variant_uses_variant_price(self, authenticated_client, product_with_variants):
        product, default, big, huge = product_with_variants
        resp = authenticated_client.post(
            f'{self.base_url}add_item/',
            {'product_id': product.id, 'variant_id': big.id, 'quantity': 2},
            format='json',
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        item = data['items'][0]
        assert item['variant_id'] == big.id
        assert item['price'] == 230.0
        assert item['weight'] == '500g'
        assert data['summary']['subtotal'] == 460.0

    def test_default_variant_when_unspecified(self, authenticated_client, product_with_variants):
        product, default, big, huge = product_with_variants
        resp = authenticated_client.post(
            f'{self.base_url}add_item/',
            {'product_id': product.id, 'quantity': 1},
            format='json',
        )
        assert resp.status_code == status.HTTP_200_OK
        item = resp.json()['items'][0]
        assert item['variant_id'] == default.id

    def test_two_sizes_are_separate_lines(self, authenticated_client, product_with_variants):
        product, default, big, huge = product_with_variants
        authenticated_client.post(
            f'{self.base_url}add_item/',
            {'product_id': product.id, 'variant_id': big.id, 'quantity': 1},
            format='json',
        )
        resp = authenticated_client.post(
            f'{self.base_url}add_item/',
            {'product_id': product.id, 'variant_id': huge.id, 'quantity': 1},
            format='json',
        )
        data = resp.json()
        assert len(data['items']) == 2
        variant_ids = {i['variant_id'] for i in data['items']}
        assert variant_ids == {big.id, huge.id}

    def test_variant_stock_enforced(self, authenticated_client, product_with_variants):
        product, default, big, huge = product_with_variants
        resp = authenticated_client.post(
            f'{self.base_url}add_item/',
            {'product_id': product.id, 'variant_id': huge.id, 'quantity': 999},
            format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestOrderVariants:
    base_url = '/api/orders/'

    def test_order_decrements_variant_stock_and_mirrors_default(
        self, authenticated_client, test_user, product_with_variants
    ):
        product, default, big, huge = product_with_variants
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, product=product, variant=big,
                                item_type='product', quantity=3)
        CartItem.objects.create(cart=cart, product=product, variant=default,
                                item_type='product', quantity=2)

        resp = authenticated_client.post(
            self.base_url,
            {'shipping_address': '1 Test Rd', 'phone_number': '1234567890',
             'payment_method': 'COD'},
            format='json',
        )
        assert resp.status_code == status.HTTP_201_CREATED

        big.refresh_from_db()
        default.refresh_from_db()
        product.refresh_from_db()
        assert big.stock == 37
        assert default.stock == 98
        assert product.stock == 98

        oi = OrderItem.objects.get(order_id=resp.json()['order_id'], variant=big)
        assert oi.product_weight == '500g'
        assert oi.price == Decimal('230.00')
        assert oi.variant_id == big.id

    def test_cancel_restores_variant_stock(
        self, authenticated_client, test_user, product_with_variants
    ):
        product, default, big, huge = product_with_variants
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, product=product, variant=big,
                                item_type='product', quantity=5)
        order_id = authenticated_client.post(
            self.base_url,
            {'shipping_address': '1 Test Rd', 'phone_number': '1234567890',
             'payment_method': 'COD'},
            format='json',
        ).json()['order_id']
        big.refresh_from_db()
        assert big.stock == 35

        authenticated_client.post(f'{self.base_url}{order_id}/cancel/')
        big.refresh_from_db()
        assert big.stock == 40


# --- From test_slug_aliases.py ---

@pytest.fixture
def product(test_product):
    return test_product


@pytest.mark.django_db
class TestSlugAlias:
    def test_renaming_records_the_old_slug(self, product):
        original = product.slug

        product.slug = "kitchen-king-masala-new"
        product.save()

        assert ProductSlugAlias.objects.filter(
            slug=original, product=product
        ).exists()

    def test_old_slug_still_resolves_to_the_product(self, client, product):
        original = product.slug
        product.slug = "kitchen-king-masala-new"
        product.save()

        response = client.get(f"/api/products/{original}/")

        assert response.status_code == 200
        assert response.json()["slug"] == "kitchen-king-masala-new"

    def test_canonical_slug_still_resolves(self, client, product):
        response = client.get(f"/api/products/{product.slug}/")

        assert response.status_code == 200

    def test_unknown_slug_still_404s(self, client, product):
        response = client.get("/api/products/no-such-product/")

        assert response.status_code == 404

    def test_reusing_a_retired_slug_clears_the_alias(self, product):
        original = product.slug
        product.slug = "temporary-slug"
        product.save()
        assert ProductSlugAlias.objects.filter(slug=original).exists()

        product.slug = original
        product.save()

        assert not ProductSlugAlias.objects.filter(slug=original).exists()
        assert ProductSlugAlias.objects.filter(slug="temporary-slug").exists()

    def test_multiple_renames_all_keep_resolving(self, client, product):
        first = product.slug
        product.slug = "second-slug"
        product.save()
        product.slug = "third-slug"
        product.save()

        for old in (first, "second-slug"):
            assert client.get(f"/api/products/{old}/").status_code == 200


# --- From test_extra_categories.py ---

@pytest.fixture
def sprinklers(db):
    return Category.objects.create(
        name="Secondary Shelf (test)",
        description="A second category to list a product under",
        is_active=True,
    )


@pytest.mark.django_db
class TestExtraCategories:
    def test_listed_under_its_canonical_category(self, client, test_product):
        response = client.get(f"/api/products/?category={test_product.category_id}")

        ids = [p["id"] for p in response.json()]
        assert test_product.id in ids

    def test_also_listed_under_a_secondary_category(
        self, client, test_product, sprinklers
    ):
        test_product.extra_categories.add(sprinklers)

        response = client.get(f"/api/products/?category={sprinklers.id}")

        ids = [p["id"] for p in response.json()]
        assert test_product.id in ids

    def test_secondary_category_does_not_change_the_canonical_one(
        self, test_product, sprinklers
    ):
        original = test_product.category_id
        test_product.extra_categories.add(sprinklers)
        test_product.refresh_from_db()

        assert test_product.category_id == original

    def test_not_listed_under_an_unrelated_category(
        self, client, test_product, sprinklers
    ):
        other = Category.objects.create(
            name="Totally Unrelated Shelf",
            description="Nothing here",
            is_active=True,
        )

        response = client.get(f"/api/products/?category={other.id}")

        ids = [p["id"] for p in response.json()]
        assert test_product.id not in ids

    def test_appears_once_not_duplicated(self, client, test_product, sprinklers):
        test_product.extra_categories.add(sprinklers)

        response = client.get(f"/api/products/?category={sprinklers.id}")

        ids = [p["id"] for p in response.json()]
        assert ids.count(test_product.id) == 1


# --- From test_sections.py ---

@pytest.mark.django_db
class TestSectionCrud:
    def test_staff_can_create_section(self, admin_client):
        resp = admin_client.post('/api/product-sections/', {
            'name': 'Festival Picks', 'section_type': 'custom', 'max_products': 8,
        }, format='json')
        assert resp.status_code == 201
        assert ProductSection.objects.filter(name='Festival Picks').exists()

    def test_customer_cannot_create_section(self, authenticated_client):
        resp = authenticated_client.post('/api/product-sections/', {
            'name': 'Hax', 'section_type': 'custom',
        }, format='json')
        assert resp.status_code == 403

    def test_delete_soft_hides(self, admin_client):
        section = ProductSection.objects.create(name='Temp', section_type='custom')
        resp = admin_client.delete(f'/api/product-sections/{section.id}/')
        assert resp.status_code == 204
        section.refresh_from_db()
        assert section.is_active is False

    def test_set_and_reorder_products(self, admin_client, test_product, test_product2):
        section = ProductSection.objects.create(name='Row', section_type='custom')
        resp = admin_client.put(
            f'/api/product-sections/{section.id}/products/',
            {'product_ids': [test_product2.id, test_product.id]}, format='json')
        assert resp.status_code == 200
        positions = {p['id']: p['position'] for p in resp.data}
        assert positions[test_product2.id] == 0
        assert positions[test_product.id] == 1
        assert ProductSectionPlacement.objects.filter(section=section).count() == 2

        resp = admin_client.put(
            f'/api/product-sections/{section.id}/products/',
            {'product_ids': [test_product.id, test_product2.id]}, format='json')
        positions = {p['id']: p['position'] for p in resp.data}
        assert positions[test_product.id] == 0

    def test_unknown_product_id_rejected(self, admin_client):
        section = ProductSection.objects.create(name='Row2', section_type='custom')
        resp = admin_client.put(
            f'/api/product-sections/{section.id}/products/',
            {'product_ids': [999999]}, format='json')
        assert resp.status_code == 400

    def test_get_products_is_public(self, api_client, test_product):
        section = ProductSection.objects.create(name='Pub', section_type='custom')
        ProductSectionPlacement.objects.create(section=section, product=test_product, position=0)
        resp = api_client.get(f'/api/product-sections/{section.id}/products/')
        assert resp.status_code == 200
        assert resp.data[0]['id'] == test_product.id


@pytest.fixture
def section(db):
    return ProductSection.objects.create(name="Trending Now", section_type="trending")


@pytest.fixture
def section2(db):
    return ProductSection.objects.create(name="Best Sellers", section_type="bestseller")


@pytest.mark.django_db
class TestProductSectionList:
    def test_list_returns_sections(self, admin_client, section, section2):
        resp = admin_client.get("/api/product-sections/")
        assert resp.status_code == 200
        names = {s["name"] for s in resp.data}
        assert {"Trending Now", "Best Sellers"} <= names

    def test_list_is_public_readable(self, api_client, section):
        resp = api_client.get("/api/product-sections/")
        assert resp.status_code == 200


@pytest.mark.django_db
class TestProductSectionPlacement:
    def test_admin_sets_product_sections(self, admin_client, test_product, section, section2):
        resp = admin_client.patch(
            f"/api/products/{test_product.slug}/",
            {"sections": [section.id, section2.id]},
            format="json",
        )
        assert resp.status_code == 200
        assert set(test_product.sections.values_list("id", flat=True)) == {section.id, section2.id}
        assert set(resp.data["sections"]) == {section.id, section2.id}
        assert "Trending Now" in resp.data["section_names"]

    def test_admin_clears_product_sections(self, admin_client, test_product, section):
        test_product.sections.set([section])
        resp = admin_client.patch(
            f"/api/products/{test_product.slug}/",
            {"sections": []},
            format="json",
        )
        assert resp.status_code == 200
        assert test_product.sections.count() == 0

    def test_absent_sections_left_untouched(self, admin_client, test_product, section):
        test_product.sections.set([section])
        resp = admin_client.patch(
            f"/api/products/{test_product.slug}/",
            {"badge": "NEW"},
            format="json",
        )
        assert resp.status_code == 200
        assert set(test_product.sections.values_list("id", flat=True)) == {section.id}

    def test_admin_sets_combo_sections(self, admin_client, test_combo, section):
        resp = admin_client.patch(
            f"/api/combos/{test_combo.slug}/",
            {"sections": [section.id]},
            format="json",
        )
        assert resp.status_code == 200
        assert set(test_combo.sections.values_list("id", flat=True)) == {section.id}

    def test_non_admin_cannot_set_sections(self, authenticated_client, test_product, section):
        resp = authenticated_client.patch(
            f"/api/products/{test_product.slug}/",
            {"sections": [section.id]},
            format="json",
        )
        assert resp.status_code in (401, 403)
        assert test_product.sections.count() == 0
