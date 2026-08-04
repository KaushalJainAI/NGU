"""Invoice issuing: numbering, triggers, freezing, and the endpoint gate.

These are the four defects the invoice rework closes, one section each:

1. the series had gaps (it was `ORD-{order.id}`),
2. reprints mutated with live settings,
3. any order could pull a document headed TAX INVOICE,
4. nothing recorded that an invoice had been issued at all.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from orders.invoicing import (
    financial_year_label, invoice_is_due, invoice_series, issue_invoice,
    maybe_issue_invoice,
)
from orders.models import Invoice, InvoiceCounter, Order, OrderItem

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user(test_user):
    """The project's standard customer fixture (conftest.py)."""
    return test_user


@pytest.fixture
def admin(test_admin):
    return test_admin


def _order(user, **kwargs):
    defaults = dict(
        user=user,
        shipping_address='12 Rose Lane, Ujjain, Madhya Pradesh 456771',
        phone_number='9000000000',
        subtotal=Decimal('500.00'),
        discount_amount=Decimal('0.00'),
        shipping_charge=Decimal('0.00'),
        shipping_tax=Decimal('0.00'),
        tax=Decimal('23.81'),
        total_amount=Decimal('500.00'),
        payment_method='ONLINE',
        payment_status='paid',
        status='confirmed',
    )
    defaults.update(kwargs)
    order = Order.objects.create(**defaults)
    OrderItem.objects.create(
        order=order, item_type='product', product_name='Garam Masala',
        product_weight='100g', quantity=2, price=Decimal('250.00'),
        discounted_price=Decimal('250.00'), final_price=Decimal('500.00'),
        tax_amount=Decimal('23.81'), tax_rate=Decimal('5.00'))
    return order


# ---------------------------------------------------------------------------
# 1. The number is a real series
# ---------------------------------------------------------------------------

def test_number_is_sequential_and_gapless_across_cancelled_orders(user):
    """The defect: `ORD-{id}` burned a number on every cancelled order.

    Two invoiced orders with a cancelled one between them must still be
    consecutive in the series — the cancelled order never enters it.
    """
    first = _order(user)
    cancelled = _order(user, status='cancelled', payment_status='pending')
    second = _order(user)

    inv1, _ = issue_invoice(first)
    assert not invoice_is_due(cancelled)
    inv2, _ = issue_invoice(second)

    assert inv2.sequence == inv1.sequence + 1
    # …even though the order ids are NOT consecutive.
    assert second.id - first.id == 2


def test_number_format_fits_the_gst_16_character_limit(user):
    invoice, _ = issue_invoice(_order(user))
    assert len(invoice.number) <= 16
    assert invoice.number == f"{invoice.series}/{invoice.sequence:06d}"
    # Only alphanumerics, '-' and '/' are permitted in a GST serial.
    assert all(c.isalnum() or c in '-/' for c in invoice.number)


def test_series_restarts_per_financial_year(user):
    """April–March, so a March and an April invoice sit in different series."""
    march = timezone.make_aware(timezone.datetime(2026, 3, 31, 23, 0))
    april = timezone.make_aware(timezone.datetime(2026, 4, 1, 1, 0))

    assert financial_year_label(march) == '25-26'
    assert financial_year_label(april) == '26-27'

    inv_march, _ = issue_invoice(_order(user), when=march)
    inv_april, _ = issue_invoice(_order(user), when=april)

    assert inv_march.series != inv_april.series
    # Each series counts from 1 independently.
    assert inv_march.sequence == 1
    assert inv_april.sequence == 1


def test_counter_is_shared_within_a_series(user):
    issue_invoice(_order(user))
    issue_invoice(_order(user))
    counter = InvoiceCounter.objects.get(series=invoice_series())
    assert counter.last_number == 2
    assert InvoiceCounter.objects.count() == 1


# ---------------------------------------------------------------------------
# 2. Reprints do not mutate
# ---------------------------------------------------------------------------

