"""Monthly books summary — one estimate screen, no ledgers.

Deliberately small: sales (from the invoice-basis GST ledger), cash received,
costs (gateway + courier + entered expenses), an estimated profit and an
estimated GST figure. Every money value is a Decimal here; the view formats to
strings. `is_estimate: True` is always returned — these come from the entries
in this panel and must be confirmed with the accountant before filing/paying.
"""
from decimal import Decimal

from django.db.models import Count, Q, Sum

from orders.gst_ledger import period_summary
from orders.models import Order, OrderRefund
from payments.models import Payment
from spices_backend.timeranges import range_filter

from .models import Expense

ONLINE = ['ONLINE', 'razorpay']
PAISA = Decimal('0.01')


def _s(value):
    return str(Decimal(str(value or 0)).quantize(PAISA))


def monthly_summary(date_from, date_to):
    ledger = period_summary(date_from, date_to)
    invoices = ledger['invoices']
    notes = ledger['credit_notes']
    net = ledger['net']

    payments = Payment.objects.filter(
        status__in=['completed', 'refunded'],
        order__is_deleted=False,
        **range_filter('order__created_at', date_from, date_to),
    )
    pay_agg = payments.aggregate(amount=Sum('amount'), fee=Sum('gateway_fee'), tax=Sum('gateway_tax'))
    online_received = pay_agg['amount'] or Decimal('0.00')
    gateway_fee = pay_agg['fee'] or Decimal('0.00')
    gateway_tax = pay_agg['tax'] or Decimal('0.00')
    gateway_fees_ex_gst = gateway_fee - gateway_tax
    gateway_total = payments.count()
    gateway_recorded = payments.filter(gateway_fee__gt=0).count()

    cod_received = (Order.objects.filter(
        is_deleted=False, **range_filter('cod_paid_at', date_from, date_to),
    ).aggregate(s=Sum('total_amount'))['s'] or Decimal('0.00'))

    refunds_paid = (OrderRefund.objects.filter(
        **range_filter('created_at', date_from, date_to),
        order__is_deleted=False,
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00'))

    cod_outstanding_now = (Order.objects.filter(
        is_deleted=False, payment_method='COD', cod_paid_at__isnull=True,
        status__in=['shipped', 'delivering', 'delivered'],
    ).aggregate(s=Sum('total_amount'))['s'] or Decimal('0.00'))

    courier_orders = Order.objects.filter(
        is_deleted=False, **range_filter('created_at', date_from, date_to),
    ).exclude(status='cancelled')
    courier_cost = courier_orders.aggregate(s=Sum('shipping_cost'))['s'] or Decimal('0.00')
    courier_total = Order.objects.filter(
        is_deleted=False, **range_filter('created_at', date_from, date_to),
        status__in=['shipped', 'delivering', 'delivered'],
    ).count()
    courier_recorded = courier_orders.filter(shipping_cost__gt=0).count()

    expenses = Expense.objects.filter(**range_filter('date', date_from, date_to))
    by_cat = (expenses.values('category')
              .annotate(amount=Sum('amount'),
                        itc=Sum('gst_amount', filter=Q(itc_eligible=True))))
    labels = dict(Expense.CATEGORIES)
    expenses_by_category = []
    for row in by_cat:
        cost = (row['amount'] or Decimal('0.00')) - (row['itc'] or Decimal('0.00'))
        expenses_by_category.append({
            'category': row['category'],
            'label': labels.get(row['category'], row['category']),
            'cost': cost,
        })
    expenses_by_category.sort(key=lambda r: r['category'])
    expenses_total = sum((r['cost'] for r in expenses_by_category), Decimal('0.00'))

    net_sales_ex_gst = net['taxable_value']
    estimated_profit = net_sales_ex_gst - gateway_fees_ex_gst - courier_cost - expenses_total

    input_tax_expenses = (expenses.filter(itc_eligible=True)
                          .aggregate(s=Sum('gst_amount'))['s'] or Decimal('0.00'))
    estimated_net_gst = (invoices['tax'] - notes['tax']
                         - input_tax_expenses - gateway_tax)

    return {
        'is_estimate': True,
        'sales': {
            'invoiced_total': _s(invoices['total']),
            'credit_notes_total': _s(notes['total']),
            'net_sales_ex_gst': _s(net_sales_ex_gst),
        },
        'cash': {
            'online_received': _s(online_received),
            'cod_received': _s(cod_received),
            'refunds_paid': _s(refunds_paid),
            'cod_outstanding_now': _s(cod_outstanding_now),
        },
        'costs': {
            'gateway_fees_ex_gst': _s(gateway_fees_ex_gst),
            'gateway_fee_coverage': {'recorded': gateway_recorded, 'total': gateway_total},
            'courier_cost': _s(courier_cost),
            'courier_cost_coverage': {'recorded': courier_recorded, 'total': courier_total},
            'expenses_by_category': [
                {**r, 'cost': _s(r['cost'])} for r in expenses_by_category
            ],
            'expenses_total': _s(expenses_total),
        },
        'profit': {'estimated_profit': _s(estimated_profit)},
        'gst': {
            'output_tax': _s(invoices['tax']),
            'credit_note_tax': _s(notes['tax']),
            'input_tax_expenses': _s(input_tax_expenses),
            'input_tax_gateway': _s(gateway_tax),
            'estimated_net_gst': _s(estimated_net_gst),
        },
    }
