import qrcode
from io import BytesIO
import base64
import csv

from django.http import StreamingHttpResponse


# Leading characters that spreadsheet apps (Excel/LibreOffice) treat as the
# start of a formula. Customer-controlled text (names, addresses, phone) ends up
# in these exports, so a value like `=HYPERLINK(...)` or `@SUM(...)` would run
# when the admin opens the file. We neutralise it by prefixing a single quote.
_CSV_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def _csv_safe(value):
    """Neutralise CSV formula-injection: escape any cell that a spreadsheet
    would evaluate as a formula. Non-string values pass through as text."""
    s = '' if value is None else str(value)
    if s and s[0] in _CSV_FORMULA_PREFIXES:
        return "'" + s
    return s


class _EchoWriter:
    """File-like object whose write() just returns the value — lets csv.writer
    produce one encoded line at a time for StreamingHttpResponse."""
    def write(self, value):
        return value


def csv_response(filename, header, rows):
    """Build a downloadable CSV as a streaming response.

    `header` is a list of column titles; `rows` is an iterable of lists/tuples
    already matching the header order. A UTF-8 BOM is streamed first so Excel on
    Windows opens Indian text and the ₹ symbol correctly (without it Excel
    mis-decodes UTF-8). Every cell is passed through `_csv_safe` to prevent
    formula injection from user-controlled data. Used by the admin export
    buttons (orders/products/customers) — never paginated: whatever queryset is
    passed is fully written, streamed row by row so a large table doesn't buffer
    the whole file in memory.
    """
    writer = csv.writer(_EchoWriter())

    def stream():
        yield '﻿'  # BOM for Excel
        yield writer.writerow([_csv_safe(h) for h in header])
        for row in rows:
            yield writer.writerow([_csv_safe(cell) for cell in row])

    response = StreamingHttpResponse(stream(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

def generate_upi_qr_code(account, amount=None, transaction_note="Payment"):
    """
    Generate UPI QR code base64 string for the given receivable account.
    
    :param account: ReceivableAccount instance
    :param amount: Optional payment amount (Decimal/float/str)
    :param transaction_note: Optional transaction note text
    :return: base64-encoded PNG image of the QR code, UPI payment URL string
    """
    from urllib.parse import quote
    
    # Mandatory fields: pa (upi_id), pn (account_holder_name)
    # Optional: am (amount), tn (transaction note), cu (currency)
    
    pn_encoded = quote(account.account_holder_name)
    tn_encoded = quote(transaction_note)
    
    upi_url = f"upi://pay?pa={account.upi_id}&pn={pn_encoded}"
    
    if amount is not None:
        upi_url += f"&am={amount}"
    
    upi_url += f"&cu=INR&tn={tn_encoded}"
    
    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(upi_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save to in-memory bytes buffer
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    # Encode image to base64 to embed or send over APIs
    qr_base64 = base64.b64encode(buffer.read()).decode("utf-8")
    
    return qr_base64, upi_url