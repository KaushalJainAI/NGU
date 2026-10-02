"""Refresh the seeded privacy policy content to the current, structured version.

The original seed (migration 0007) predates our DPDP-aligned policy. This brings
the stored `Policy(type='privacy')` content in line with what the storefront
Privacy Policy page presents, so any consumer of the DB copy stays consistent.
"""
from django.db import migrations


NEW_PRIVACY_CONTENT = """# Privacy Policy

This Privacy Policy explains how Nidhi Grah Udyog (Proprietor: Lalit Kumar Jain)
collects, uses, shares and protects your personal data when you use this website.
We handle your data in accordance with the Digital Personal Data Protection Act,
2023 (DPDP Act) and applicable Indian law. By using the website, you agree to this
Policy.

## 1. Data We Collect
- **Account & order details:** name, email, phone number, shipping address and order history.
- **Payment information:** we do not store your full payment credentials; UPI/payments are handled by the payment provider.
- **Usage & device data:** pages viewed, products browsed and approximate (coarse) location, used to improve the site and recommendations.

## 2. Purpose & Legal Basis
We process your personal data for specified, lawful purposes: to process and
deliver your orders, provide customer support, personalise recommendations, run
anonymous aggregate analytics, send order updates, and (with your consent)
promotional communication. We rely on your consent and on the necessity of
processing to fulfil the services you request.

## 3. Consent
You may withdraw your consent at any time by contacting us. Withdrawing consent
will not affect the lawfulness of processing carried out before withdrawal, and
may limit our ability to provide certain services.

## 4. Sharing of Data
We share your data only with trusted service providers (courier/logistics
partners, payment processors, hosting/analytics providers) to the extent necessary
to operate the service. We do not sell your personal data. We may disclose data
where required by law.

## 5. Cookies & Analytics
We use cookies and similar technologies to keep you logged in, remember your cart,
and understand how the website is used through anonymous, aggregate analytics. You
can control cookies through your browser settings and the on-site cookie notice.

## 6. Data Security & Retention
We use reasonable technical and organisational safeguards to protect your data. We
retain personal data only as long as necessary to provide our services and to meet
legal, accounting and tax obligations.

## 7. Your Rights (DPDP Act, 2023)
You have the right to access, correct, update and erase your personal data, to
nominate, and to grievance redressal. To exercise any right, contact us using the
details below.

## 8. Grievance Officer
Ankur Jain • +91 93000 05040. We acknowledge grievances within 48 hours and aim to
resolve them within 30 days.

## 9. Contact Us
Nidhi Grah Udyog, 7, Industrial Area, Runija Road, Barnagar, Ujjain, Madhya Pradesh
456771. Email nidhigrahudyog@rediffmail.com or call +91 93000 05040, or use our
Contact page.
"""

# Original seed text, so the migration can be reversed cleanly.
OLD_PRIVACY_CONTENT = """# Privacy Policy

Your privacy matters to us. This policy explains what we collect and why.

## Information you provide
When you create an account or place an order we collect your name, email,
phone number and shipping address so we can fulfil and support your orders.

## How we use your data
- To process orders, payments and deliveries.
- To provide account features such as order history and favorites.
- To personalise product recommendations for you when you are signed in,
  based on your browsing and purchase activity.

## Analytics
- **Signed-in activity:** for logged-in users we record product views,
  searches, cart activity and purchases to power personalised recommendations
  and to understand how our store is used.
- **Anonymous visitors:** for visitors who are not signed in we collect only
  aggregate, non-identifying statistics (such as overall page views, device
  type and approximate region derived from IP at a city/state level). We do not
  store a profile, a cookie identifier, or anything that can recognise an
  individual or a returning visitor.

## What we do not do
We do not sell your personal data. We do not use precise location, and coarse
region data for anonymous visitors is only ever stored as aggregate counts.

## Data retention
Order and account data is retained while your account is active. Aggregate
analytics are retained in summarised form and contain no personal identifiers.

## Contact
For any privacy questions or to request deletion of your account data, please
contact us through the Contact page.
"""


def _set_privacy(apps, content):
    Policy = apps.get_model("admin_panel", "Policy")
    Policy.objects.update_or_create(type="privacy", defaults={"content": content})


def forward(apps, schema_editor):
    _set_privacy(apps, NEW_PRIVACY_CONTENT)


def backward(apps, schema_editor):
    _set_privacy(apps, OLD_PRIVACY_CONTENT)


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0008_create_save10_coupon"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
