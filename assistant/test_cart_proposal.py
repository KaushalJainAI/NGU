"""AP10: size-aware tools, cart proposals, offers/delivery/tracking/policy."""
from decimal import Decimal

import pytest

from assistant import tools as toolkit
from products.models import ProductVariant


@pytest.fixture
def sized_product(db, test_category):
    from products.models import Product
    from conftest import create_test_image
    p = Product.objects.create(
        name='Sized Haldi Powder', category=test_category, description='sized',
        price=Decimal('100.00'), stock=50, weight=Decimal('100.00'), unit='g',
        spice_form='powder', is_active=True, image=create_test_image('s.jpg'))
    # Demote any signal-created default, then own two explicit sizes.
    ProductVariant.objects.filter(product=p).update(is_default=False)
    v100 = ProductVariant.objects.create(product=p, weight=Decimal('100.00'), unit='g',
                                         price=Decimal('100.00'), stock=10,
                                         is_default=True, is_active=True)
    v500 = ProductVariant.objects.create(product=p, weight=Decimal('500.00'), unit='g',
                                         price=Decimal('450.00'), stock=5,
                                         is_active=True)
    return p, v100, v500


@pytest.mark.django_db
class TestSizeAwareSearch:
    def test_search_rows_carry_variants(self, sized_product):
        p, v100, v500 = sized_product
        out = toolkit.tool_search_products(None, {'query': 'Sized Haldi'})
        row = next(r for r in out['results'] if r['id'] == p.id)
        by_id = {v['variant_id']: v for v in row['variants']}
        assert by_id[v500.id]['weight'] == v500.formatted_weight
        assert by_id[v500.id]['price'] == float(v500.final_price)
        assert by_id[v100.id]['in_stock'] is True


@pytest.mark.django_db
class TestVariantProposals:
    def test_add_to_cart_pins_variant(self, test_user, sized_product):
        p, v100, v500 = sized_product
        action, err = toolkit.build_add_to_cart(
            test_user, {'product_id': p.id, 'variant_id': v500.id, 'quantity': 2})
        assert err is None
        assert action['variant_id'] == v500.id
        assert action['quantity'] == 2
        assert '500' in action['label']

    def test_mismatched_variant_rejected(self, test_user, sized_product, test_product2):
        p, _, _ = sized_product
        action, err = toolkit.build_add_to_cart(
            test_user, {'product_id': test_product2.id,
                        'variant_id': p.variants.first().id, 'quantity': 1})
        assert action is None and err

    def test_cart_proposal_multi_line(self, test_user, sized_product, test_product2):
        p, v100, v500 = sized_product
        action, err = toolkit.build_cart_proposal(test_user, {'lines': [
            {'product_id': p.id, 'variant_id': v500.id, 'quantity': 2},
            {'product_id': test_product2.id, 'quantity': 1},
        ], 'note': 'weekly list'})
        assert err is None
        assert action['type'] == 'cart_proposal'
        assert len(action['lines']) == 2
        assert action['lines'][0]['variant_id'] == v500.id
        assert action['note'] == 'weekly list'

    def test_cart_proposal_all_or_nothing(self, test_user, sized_product):
        p, v100, _ = sized_product
        action, err = toolkit.build_cart_proposal(test_user, {'lines': [
            {'product_id': p.id, 'variant_id': v100.id, 'quantity': 1},
            {'product_id': p.id, 'variant_id': 999999, 'quantity': 1},
        ]})
        assert action is None and err

    def test_edit_cart_remove_line(self, test_user, sized_product):
        p, v100, _ = sized_product
        action, err = toolkit.build_edit_cart(
            test_user, {'lines': [{'variant_id': v100.id, 'quantity': 0}]})
        assert err is None
        assert action['type'] == 'edit_cart'
        assert action['lines'][0]['quantity'] == 0


@pytest.mark.django_db
class TestNewReadTools:
    def test_get_offers_lists_active_coupon(self, test_user, test_coupon):
        out = toolkit.tool_get_offers(test_user, {})
        codes = [o['code'] for o in out['offers']]
        assert 'TESTCOUPON10' in codes
        row = next(o for o in out['offers'] if o['code'] == 'TESTCOUPON10')
        assert 'usage_count' not in row and 'assigned' not in str(row)

    def test_get_delivery_info_matches_limits(self):
        out = toolkit.tool_get_delivery_info(None, {})
        assert out['fee_net'] == 59.0
        assert out['tax_rate'] == 18.0
        assert out['fee_total'] == 69.62
        assert out['free_above'] == 499.0

    def test_get_tracking_own_order(self, test_user, test_order):
        out = toolkit.tool_get_tracking(test_user, {'order_number': f'ORD-{test_order.id:06d}'})
        assert out['status'] == test_order.status
        assert out['route'] == '/my-orders'
        assert 'tracking_url' in out

    def test_get_tracking_other_user_not_found(self, test_user2, test_order):
        out = toolkit.tool_get_tracking(test_user2, {'order_number': f'ORD-{test_order.id:06d}'})
        assert out['error'] == 'not_found'

    def test_get_tracking_requires_login(self):
        assert toolkit.tool_get_tracking(None, {'order_number': 'ORD-000001'})['error'] == 'login_required'

    def test_get_policy_from_static_pages(self):
        out = toolkit.tool_get_policy(None, {'kind': 'shipping'})
        assert out['route'] == '/shipping-policy'
        assert '499' in out['content']
        ret = toolkit.tool_get_policy(None, {'kind': 'return'})
        assert ret['route'] == '/return-policy'
        assert '7 days' in ret['content']
        bad = toolkit.tool_get_policy(None, {'kind': 'privacy'})
        assert bad['error'] == 'bad_args'
