"""AP7b/S7: COD abuse guard — verified inbox, value cap, open-order cap."""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from orders.models import Order

User = get_user_model()

ADDR = {'shipping_address': '1 St', 'phone_number': '9999999999', 'payment_method': 'COD'}


def _bearer(api_client, user):
    token = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return api_client


def _add(api_client, product, qty=2):
    r = api_client.post('/api/cart/add_item/',
                        {'product_id': product.id, 'quantity': qty}, format='json')
    assert r.status_code == 200, r.data


def _open_cod_order(user, status='pending'):
    return Order.objects.create(
        user=user, shipping_address='1 St', phone_number='9999999999',
        payment_method='COD', subtotal=Decimal('240.00'), tax=Decimal('24.00'),
        total_amount=Decimal('264.00'), status=status,
    )


@pytest.mark.django_db
class TestCODGuard:
    def test_unverified_user_rejected(self, api_client, test_product):
        user = User.objects.create_user(username='uuv', email='uuv@example.com',
                                        password='TestPass123!')
        assert user.email_verified is False
        _add(_bearer(api_client, user), test_product)
        r = api_client.post('/api/orders/', ADDR, format='json')
        assert r.status_code == 400
        assert r.data['code'] == 'email_not_verified'
        assert Order.objects.filter(user=user).count() == 0

    def test_fourth_open_cod_rejected(self, authenticated_client, test_user, test_product):
        for _ in range(3):
            _open_cod_order(test_user)
        _add(authenticated_client, test_product)
        r = authenticated_client.post('/api/orders/', ADDR, format='json')
        assert r.status_code == 400
        assert r.data['code'] == 'cod_limit'

    def test_value_cap_rejected(self, api_client, test_user, test_product):
        token = RefreshToken.for_user(test_user)
        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        _add(api_client, test_product, qty=100)  # 100 x ~120 = ~12,000 > 5,000
        r = api_client.post('/api/orders/', ADDR, format='json')
        assert r.status_code == 400
        assert r.data['code'] == 'cod_value'

    def test_passing_cod_holds_stock(self, api_client, test_user, test_product):
        start = test_product.stock
        token = RefreshToken.for_user(test_user)
        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        _add(api_client, test_product, qty=2)
        r = api_client.post('/api/orders/', ADDR, format='json')
        assert r.status_code == 201, r.data
        test_product.refresh_from_db()
        assert test_product.stock == start - 2
