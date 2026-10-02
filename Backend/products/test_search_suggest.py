"""AP1 regression: build_suggestions must not crash when a combo matches (A1).

ProductCombo has no `price` column (MRP is a @property), so .only('price')
raised FieldDoesNotExist.
"""
import pytest
from decimal import Decimal

from products.models import ProductCombo, ProductComboItem
from products.recommendations import build_suggestions


@pytest.mark.django_db
class TestBuildSuggestionsCombo:
    def test_product_and_combo_both_returned(self, test_product, test_combo):
        # Both fixtures share "Test" token; corpus is cache-isolated per test.
        result = build_suggestions('Test', limit=6)
        types = {(s['type'], s['id']) for s in result['suggestions']}
        assert ('product', test_product.id) in types
        assert ('combo', test_combo.id) in types

    def test_combo_without_discount_price(self, test_product, test_product2, test_category):
        from products.models import Product
        combo = ProductCombo.objects.create(
            name='No Discount Combo Pack',
            description='combo with no selling price set',
            discount_price=None,
            is_active=True,
        )
        ProductComboItem.objects.create(combo=combo, product=test_product, quantity=1)
        ProductComboItem.objects.create(combo=combo, product=test_product2, quantity=1)
        result = build_suggestions('No Discount', limit=6)
        row = next(s for s in result['suggestions'] if s['type'] == 'combo' and s['id'] == combo.id)
        combo.refresh_from_db()
        assert row['price'] == float(combo.final_price)
