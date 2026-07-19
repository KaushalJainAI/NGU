"""
Tests for the analytics insights system: anonymous counters, the rollup
command, admin-only insights API, granularity bucketing, caching, and purchase signals.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from analytics import insights
from analytics.anon import record_anon, _device, _source
from analytics.models import (
    DailyAnonStat, DailyFunnelRollup, DailySalesRollup, SearchTermStat, UserEvent,
)
from orders.models import Order, OrderItem


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _make_order(user, when, total, status='confirmed', coupon=None, discount=0):
    order = Order.objects.create(
        user=user,
        shipping_address='addr',
        phone_number='123',
        payment_method='COD',
        subtotal=Decimal(total),
        discount_amount=Decimal(discount),
        total_amount=Decimal(total),
        status=status,
        coupon=coupon,
    )
    # created_at is auto_now_add; force it to the desired instant.
    Order.objects.filter(pk=order.pk).update(created_at=when)
    order.refresh_from_db()
    return order


def _rf(user_agent='Mozilla/5.0 (Windows NT 10.0)', referer='', remote='8.8.8.8'):
    """A minimal request-like object for record_anon (avoids HTTP overhead)."""
    from django.test import RequestFactory
    req = RequestFactory().post('/api/anon-events/')
    req.META['HTTP_USER_AGENT'] = user_agent
    if referer:
        req.META['HTTP_REFERER'] = referer
    req.META['REMOTE_ADDR'] = remote
    return req


# --- From test_analytics_insights.py ---

# --------------------------------------------------------------------------- #
# anonymous counters
# --------------------------------------------------------------------------- #

class TestAnonHelpers:
    def test_device_classification(self):
        assert _device('iPhone Mobile Safari') == 'mobile'
        assert _device('Mozilla/5.0 (Windows NT 10.0)') == 'desktop'
        assert _device('Googlebot/2.1') == 'bot'
        assert _device('Mozilla/5.0 (iPad; ...)') == 'tablet'

    def test_source_buckets(self):
        assert _source('', 'shop.com') == 'direct'
        assert _source('https://www.google.com/search', 'shop.com') == 'google'
        assert _source('https://facebook.com/x', 'shop.com') == 'social'
        assert _source('https://blog.example.com', 'shop.com') == 'referral'
        # internal navigation is not a traffic source
        assert _source('https://shop.com/cart', 'shop.com') is None


@pytest.mark.django_db
class TestRecordAnon:
    def test_increments_total_and_device(self):
        record_anon('page_view', _rf())
        total = DailyAnonStat.objects.get(
            date=timezone.localdate(), metric='page_view', dimension_key='')
        device = DailyAnonStat.objects.get(
            date=timezone.localdate(), metric='page_view', dimension_key='device:desktop')
        assert total.count == 1
        assert device.count == 1

    def test_repeated_events_accumulate_not_explode(self):
        for _ in range(5):
            record_anon('page_view', _rf())
        # 5 events, still ONE row per (metric, dimension) — bounded storage.
        total = DailyAnonStat.objects.get(
            date=timezone.localdate(), metric='page_view', dimension_key='')
        assert total.count == 5
        assert DailyAnonStat.objects.filter(metric='page_view', dimension_key='').count() == 1

    def test_zero_result_search_bumps_extra_metric(self):
        record_anon('search', _rf(), query='asdfqwer', zero=True)
        assert DailyAnonStat.objects.filter(metric='search', dimension_key='').exists()
        assert DailyAnonStat.objects.filter(metric='search_zero_result', dimension_key='').exists()

    def test_disallowed_metric_is_ignored(self):
        record_anon('totally_made_up', _rf())
        assert DailyAnonStat.objects.count() == 0

    def test_bot_bucketed_separately(self):
        record_anon('page_view', _rf(user_agent='Googlebot/2.1'))
        assert DailyAnonStat.objects.filter(dimension_key='device:bot').exists()


@pytest.mark.django_db
class TestAnonEndpoint:
    def test_anonymous_user_can_post_and_gets_204(self, api_client):
        resp = api_client.post('/api/anon-events/', {'metric': 'page_view'}, format='json')
        assert resp.status_code == 204
        assert DailyAnonStat.objects.filter(metric='page_view').exists()

    def test_bad_metric_still_204_no_row(self, api_client):
        resp = api_client.post('/api/anon-events/', {'metric': 'nope'}, format='json')
        assert resp.status_code == 204
        assert DailyAnonStat.objects.count() == 0


# --------------------------------------------------------------------------- #
# rollup command
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestRollupCommand:
    def test_sales_rollup_basic(self, test_user, test_coupon):
        today = timezone.localdate()
        now = timezone.now()
        _make_order(test_user, now, '100.00')
        _make_order(test_user, now, '300.00', coupon=test_coupon, discount='30.00')
        # cancelled orders are excluded from realised revenue
        _make_order(test_user, now, '999.00', status='cancelled')

        call_command('rollup_analytics', '--date', today.isoformat())

        roll = DailySalesRollup.objects.get(date=today)
        assert roll.orders == 2
        assert roll.revenue == Decimal('400.00')
        assert roll.coupon_orders == 1
        assert roll.aov == Decimal('200.00')

    def test_new_vs_returning(self, test_user, test_user2):
        today = timezone.localdate()
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        # test_user ordered yesterday and today -> returning today
        _make_order(test_user, yesterday, '50.00')
        _make_order(test_user, now, '50.00')
        # test_user2 first ever order is today -> new
        _make_order(test_user2, now, '70.00')

        call_command('rollup_analytics', '--date', today.isoformat())
        roll = DailySalesRollup.objects.get(date=today)
        assert roll.new_customers == 1
        assert roll.returning_customers == 1

    def test_funnel_and_search_rollup(self, test_user, test_product):
        today = timezone.localdate()
        UserEvent.objects.create(user=test_user, event_type='view', product=test_product)
        UserEvent.objects.create(user=test_user, event_type='view', product=test_product)
        UserEvent.objects.create(user=test_user, event_type='add_to_cart', product=test_product)
        UserEvent.objects.create(user=test_user, event_type='search', query='Turmeric',
                                 metadata={'zero': False})
        UserEvent.objects.create(user=test_user, event_type='search', query='xyzzy',
                                 metadata={'zero': True})

        call_command('rollup_analytics', '--date', today.isoformat())

        assert DailyFunnelRollup.objects.get(date=today, event_type='view').count == 2
        assert DailyFunnelRollup.objects.get(date=today, event_type='add_to_cart').count == 1
        assert SearchTermStat.objects.get(date=today, term='turmeric').count == 1
        assert SearchTermStat.objects.get(date=today, term='xyzzy').zero_result is True

    def test_idempotent_rerun(self, test_user):
        today = timezone.localdate()
        _make_order(test_user, timezone.now(), '100.00')
        call_command('rollup_analytics', '--date', today.isoformat())
        call_command('rollup_analytics', '--date', today.isoformat())
        # Re-run must not double-count.
        assert DailySalesRollup.objects.filter(date=today).count() == 1
        assert DailySalesRollup.objects.get(date=today).orders == 1


# --------------------------------------------------------------------------- #
# insights aggregation + API
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestInsightsAggregation:
    def test_sales_pop_delta(self, test_user):
        today = timezone.localdate()
        # current window (today): revenue 100; previous day: revenue 50 -> +100%
        DailySalesRollup.objects.create(date=today, orders=1, revenue=Decimal('100'))
        DailySalesRollup.objects.create(date=today - timedelta(days=1), orders=1,
                                        revenue=Decimal('50'))
        data = insights.sales(today, today, 'day')
        assert data['kpis']['revenue'] == 100.0
        assert data['kpis']['revenue_delta_pct'] == 100.0

    def test_funnel_conversion(self):
        today = timezone.localdate()
        DailyFunnelRollup.objects.create(date=today, event_type='view', count=100)
        DailyFunnelRollup.objects.create(date=today, event_type='add_to_cart', count=40)
        DailyFunnelRollup.objects.create(date=today, event_type='purchase', count=10)
        data = insights.funnel(today, today)
        stages = {s['stage']: s for s in data['stages']}
        assert stages['add_to_cart']['pct_of_top'] == 40.0
        assert stages['purchase']['count'] == 10

    def test_anonymous_macro_funnel_and_breakdowns(self):
        today = timezone.localdate()
        DailyAnonStat.objects.create(date=today, metric='page_view', dimension_key='', count=200)
        DailyAnonStat.objects.create(date=today, metric='page_view',
                                     dimension_key='device:mobile', count=150)
        DailyAnonStat.objects.create(date=today, metric='page_view',
                                     dimension_key='state:Maharashtra', count=120)
        DailyAnonStat.objects.create(date=today, metric='product_view', dimension_key='', count=80)
        data = insights.anonymous(today, today)
        assert data['totals']['page_view'] == 200
        assert {d['device']: d['count'] for d in data['by_device']}['mobile'] == 150
        assert {d['state']: d['count'] for d in data['by_state']}['Maharashtra'] == 120
        macro = {s['stage']: s for s in data['macro_funnel']}
        assert macro['product_view']['pct_of_top'] == 40.0


@pytest.mark.django_db
class TestInsightsAPI:
    def test_requires_admin(self, authenticated_client):
        resp = authenticated_client.get('/api/analytics/sales/')
        assert resp.status_code == 403

    def test_anonymous_user_denied(self, api_client):
        resp = api_client.get('/api/analytics/sales/')
        assert resp.status_code in (401, 403)

    def test_admin_can_read_all_endpoints(self, admin_client, test_user):
        today = timezone.localdate()
        DailySalesRollup.objects.create(date=today, orders=2, revenue=Decimal('500'))
        for path in ['sales', 'funnel', 'search', 'customers', 'anonymous']:
            resp = admin_client.get(f'/api/analytics/{path}/')
            assert resp.status_code == 200, f'{path} -> {resp.status_code}'

    def test_sales_endpoint_returns_kpis(self, admin_client):
        today = timezone.localdate()
        DailySalesRollup.objects.create(date=today, orders=2, revenue=Decimal('500'), units=5)
        resp = admin_client.get('/api/analytics/sales/',
                                {'from': today.isoformat(), 'to': today.isoformat()})
        assert resp.status_code == 200
        assert resp.data['kpis']['revenue'] == 500.0
        assert resp.data['kpis']['orders'] == 2


# --- From test_analytics_extra.py ---

# --------------------------------------------------------------------------- #
# granularity bucketing
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestGranularity:
    def test_weekly_buckets_collapse_days(self):
        # Three consecutive days in the same ISO week roll into one bucket.
        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        for i in range(3):
            DailySalesRollup.objects.create(
                date=monday + timedelta(days=i), orders=1, revenue=Decimal('10'))
        data = insights.sales(monday, monday + timedelta(days=2), 'week')
        assert len(data['series']) == 1
        assert data['series'][0]['revenue'] == 30.0

    def test_monthly_buckets(self):
        first = timezone.localdate().replace(day=1)
        DailySalesRollup.objects.create(date=first, orders=1, revenue=Decimal('5'))
        DailySalesRollup.objects.create(date=first + timedelta(days=1), orders=1,
                                        revenue=Decimal('7'))
        data = insights.sales(first, first + timedelta(days=1), 'month')
        assert len(data['series']) == 1
        assert data['series'][0]['revenue'] == 12.0


# --------------------------------------------------------------------------- #
# period-over-period edge cases
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestDeltas:
    def test_delta_none_when_no_prior_baseline(self):
        today = timezone.localdate()
        DailySalesRollup.objects.create(date=today, orders=1, revenue=Decimal('100'))
        data = insights.sales(today, today, 'day')
        # No previous window data -> delta undefined (None), not a crash.
        assert data['kpis']['revenue_delta_pct'] is None

    def test_empty_range_is_zeroed(self):
        today = timezone.localdate()
        data = insights.sales(today, today, 'day')
        assert data['kpis']['revenue'] == 0
        assert data['kpis']['aov'] == 0
        assert data['series'] == []


# --------------------------------------------------------------------------- #
# customers + search aggregation
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestCustomersAndSearch:
    def test_repeat_rate(self):
        today = timezone.localdate()
        DailySalesRollup.objects.create(date=today, orders=4, revenue=Decimal('100'),
                                        new_customers=1, returning_customers=3)
        data = insights.customers(today, today, 'day')
        assert data['kpis']['repeat_rate_pct'] == 75.0
        assert data['kpis']['new_customers'] == 1

    def test_top_customers_and_geo(self, test_user, test_product):
        from analytics.models import UserGeo
        UserGeo.objects.create(user=test_user, state='Maharashtra')
        order = Order.objects.create(
            user=test_user, shipping_address='a', phone_number='1',
            payment_method='COD', subtotal=Decimal('200'), total_amount=Decimal('200'),
            status='confirmed')
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now())
        today = timezone.localdate()
        data = insights.customers(today, today, 'day')
        assert any(c['email'] == test_user.email for c in data['top_customers'])
        assert any(g['state'] == 'Maharashtra' for g in data['geo'])

    def test_viewed_not_bought_excludes_purchased(self, test_user, test_product, test_product2):
        # product viewed but never purchased -> appears
        UserEvent.objects.create(user=test_user, event_type='view', product=test_product)
        # product2 viewed AND purchased -> excluded
        UserEvent.objects.create(user=test_user, event_type='view', product=test_product2)
        UserEvent.objects.create(user=test_user, event_type='purchase', product=test_product2)
        today = timezone.localdate()
        data = insights.search(today, today)
        ids = [r['product_id'] for r in data['viewed_not_bought']]
        assert test_product.id in ids
        assert test_product2.id not in ids


# --------------------------------------------------------------------------- #
# anonymous source classification through the full record path
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestAnonSource:
    def test_referer_drives_source_dimension(self):
        record_anon('page_view', _rf(referer='https://www.google.com/search?q=spice'))
        assert DailyAnonStat.objects.filter(
            metric='page_view', dimension_key='source:google').exists()

    def test_direct_when_no_referer(self):
        record_anon('page_view', _rf())
        assert DailyAnonStat.objects.filter(
            metric='page_view', dimension_key='source:direct').exists()


# --------------------------------------------------------------------------- #
# date-param parsing + caching at the view layer
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestViewParams:
    def test_invalid_dates_fall_back_to_default(self, admin_client):
        resp = admin_client.get('/api/analytics/sales/',
                                {'from': 'garbage', 'to': 'also-bad'})
        assert resp.status_code == 200  # defaults applied, no 500

    def test_invalid_granularity_defaults_to_day(self, admin_client):
        resp = admin_client.get('/api/analytics/sales/', {'granularity': 'decade'})
        assert resp.status_code == 200
        assert resp.data['range']['granularity'] == 'day'

    def test_overview_endpoint(self, admin_client):
        today = timezone.localdate()
        DailySalesRollup.objects.create(date=today, orders=3, revenue=Decimal('300'),
                                        new_customers=1, returning_customers=2)
        resp = admin_client.get('/api/analytics/overview/',
                                {'from': today.isoformat(), 'to': today.isoformat()})
        assert resp.status_code == 200
        assert resp.data['kpis']['revenue'] == 300.0
        assert resp.data['kpis']['repeat_rate_pct'] == 66.7
        assert 'funnel' in resp.data and 'anon_by_device' in resp.data

    def test_overview_requires_admin(self, authenticated_client):
        assert authenticated_client.get('/api/analytics/overview/').status_code == 403

    def test_response_is_cached(self, admin_client):
        today = timezone.localdate()
        DailySalesRollup.objects.create(date=today, orders=1, revenue=Decimal('100'))
        params = {'from': today.isoformat(), 'to': today.isoformat()}
        first = admin_client.get('/api/analytics/sales/', params)
        assert first.data['kpis']['revenue'] == 100.0
        # Mutate underlying data; cached response should be unchanged within TTL.
        DailySalesRollup.objects.filter(date=today).update(revenue=Decimal('999'))
        second = admin_client.get('/api/analytics/sales/', params)
        assert second.data['kpis']['revenue'] == 100.0


# --------------------------------------------------------------------------- #
# decoupled purchase-capture signal
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestPurchaseSignal:
    def test_order_creation_records_purchase_events(
        self, test_user, test_product, django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            order = Order.objects.create(
                user=test_user, shipping_address='a', phone_number='1',
                payment_method='COD', subtotal=Decimal('120'),
                total_amount=Decimal('120'), status='confirmed')
            OrderItem.objects.create(
                order=order, product=test_product, item_type='product',
                product_name=test_product.name, product_weight='250g',
                quantity=1, price=Decimal('120'), final_price=Decimal('120'))
        # The post_save -> on_commit receiver should have logged a purchase event.
        assert UserEvent.objects.filter(
            user=test_user, event_type='purchase', product=test_product).exists()
