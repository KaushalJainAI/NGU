"""Admin-only GST reporting endpoints.

Invoice-basis ledger (GSTR-1 Tables 7/9B/documents) plus the HSN summary
(Table 12). One endpoint, two renderings: JSON for the panel's on-screen
tables and CSV for the file the owner (or their CA) actually files from.
Both renderings come from the same functions so the screen and the download
can never disagree.
"""
from datetime import date as date_cls, timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from admin_panel.utils import csv_response
from products.hsn import RATES_AS_OF

from .gst_ledger import (
    b2c_by_state, credit_note_register, documents_issued,
    fallback_place_of_supply, invoice_register, period_summary,
)
from .gst_reports import hsn_summary, unclassified_products


def _f(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _block_json(block):
    return {k: (_f(v) if k != 'count' else v) for k, v in block.items()}


def _parse_range(request):
    """Inclusive [from, to] dates, defaulting to the PREVIOUS calendar month.

    That default is chosen for the job this serves: GSTR-1 is filed for a month
    that has closed, so "last month" is what an admin opening this screen almost
    always wants. Defaulting to the current month would show a partial period
    that reconciles against nothing.
    """
    # localdate(), NOT date.today(): the latter is the SERVER's date (UTC in the
    # container), so between 00:00 and 05:30 IST on the 1st of a month it still
    # reads as the previous month and the "last month" default silently resolves
    # a whole period early — on the one screen whose entire job is picking the
    # right filing period. Matches the localdate() convention used by the
    # dashboard and the digest commands.
    today = timezone.localdate()
    first_this_month = today.replace(day=1)
    default_to = first_this_month - timedelta(days=1)
    default_from = default_to.replace(day=1)
    try:
        date_from = date_cls.fromisoformat(request.query_params['from'])
    except (KeyError, ValueError):
        date_from = default_from
    try:
        date_to = date_cls.fromisoformat(request.query_params['to'])
    except (KeyError, ValueError):
        date_to = default_to
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return date_from, date_to


@api_view(['GET'])
@permission_classes([IsAdminUser])
def hsn_summary_report(request):
    """HSN-wise summary of outward supplies for a date range.

    `?from=YYYY-MM-DD&to=YYYY-MM-DD` (inclusive, defaults to last month).
    `?download=csv` downloads it instead of returning JSON. NOT `?format=` —
    DRF reserves that name for renderer negotiation and 404s on an unknown
    value, which is a confusing way for a download button to fail.

    Deliberately NOT cached, unlike the Insights endpoints: this is a
    once-a-month compliance read where a stale figure is worse than a slow one.
    """
    date_from, date_to = _parse_range(request)
    data = hsn_summary(date_from, date_to)

    if request.query_params.get('download') == 'csv':
        header = ['HSN/SAC', 'Description', 'UQC', 'Total Quantity',
                  'Rate (%)', 'Taxable Value', 'Tax Amount', 'Total Value']

        def rows():
            for row in data['rows']:
                yield [
                    row['hsn_code'] or 'NOT CLASSIFIED',
                    row['description'],
                    row['uqc'],
                    row['quantity'],
                    f"{row['rate']:g}",
                    f"{row['taxable_value']:.2f}",
                    f"{row['tax_amount']:.2f}",
                    f"{row['total_value']:.2f}",
                ]
            totals = data['totals']
            yield ['TOTAL', '', '', totals['quantity'], '',
                   f"{totals['taxable_value']:.2f}",
                   f"{totals['tax_amount']:.2f}",
                   f"{totals['total_value']:.2f}"]
            # Trailing context so the file is self-explanatory when it is opened
            # weeks later, or by someone who did not run the report.
            yield []
            yield [f"Period: {date_from.isoformat()} to {date_to.isoformat()} "
                   f"({data['order_count']} orders, cancelled and deleted excluded)"]
            yield [f"Refunds recorded in this period (credit notes, Table 9B — "
                   f"NOT netted off above): Rs. {data['refunded_in_period']['amount']:.2f} "
                   f"incl. GST Rs. {data['refunded_in_period']['tax']:.2f}"]
            yield [f"Rates shown are as charged. Statutory rates in the HSN "
                   f"reference are as of {RATES_AS_OF}."]

        filename = f"hsn-summary-{date_from.isoformat()}-to-{date_to.isoformat()}.csv"
        return csv_response(filename, header, rows())

    return Response({
        'from': date_from.isoformat(),
        'to': date_to.isoformat(),
        'rates_as_of': RATES_AS_OF,
        'order_count': data['order_count'],
        'shipping_sac': data['shipping_sac'],
        'rows': [
            {**row,
             'taxable_value': float(row['taxable_value']),
             'tax_amount': float(row['tax_amount']),
             'total_value': float(row['total_value'])}
            for row in data['rows']
        ],
        'totals': {k: (float(v) if k != 'quantity' else v)
                   for k, v in data['totals'].items()},
        'unclassified_value': float(data['unclassified_value']),
        'refunded_in_period': {
            'amount': float(data['refunded_in_period']['amount']),
            'tax': float(data['refunded_in_period']['tax']),
        },
        # The work list, so the screen that reveals a hole also says how to
        # close it instead of making the admin go hunting.
        'unclassified_products': [
            {'id': p['id'], 'name': p['name'], 'tax_rate': float(p['tax_rate'] or 0)}
            for p in unclassified_products()
        ],
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def gst_summary(request):
    """Invoice-basis period summary: invoices, credit notes, net + fallbacks."""
    date_from, date_to = _parse_range(request)
    data = period_summary(date_from, date_to)
    fallback = fallback_place_of_supply(date_from, date_to)

    if request.query_params.get('download') == 'csv':
        header = ['Block', 'Count', 'Taxable Value', 'CGST', 'SGST', 'IGST', 'Total Tax', 'Total']

        def rows():
            for label in ('invoices', 'credit_notes', 'net'):
                block = data[label]
                yield [
                    label,
                    block.get('count', '') if label != 'net' else '',
                    f"{block['taxable_value']:.2f}",
                    f"{block['cgst']:.2f}",
                    f"{block['sgst']:.2f}",
                    f"{block['igst']:.2f}",
                    f"{block['tax']:.2f}",
                    f"{block['total']:.2f}",
                ]
            yield []
            yield [f"Period: {date_from.isoformat()} to {date_to.isoformat()} (invoices by issue date)"]

        return csv_response(f"gst-summary-{date_from.isoformat()}-to-{date_to.isoformat()}.csv",
                            header, rows())

    return Response({
        'from': date_from.isoformat(),
        'to': date_to.isoformat(),
        'invoices': _block_json(data['invoices']),
        'credit_notes': _block_json(data['credit_notes']),
        'net': _block_json(data['net']),
        'fallback_place_of_supply': fallback,
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def gst_b2c(request):
    """State-wise B2C summary (GSTR-1 Table 7 shape): gross/credit/net."""
    date_from, date_to = _parse_range(request)
    rows = b2c_by_state(date_from, date_to)

    if request.query_params.get('download') == 'csv':
        header = ['State Code', 'State', 'Rate (%)', 'Gross Taxable', 'Gross CGST',
                  'Gross SGST', 'Gross IGST', 'Credit Taxable', 'Credit CGST',
                  'Credit SGST', 'Credit IGST', 'Net Taxable', 'Net CGST',
                  'Net SGST', 'Net IGST']

        def csv_rows():
            for r in rows:
                yield [
                    r['state_code'], r['state_name'],
                    '' if r['rate'] is None else f"{r['rate']:g}",
                    f"{r['gross_taxable_value']:.2f}", f"{r['gross_cgst']:.2f}",
                    f"{r['gross_sgst']:.2f}", f"{r['gross_igst']:.2f}",
                    f"{r['credit_taxable_value']:.2f}", f"{r['credit_cgst']:.2f}",
                    f"{r['credit_sgst']:.2f}", f"{r['credit_igst']:.2f}",
                    f"{r['net_taxable_value']:.2f}", f"{r['net_cgst']:.2f}",
                    f"{r['net_sgst']:.2f}", f"{r['net_igst']:.2f}",
                ]

        return csv_response(f"gst-b2c-{date_from.isoformat()}-to-{date_to.isoformat()}.csv",
                            header, csv_rows())

    return Response({
        'from': date_from.isoformat(),
        'to': date_to.isoformat(),
        'rows': [{k: _f(v) for k, v in r.items()} for r in rows],
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def gst_documents(request):
    """Documents issued per series, with gap detection (GSTR-1 Table 12 docs)."""
    date_from, date_to = _parse_range(request)
    data = documents_issued(date_from, date_to)

    if request.query_params.get('download') == 'csv':
        header = ['Type', 'Series', 'From', 'To', 'Count', 'Gap']

        def csv_rows():
            for label in ('invoices', 'credit_notes'):
                for row in data[label]:
                    yield [label, row['series'], row['from_number'],
                           row['to_number'], row['count'], row['gap']]

        return csv_response(f"gst-documents-{date_from.isoformat()}-to-{date_to.isoformat()}.csv",
                            header, csv_rows())

    return Response({'from': date_from.isoformat(), 'to': date_to.isoformat(), **data})


@api_view(['GET'])
@permission_classes([IsAdminUser])
def gst_invoices(request):
    """Invoice register: one row per invoice issued in range."""
    date_from, date_to = _parse_range(request)
    rows = invoice_register(date_from, date_to)

    if request.query_params.get('download') == 'csv':
        header = ['Invoice', 'Issued On', 'Order', 'Buyer', 'Place of Supply',
                  'Taxable Value', 'CGST', 'SGST', 'IGST', 'Total Tax', 'Total',
                  'Payment Method', 'Order Status']

        def csv_rows():
            for r in rows:
                yield [r['number'], r['issued_on'], r['order_number'], r['buyer'],
                       r['place_of_supply'], f"{r['taxable_value']:.2f}",
                       f"{r['cgst']:.2f}", f"{r['sgst']:.2f}", f"{r['igst']:.2f}",
                       f"{r['total_tax']:.2f}", f"{r['total']:.2f}",
                       r['payment_method'], r['status']]

        return csv_response(f"invoice-register-{date_from.isoformat()}-to-{date_to.isoformat()}.csv",
                            header, csv_rows())

    return Response({
        'from': date_from.isoformat(),
        'to': date_to.isoformat(),
        'rows': [{k: _f(v) for k, v in r.items()} for r in rows],
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def gst_credit_notes(request):
    """Credit note register: one row per credit note issued in range."""
    date_from, date_to = _parse_range(request)
    rows = credit_note_register(date_from, date_to)

    if request.query_params.get('download') == 'csv':
        header = ['Credit Note', 'Issued On', 'Reason', 'Invoice', 'Order',
                  'Taxable Value', 'CGST', 'SGST', 'IGST', 'Total Tax', 'Total']

        def csv_rows():
            for r in rows:
                yield [r['number'], r['issued_on'], r['reason'], r['invoice_number'],
                       r['order_number'], f"{r['taxable_value']:.2f}",
                       f"{r['cgst']:.2f}", f"{r['sgst']:.2f}", f"{r['igst']:.2f}",
                       f"{r['total_tax']:.2f}", f"{r['total']:.2f}"]

        return csv_response(f"credit-note-register-{date_from.isoformat()}-to-{date_to.isoformat()}.csv",
                            header, csv_rows())

    return Response({
        'from': date_from.isoformat(),
        'to': date_to.isoformat(),
        'rows': [{k: _f(v) for k, v in r.items()} for r in rows],
    })