def test_seller_details_are_frozen_against_settings_changes(user, settings):
    """The bug that would actually embarrass you: change SELLER_ADDRESS and every
    historical invoice reprinted with the new one."""
    settings.SELLER_ADDRESS = 'Old Address, Ujjain'
    settings.SELLER_GSTIN = '23ABUPJ8925C1ZI'
    invoice, _ = issue_invoice(_order(user))

    settings.SELLER_ADDRESS = 'New Address, Indore'
    settings.SELLER_GSTIN = '23DIFFERENT9999'
    invoice.refresh_from_db()

    assert invoice.snapshot['seller']['address'] == 'Old Address, Ujjain'
    assert invoice.snapshot['seller']['gstin'] == '23ABUPJ8925C1ZI'


def test_buyer_address_is_frozen_against_admin_edits(user):
    """An admin PATCHing shipping_address must not rewrite who the bill names."""
    order = _order(user)
    invoice, _ = issue_invoice(order)

    order.shipping_address = 'Somewhere Else Entirely'
    order.save(update_fields=['shipping_address'])
    invoice.refresh_from_db()

    assert '12 Rose Lane' in invoice.snapshot['buyer']['address']


def test_totals_are_frozen(user):
    order = _order(user)
    invoice, _ = issue_invoice(order)

    order.total_amount = Decimal('999.00')
    order.save(update_fields=['total_amount'])
    invoice.refresh_from_db()

    assert invoice.snapshot['totals']['total_amount'] == '500.00'
    assert invoice.total_amount == Decimal('500.00')


def test_reprint_is_identical_after_settings_change(user, settings, monkeypatch):
    """The whole point, end to end: two renders of one invoice, with the seller's
    details changed in between, must produce the same document.

    reportlab is put in `invariant` mode (fixed document id and timestamp) and
    page compression is turned off, so the two renders are directly comparable
    AND the drawn text is greppable in the raw bytes.
    """
    rl_config = pytest.importorskip('reportlab.rl_config')
    from orders.invoice import generate_invoice_pdf
    monkeypatch.setattr(rl_config, 'invariant', 1, raising=False)
    monkeypatch.setattr(rl_config, 'pageCompression', 0, raising=False)

    settings.SELLER_ADDRESS = 'Original Address'
    invoice, _ = issue_invoice(_order(user))
    first = generate_invoice_pdf(invoice)

    settings.SELLER_ADDRESS = 'Changed Address'
    second = generate_invoice_pdf(invoice)

    assert first == second
    assert b'Original Address' in second
    assert b'Changed Address' not in second


# ---------------------------------------------------------------------------
# 3. Issue triggers
# ---------------------------------------------------------------------------

def test_pending_online_order_is_not_due(user):
    order = _order(user, payment_status='pending', status='pending')
    assert not invoice_is_due(order)


def test_online_order_is_due_once_paid(user):
    assert invoice_is_due(_order(user, payment_status='paid'))


def test_cod_order_is_not_due_before_dispatch(user):
    """COD takes no money at checkout, but the trigger is DISPATCH, not cash."""
    for status_ in ('pending', 'confirmed', 'processing'):
        order = _order(user, payment_method='COD', payment_status='pending',
                       status=status_)
        assert not invoice_is_due(order), status_


@pytest.mark.parametrize('status_', ['shipped', 'delivering', 'delivered'])
def test_cod_order_is_due_at_dispatch_even_though_unpaid(user, status_):
    """The bill travels with the goods; the courier remits cash days later."""
    order = _order(user, payment_method='COD', payment_status='pending',
                   status=status_)
    assert invoice_is_due(order)


def test_cancelled_order_is_never_due(user):
    order = _order(user, status='cancelled', payment_status='rejected')
    assert not invoice_is_due(order)


def test_refunded_online_order_is_still_due(user):
    """A refund can only be recorded against money actually received, so a
    refunded order was definitely supplied and needs its number.

    Without this a historical refunded order gets no invoice, and its credit
    note has no serial to cite — it would fall back to the order reference.
    """
    order = _order(user, payment_status='refunded', status='refunded')
    assert invoice_is_due(order)


