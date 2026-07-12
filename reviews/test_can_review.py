"""
The /reviews/can-review/ eligibility hint used by the storefront to decide
whether to show the write-a-review form.

It must agree with the verified-purchase gate enforced in perform_create — a
True here that the POST would reject (or vice versa) is the bug this endpoint
exists to avoid.
"""
from decimal import Decimal

import pytest

from orders.models import Order, OrderItem

URL = "/api/reviews/can-review/"
CREATE_URL = "/api/reviews/"


def _order_with(product, user, status):
    order = Order.objects.create(
        user=user, shipping_address="1 Rd", phone_number="1234567890",
        payment_method="COD", subtotal=Decimal("120.00"), tax=Decimal("6.00"),
        total_amount=Decimal("126.00"), status=status,
    )
    OrderItem.objects.create(
        order=order, product=product, item_type="product",
        product_name=product.name, product_weight=product.weight,
        quantity=1, price=product.final_price, final_price=product.final_price,
    )
    return order


@pytest.mark.django_db
class TestCanReview:
    def test_requires_authentication(self, api_client, test_product):
        r = api_client.get(f"{URL}?product={test_product.id}")
        assert r.status_code in (401, 403)

    def test_never_purchased(self, authenticated_client, test_product):
        r = authenticated_client.get(f"{URL}?product={test_product.id}")
        assert r.status_code == 200
        assert r.json() == {"can_review": False, "reason": "not_purchased"}

    @pytest.mark.parametrize("good_status", ["confirmed", "processing", "shipped", "delivering", "delivered"])
    def test_purchased_can_review(self, authenticated_client, test_user, test_product, good_status):
        _order_with(test_product, test_user, good_status)
        r = authenticated_client.get(f"{URL}?product={test_product.id}")
        assert r.json() == {"can_review": True, "reason": None}

    @pytest.mark.parametrize("bad_status", ["pending", "cancelled"])
    def test_unfulfilled_order_cannot_review(self, authenticated_client, test_user, test_product, bad_status):
        _order_with(test_product, test_user, bad_status)
        r = authenticated_client.get(f"{URL}?product={test_product.id}")
        assert r.json() == {"can_review": False, "reason": "not_purchased"}

    def test_another_users_purchase_does_not_count(self, authenticated_client, test_user2, test_product):
        _order_with(test_product, test_user2, "delivered")
        r = authenticated_client.get(f"{URL}?product={test_product.id}")
        assert r.json() == {"can_review": False, "reason": "not_purchased"}

    def test_already_reviewed(self, authenticated_client, test_user, test_product):
        _order_with(test_product, test_user, "delivered")
        created = authenticated_client.post(
            CREATE_URL,
            {"item_type": "product", "product": test_product.id, "rating": 5,
             "title": "Nice", "comment": "Fresh and aromatic"},
            format="json",
        )
        assert created.status_code == 201
        r = authenticated_client.get(f"{URL}?product={test_product.id}")
        assert r.json() == {"can_review": False, "reason": "already_reviewed"}

    def test_agrees_with_create_endpoint_when_not_purchased(self, authenticated_client, test_product):
        """can_review False => the POST it guards must also reject."""
        assert authenticated_client.get(f"{URL}?product={test_product.id}").json()["can_review"] is False
        posted = authenticated_client.post(
            CREATE_URL,
            {"item_type": "product", "product": test_product.id, "rating": 5,
             "title": "Nice", "comment": "Fresh"},
            format="json",
        )
        assert posted.status_code == 400

    def test_missing_params_rejected(self, authenticated_client):
        assert authenticated_client.get(URL).status_code == 400

    def test_both_params_rejected(self, authenticated_client, test_product):
        r = authenticated_client.get(f"{URL}?product={test_product.id}&combo=1")
        assert r.status_code == 400

    def test_non_numeric_id_rejected(self, authenticated_client):
        assert authenticated_client.get(f"{URL}?product=abc").status_code == 400
