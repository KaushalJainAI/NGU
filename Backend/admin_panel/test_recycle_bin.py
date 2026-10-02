"""Recycle Bin for hard-deleted rows: an admin DELETE snapshots the row into
DeletedRecord, and restore puts it back under its original id."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from admin_panel.models import Coupon, DeletedRecord, Expense, ReceivableAccount
from conftest import create_test_image
from products.models import ProductComboItem, ProductImage
from reviews.models import Review
from support.models import ContactSubmission

BIN = '/api/admin/recycle-bin/'


def _restore(client, record):
    return client.post(f'{BIN}{record.id}/restore/')


@pytest.mark.django_db
class TestCouponRecycle:
    def test_delete_moves_the_coupon_to_the_bin(self, admin_client, test_coupon, test_admin):
        resp = admin_client.delete(f'/api/coupons/{test_coupon.id}/')
        assert resp.status_code == 204
        assert not Coupon.objects.filter(pk=test_coupon.pk).exists()

        record = DeletedRecord.objects.get()
        assert record.kind == 'coupon'
        assert 'TESTCOUPON10' in record.label
        assert record.deleted_by == test_admin

    def test_restore_brings_it_back_with_the_same_id(self, admin_client, test_coupon):
        admin_client.delete(f'/api/coupons/{test_coupon.id}/')
        resp = _restore(admin_client, DeletedRecord.objects.get())
        assert resp.status_code == 200
        restored = Coupon.objects.get(pk=test_coupon.pk)
        assert restored.code == 'TESTCOUPON10'
        assert restored.discount_percent == 10
        assert not DeletedRecord.objects.exists()

    def test_restore_reattaches_the_orders_that_used_it(self, admin_client, test_coupon, test_order):
        """Order.coupon is SET_NULL, so deleting a coupon strips it off every
        order that used it. Restoring has to put that link back."""
        test_order.coupon = test_coupon
        test_order.save(update_fields=['coupon'])

        admin_client.delete(f'/api/coupons/{test_coupon.id}/')
        test_order.refresh_from_db()
        assert test_order.coupon_id is None

        _restore(admin_client, DeletedRecord.objects.get())
        test_order.refresh_from_db()
        assert test_order.coupon_id == test_coupon.pk

    def test_restore_refuses_when_the_code_was_reused(self, admin_client, test_coupon):
        admin_client.delete(f'/api/coupons/{test_coupon.id}/')
        Coupon.objects.create(code='TESTCOUPON10', discount_percent=5)

        record = DeletedRecord.objects.get()
        resp = _restore(admin_client, record)
        assert resp.status_code == 409
        assert 'unique' in resp.data['error']
        # Refused cleanly: the entry stays so the admin can retry later.
        assert DeletedRecord.objects.filter(pk=record.pk).exists()
        assert Coupon.objects.filter(code='TESTCOUPON10').count() == 1

    def test_restoring_twice_is_a_404_not_a_duplicate(self, admin_client, test_coupon):
        admin_client.delete(f'/api/coupons/{test_coupon.id}/')
        record = DeletedRecord.objects.get()
        assert _restore(admin_client, record).status_code == 200
        assert _restore(admin_client, record).status_code == 404
        assert Coupon.objects.filter(code='TESTCOUPON10').count() == 1


@pytest.mark.django_db
class TestOtherKinds:
    def test_expense(self, admin_client, test_admin):
        expense = Expense.objects.create(
            date=date(2026, 9, 1), category='packaging', vendor='Box Co',
            amount=Decimal('1180.00'), gst_amount=Decimal('180.00'),
            created_by=test_admin)
        assert admin_client.delete(f'/api/expenses/{expense.id}/').status_code == 204
        assert not Expense.objects.exists()

        record = DeletedRecord.objects.get(kind='expense')
        assert 'Box Co' in record.label
        assert _restore(admin_client, record).status_code == 200
        back = Expense.objects.get(pk=expense.pk)
        assert back.amount == Decimal('1180.00') and back.vendor == 'Box Co'

    def test_receivable_account_does_not_steal_default_back(self, admin_client):
        old = ReceivableAccount.objects.create(
            account_holder_name='Old', upi_id='old@upi', is_default=True)
        admin_client.delete(f'/api/receivable-accounts/{old.id}/')
        current = ReceivableAccount.objects.create(
            account_holder_name='New', upi_id='new@upi', is_default=True)

        _restore(admin_client, DeletedRecord.objects.get(kind='receivable_account'))
        old.refresh_from_db()
        current.refresh_from_db()
        assert current.is_default is True
        assert old.is_default is False

    def test_contact_submission(self, admin_client):
        msg = ContactSubmission.objects.create(
            name='Asha', email='asha@example.com', subject='Bulk order', message='Hi')
        assert admin_client.delete(f'/api/contact/{msg.id}/').status_code == 204
        record = DeletedRecord.objects.get(kind='contact_submission')
        assert _restore(admin_client, record).status_code == 200
        assert ContactSubmission.objects.get(pk=msg.pk).subject == 'Bulk order'

    def test_gallery_image(self, admin_client, test_product):
        image = ProductImage.objects.create(
            product=test_product, image=create_test_image('gallery.jpg'), alt_text='side')
        assert admin_client.delete(f'/api/product-images/{image.id}/').status_code == 204
        assert not ProductImage.objects.exists()

        record = DeletedRecord.objects.get(kind='product_image')
        assert test_product.name in record.label
        assert _restore(admin_client, record).status_code == 200
        back = ProductImage.objects.get(pk=image.pk)
        assert back.product_id == test_product.id and back.alt_text == 'side'

    def test_review_keeps_its_original_date(self, admin_client, test_user, test_product):
        review = Review.objects.create(
            user=test_user, product=test_product, item_type='product',
            rating=5, comment='Lovely')
        written = timezone.now() - timedelta(days=40)
        Review.objects.filter(pk=review.pk).update(created_at=written)

        assert admin_client.delete(f'/api/reviews/{review.id}/').status_code == 204
        record = DeletedRecord.objects.get(kind='review')
        assert _restore(admin_client, record).status_code == 200
        back = Review.objects.get(pk=review.pk)
        assert back.rating == 5 and back.comment == 'Lovely'
        # A raw restore: the review does not jump to the top as "written today".
        assert abs((back.created_at - written).total_seconds()) < 1

    def test_customer_deleting_their_own_review_is_not_binned(
            self, authenticated_client, test_user, test_product):
        review = Review.objects.create(
            user=test_user, product=test_product, item_type='product', rating=4)
        assert authenticated_client.delete(f'/api/reviews/{review.id}/').status_code == 204
        assert not Review.objects.exists()
        assert not DeletedRecord.objects.exists()


@pytest.mark.django_db
class TestBinEndpoint:
    def test_lists_entries_without_the_payload(self, admin_client, test_coupon):
        admin_client.delete(f'/api/coupons/{test_coupon.id}/')
        resp = admin_client.get(BIN)
        assert resp.status_code == 200
        assert resp.data['retention_days'] == 30
        (item,) = resp.data['items']
        assert item['kind'] == 'coupon'
        assert item['deleted_by'] == 'admin@example.com'
        assert item['purge_at'] > item['deleted_at']
        assert 'payload' not in item

    def test_staff_only(self, authenticated_client, api_client, test_coupon):
        assert authenticated_client.get(BIN).status_code == 403
        record = DeletedRecord.objects.create(
            kind='coupon', model_label='admin_panel.coupon', object_pk='1',
            label='x', payload={'objects': []})
        assert authenticated_client.post(f'{BIN}{record.id}/restore/').status_code == 403

    def test_unknown_entry_is_404(self, admin_client):
        assert admin_client.post(f'{BIN}999999/restore/').status_code == 404

    def test_restore_refuses_when_the_parent_is_gone(self, admin_client, test_product):
        image = ProductImage.objects.create(
            product=test_product, image=create_test_image('gallery.jpg'))
        admin_client.delete(f'/api/product-images/{image.id}/')
        test_product.delete()

        resp = _restore(admin_client, DeletedRecord.objects.get())
        assert resp.status_code == 409
        assert 'no longer exists' in resp.data['error']
        assert not ProductImage.objects.exists()


@pytest.mark.django_db
class TestPurge:
    def test_old_entries_are_purged_and_recent_ones_kept(self, admin_client, test_coupon, expired_coupon):
        admin_client.delete(f'/api/coupons/{test_coupon.id}/')
        admin_client.delete(f'/api/coupons/{expired_coupon.id}/')
        old = DeletedRecord.objects.get(object_pk=str(test_coupon.id))
        DeletedRecord.objects.filter(pk=old.pk).update(
            deleted_at=timezone.now() - timedelta(days=31))

        call_command('purge_recycle_bin', '--dry-run')
        assert DeletedRecord.objects.count() == 2

        call_command('purge_recycle_bin')
        assert list(DeletedRecord.objects.values_list('object_pk', flat=True)) == [
            str(expired_coupon.id)]

    def test_a_binned_product_still_in_a_combo_is_not_purged(self, test_combo, test_product):
        """The combo line PROTECTs the product's size, so the row cannot be
        deleted. The purge has to skip it, say why, and count it truthfully.

        A product switched off through save() is taken OUT of its combos first
        (products/combo_membership.py), so this can only arise for a row
        changed behind save()'s back — hence the .update() here."""
        from io import StringIO
        from products.models import Product

        Product.objects.filter(pk=test_product.pk).update(
            is_active=False, deactivated_at=timezone.now() - timedelta(days=60))

        out = StringIO()
        call_command('purge_recycle_bin', stdout=out)

        test_product.refresh_from_db()  # still there
        assert ProductComboItem.objects.filter(combo=test_combo).count() == 2
        assert 'still part of combo(s): Test Combo Pack' in out.getvalue()
        assert '0 product(s)' in out.getvalue()

    def test_a_binned_product_taken_out_of_its_combos_can_be_purged(self, test_combo, test_product):
        """The normal path: binning the product removes it from the combo, so
        nothing protects it any more and the purge may take it. The combo keeps
        its other line and stays switched off."""
        from products.models import Product, ProductCombo

        test_product.is_active = False
        test_product.deactivated_at = timezone.now() - timedelta(days=60)
        test_product.save(update_fields=['is_active', 'deactivated_at'])
        assert ProductComboItem.objects.filter(combo=test_combo).count() == 1

        call_command('purge_recycle_bin')

        assert not Product.objects.filter(pk=test_product.pk).exists()
        assert ProductComboItem.objects.filter(combo=test_combo).count() == 1
        assert ProductCombo.objects.get(pk=test_combo.pk).is_active is False

    def test_a_product_in_a_combo_cannot_be_hard_deleted_at_all(self, test_combo, test_product):
        """Pins the guarantee the purge relies on: no code path can cascade a
        combo line away by deleting its product."""
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            test_product.delete()
        assert ProductComboItem.objects.filter(combo=test_combo).count() == 2