def test_refunded_cod_order_is_still_due(user):
    """Its status has left the dispatched set, so the money signal is the only
    evidence left — and it is sufficient."""
    order = _order(user, payment_method='COD', payment_status='refunded',
                   status='refunded')
    assert invoice_is_due(order)


def test_cod_order_with_confirmed_cash_is_due(user):
    """Cash in hand on a COD order means the courier delivered. Dispatch is the
    normal trigger and fires first; this is the belt-and-braces path."""
    order = _order(user, payment_method='COD', payment_status='paid',
                   status='confirmed', cod_paid_at=timezone.now())
    assert invoice_is_due(order)


def test_cancelled_order_is_not_due_even_if_money_was_taken(user):
    """Capture-after-cancel is an exception routed to a refund, not a sale."""
    order = _order(user, status='cancelled', payment_status='paid')
    assert not invoice_is_due(order)


def test_issuing_is_idempotent(user):
    """One order, one invoice — a second call returns the first, unchanged."""
    order = _order(user)
    first, created_1 = issue_invoice(order)
    second, created_2 = issue_invoice(order)

    assert created_1 is True and created_2 is False
    assert first.pk == second.pk
    assert Invoice.objects.filter(order=order).count() == 1
    # And the sequence was not burned twice.
    assert InvoiceCounter.objects.get(series=first.series).last_number == 1


def test_maybe_issue_never_raises_on_a_broken_snapshot(user, monkeypatch):
    """A document bug must not roll back the payment capture it runs inside."""
    import orders.invoicing as invoicing
    monkeypatch.setattr(invoicing, 'build_invoice_snapshot',
                        lambda order: (_ for _ in ()).throw(RuntimeError('boom')))

    order = _order(user)
    assert maybe_issue_invoice(order) is None
    assert not Invoice.objects.filter(order=order).exists()


# ---------------------------------------------------------------------------
# 4. The endpoint is gated on an issued invoice
# ---------------------------------------------------------------------------

def test_invoice_endpoint_409s_when_none_issued(user):
    """A pending, unpaid order must not yield a page headed TAX INVOICE."""
    order = _order(user, payment_status='pending', status='pending')
    client = APIClient()
    client.force_authenticate(user=user)

    res = client.get(f'/api/orders/{order.id}/invoice/')

    assert res.status_code == 409
    assert res.data['code'] == 'invoice_not_issued'


def test_invoice_endpoint_serves_the_issued_document(user):
    pytest.importorskip('reportlab')
    order = _order(user)
    invoice, _ = issue_invoice(order)
    client = APIClient()
    client.force_authenticate(user=user)

    res = client.get(f'/api/orders/{order.id}/invoice/')

    assert res.status_code == 200
    assert res['Content-Type'] == 'application/pdf'
    # Named by the invoice serial, not the order id.
    assert invoice.number.replace('/', '-') in res['Content-Disposition']


def test_order_response_exposes_the_invoice_identity(user):
    order = _order(user)
    client = APIClient()
    client.force_authenticate(user=user)

    before = client.get(f'/api/orders/{order.id}/')
    assert before.data['invoice'] is None

    invoice, _ = issue_invoice(order)
    after = client.get(f'/api/orders/{order.id}/')
    assert after.data['invoice']['number'] == invoice.number


# ---------------------------------------------------------------------------
# Wiring: the live paths actually issue
# ---------------------------------------------------------------------------

def test_admin_dispatch_issues_a_cod_invoice(user, admin):
    order = _order(user, payment_method='COD', payment_status='pending',
                   status='confirmed')
    client = APIClient()
    client.force_authenticate(user=admin)

    res = client.patch(f'/api/orders/{order.id}/', {'status': 'shipped'},
                       format='json')

    assert res.status_code == 200
    assert Invoice.objects.filter(order=order).exists()


