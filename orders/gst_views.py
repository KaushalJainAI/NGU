"""Admin-only GST reporting endpoints.

One endpoint, two renderings: JSON for the admin panel's on-screen table and CSV
for the file the owner (or their CA) actually uploads/keys into GSTR-1 Table 12.
Both come from `gst_reports.hsn_summary` so the screen and the download can
never disagree.
"""
from datetime import date as date_cls, timedelta

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from admin_panel.utils import csv_response
from products.hsn import RATES_AS_OF

from .gst_reports import hsn_summary, unclassified_products


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
