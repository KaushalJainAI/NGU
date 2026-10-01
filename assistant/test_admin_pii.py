"""AP8/S11: admin tools mask customer PII in model prompts by default."""
import json
import logging

import pytest

from assistant import admin_tools


@pytest.mark.django_db
class TestCustomerMasking:
    def test_find_customer_masks_by_default(self, test_admin, test_user):
        out = admin_tools.admin_find_customer(test_admin, {'query': 'testuser'})
        assert out['count'] >= 1
        row = out['customers'][0]
        assert row['customer_ref'] == f'CUST-{test_user.pk}'
        assert row['email_masked'] == 't***@example.com'
        assert 'phone' not in row
        assert 'email' not in row
        blob = json.dumps(out)
        assert test_user.email not in blob  # full address never in the prompt
        assert '1234567890' not in blob  # nor the phone

    def test_find_customer_unmasks_on_request_and_logs(self, test_admin, test_user, caplog):
        with caplog.at_level(logging.WARNING, logger='assistant.admin_tools'):
            out = admin_tools.admin_find_customer(
                test_admin, {'query': 'testuser', 'include_contact': True})
        row = out['customers'][0]
        assert row['email'] == test_user.email
        assert row['phone'] == '1234567890'
        assert any('unmasked' in m and str(test_admin.pk) in m for m in caplog.messages)

    def test_recent_orders_mask_customer(self, test_admin, test_user, test_order):
        out = admin_tools.admin_list_recent_orders(test_admin, {})
        assert out['count'] >= 1
        blob = json.dumps(out)
        assert test_user.email not in blob
        row = next(r for r in out['orders'] if r['order_number'] == f'ORD-{test_order.id:06d}')
        assert row['customer_ref'] == f'CUST-{test_user.pk}'

    def test_mask_email_edge_cases(self):
        assert admin_tools._mask_email('a@b.com') == 'a***@b.com'
        assert admin_tools._mask_email('') == '***'
        assert admin_tools._mask_email('no-at-sign') == '***'