def test_advancing_a_dispatched_order_does_not_issue_a_second(user, admin):
    order = _order(user, payment_method='COD', payment_status='pending',
                   status='shipped')
    issue_invoice(order)
    client = APIClient()
    client.force_authenticate(user=admin)

    client.patch(f'/api/orders/{order.id}/', {'status': 'delivered'},
                 format='json')

    assert Invoice.objects.filter(order=order).count() == 1


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def test_backfill_issues_oldest_first(user):
    from django.core.management import call_command

    older = _order(user)
    newer = _order(user)
    # created_at is auto_now_add; force a gap so the ordering is unambiguous.
    Order.objects.filter(pk=older.pk).update(
        created_at=timezone.now() - timedelta(days=3))

    call_command('backfill_invoices', verbosity=0)

    assert Invoice.objects.get(order=older).sequence == 1
    assert Invoice.objects.get(order=newer).sequence == 2


def test_backfill_skips_orders_that_are_not_due(user):
    from django.core.management import call_command

    _order(user, payment_status='pending', status='pending')
    call_command('backfill_invoices', verbosity=0)
    assert Invoice.objects.count() == 0


def test_backfill_covers_every_historical_shape(user):
    """The migration case: a spread of legacy orders, numbered in one pass.

    Asserts BOTH directions — that everything with a completed supply gets a
    number, and that nothing else does.
    """
    from django.core.management import call_command

    due = {
        'online_paid': _order(user),
        'online_refunded': _order(user, payment_status='refunded', status='refunded'),
        'cod_delivered': _order(user, payment_method='COD',
                                payment_status='pending', status='delivered'),
        'cod_cash_confirmed': _order(user, payment_method='COD',
                                     payment_status='paid', status='confirmed',
                                     cod_paid_at=timezone.now()),
        'legacy_tax_exclusive': _order(user, tax_inclusive=False),
    }
    not_due = {
        'pending': _order(user, payment_status='pending', status='pending'),
        'cancelled': _order(user, payment_status='rejected', status='cancelled'),
        'cod_awaiting_dispatch': _order(user, payment_method='COD',
                                        payment_status='pending',
                                        status='processing'),
    }

    call_command('backfill_invoices', verbosity=0)

    for label, order in due.items():
        assert Invoice.objects.filter(order=order).exists(), f"{label} was not numbered"
    for label, order in not_due.items():
        assert not Invoice.objects.filter(order=order).exists(), f"{label} was numbered"

    # Every number issued is distinct and the series has no holes in it.
    sequences = sorted(Invoice.objects.values_list('sequence', flat=True))
    assert sequences == list(range(1, len(due) + 1))


def test_backfill_is_re_entrant(user):
    """Running it twice must not issue a second invoice or burn a number."""
    from django.core.management import call_command

    _order(user)
    call_command('backfill_invoices', verbosity=0)
    call_command('backfill_invoices', verbosity=0)

    assert Invoice.objects.count() == 1
    assert InvoiceCounter.objects.get(series=invoice_series()).last_number == 1


def test_backfill_dry_run_writes_nothing(user):
    from django.core.management import call_command

    _order(user)
    call_command('backfill_invoices', '--dry-run', verbosity=0)

    assert Invoice.objects.count() == 0
    assert InvoiceCounter.objects.count() == 0


def test_backfill_stamps_each_invoice_with_its_order_date(user):
    """A backfilled invoice is dated at the supply, not at the day of the
    migration — and its SERIES follows from that date."""
    from django.core.management import call_command

    order = _order(user)
    placed = timezone.now() - timedelta(days=400)
    Order.objects.filter(pk=order.pk).update(created_at=placed)

    call_command('backfill_invoices', verbosity=0)

    invoice = Invoice.objects.get(order=order)
    assert invoice.issued_at == placed
    assert invoice.series == invoice_series(placed)


def test_backfilled_credit_note_cites_the_real_invoice_number(user):
    """The point of numbering history: a historical refund's credit note must
    reference a serial, not the order id."""
    pytest.importorskip('reportlab')
    from django.core.management import call_command
    from orders.invoice import credited_invoice_label
    from orders.models import OrderRefund

    order = _order(user, payment_status='refunded', status='refunded')
    OrderRefund.objects.create(order=order, amount=Decimal('100.00'),
                               tax_amount=Decimal('4.76'), source='admin')

    call_command('backfill_invoices', verbosity=0)
    order.refresh_from_db()

    assert credited_invoice_label(order) == Invoice.objects.get(order=order).number
