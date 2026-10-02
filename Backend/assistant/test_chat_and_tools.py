"""
Unified chat, assistant tools, and admin-assistant tests.
Includes catalogue/order tools, thread title generation, admin persona, and ordering flows.
"""
from datetime import timedelta
from decimal import Decimal
import json
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.utils import timezone

from assistant import tools as toolkit
from assistant.agent import Agent
from assistant.models import AssistantConversation, AssistantMessage
from conftest import create_test_image


# --------------------------------------------------------------------------- #
# Shared Helpers & Fixtures
# --------------------------------------------------------------------------- #

ADMIN_CHAT_URL = '/api/assistant/admin-chat/'
CHAT_URL = '/api/assistant/chat/'
LIST_URL = '/api/assistant/conversations/'
ADMIN_LIST_URL = '/api/assistant/conversations/admin/'


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _turn(content=None, calls=(), finish='stop'):
    """One scripted native-tool turn (AP9 contract)."""
    return {'content': content,
            'tool_calls': [{'name': n, 'args': a} for n, a in calls],
            'finish': finish}


def _script(monkeypatch, *responses):
    """Make the agent's LLM return the given turn-dicts in order."""
    it = iter(responses)
    monkeypatch.setattr('assistant.agent._build_llm', lambda: object())
    monkeypatch.setattr('assistant.agent.Agent._complete', lambda self, messages: next(it))


def _capture(monkeypatch, response):
    """Stub the LLM but record the message list it was handed."""
    captured = {}
    monkeypatch.setattr('assistant.agent._build_llm', lambda: object())

    def fake_complete(self, messages):
        captured['messages'] = messages
        return response

    monkeypatch.setattr('assistant.agent.Agent._complete', fake_complete)
    return captured


def _env(*, tool=None, args=None, final_reply=None, proposed_action=None, title=None,
         finish='stop', multi=None):
    calls = []
    if tool:
        calls.append((tool, args or {}))
    for name, call_args in (multi or []):
        calls.append((name, call_args or {}))
    if proposed_action:
        calls.append((proposed_action['tool'], proposed_action.get('args') or {}))
    return _turn(content=final_reply, calls=calls, finish=finish)


# --- From test_tools.py ---

# --------------------------------------------------------------------------- #
# Fixtures for Tools
# --------------------------------------------------------------------------- #

@pytest.fixture
def discounted_product(db, test_category):
    from products.models import Product
    return Product.objects.create(
        name='Discounted Chilli Powder',
        category=test_category,
        description='On offer',
        price=Decimal('200.00'),
        discount_price=Decimal('120.00'),
        stock=10,
        weight=Decimal('100.00'),
        unit='g',
        spice_form='powder',
        is_active=True,
        image=create_test_image('discounted.jpg'),
    )


@pytest.fixture
def review_for_product(db, test_product, test_user):
    from reviews.models import Review
    return Review.objects.create(
        item_type='product', product=test_product, user=test_user,
        rating=4, title='Good stuff', comment='Fresh and aromatic',
        is_verified_purchase=True,
    )


# --------------------------------------------------------------------------- #
# browse_products
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestBrowseProducts:
    def test_returns_active_products(self, test_product, test_product2):
        out = toolkit.tool_browse_products(None, {})
        names = {r['name'] for r in out['results']}
        assert test_product.name in names and test_product2.name in names

    def test_excludes_inactive(self, test_product, test_category):
        from products.models import Product
        Product.objects.create(
            name='Hidden Spice', category=test_category, description='x',
            price=Decimal('50'), stock=5, weight=Decimal('100'), unit='g',
            spice_form='powder', is_active=False,
            image=create_test_image('hidden.jpg'),
        )
        out = toolkit.tool_browse_products(None, {})
        assert 'Hidden Spice' not in {r['name'] for r in out['results']}

    def test_max_price_filter(self, test_product, test_product2):
        # test_product final 120, test_product2 final 200
        out = toolkit.tool_browse_products(None, {'max_price': 150, 'include_combos': False})
        prices = [r['price'] for r in out['results']]
        assert prices and all(p <= 150 for p in prices)

    def test_on_offer_filter(self, discounted_product, test_product2):
        # test_product2 has no discount_price; discounted_product does.
        out = toolkit.tool_browse_products(None, {'on_offer': True, 'include_combos': False})
        names = {r['name'] for r in out['results']}
        assert 'Discounted Chilli Powder' in names
        assert 'Test Cumin Seeds' not in names

    def test_spice_form_filter(self, test_product, test_product2):
        # test_product is 'powder', test_product2 is 'whole'
        out = toolkit.tool_browse_products(None, {'spice_form': 'whole', 'include_combos': False})
        names = {r['name'] for r in out['results']}
        assert 'Test Cumin Seeds' in names
        assert 'Test Turmeric Powder' not in names

    def test_sort_price_asc(self, test_product, test_product2):
        out = toolkit.tool_browse_products(None, {'sort': 'price_asc', 'include_combos': False})
        prices = [r['price'] for r in out['results']]
        assert prices == sorted(prices)

    def test_limit_is_capped(self, test_product):
        out = toolkit.tool_browse_products(None, {'limit': 9999})
        assert len(out['results']) <= toolkit.MAX_LIST_LIMIT

    def test_combos_included_by_default(self, test_combo):
        out = toolkit.tool_browse_products(None, {})
        types = {r['type'] for r in out['results']}
        assert 'combo' in types

    def test_only_public_fields(self, test_product):
        out = toolkit.tool_browse_products(None, {'include_combos': False})
        allowed = {'id', 'name', 'slug', 'type', 'price', 'original_price', 'in_stock', 'route'}
        for r in out['results']:
            assert set(r).issubset(allowed)
            assert 'stock' not in r and 'cost' not in r


# --------------------------------------------------------------------------- #
# get_product_reviews
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestGetProductReviews:
    def test_returns_summary_and_recent(self, test_product, review_for_product):
        out = toolkit.tool_get_product_reviews(None, {'slug': test_product.slug})
        assert out['review_count'] == 1
        assert out['average_rating'] == 4.0
        assert out['reviews'][0]['comment'] == 'Fresh and aromatic'
        assert out['reviews'][0]['verified_purchase'] is True

    def test_does_not_leak_reviewer_email(self, test_product, review_for_product, test_user):
        out = toolkit.tool_get_product_reviews(None, {'slug': test_product.slug})
        blob = str(out)
        assert test_user.email not in blob
        # Only the first name is exposed as 'reviewer'.
        assert out['reviews'][0]['reviewer'] == test_user.first_name

    def test_no_reviews_yet(self, test_product):
        out = toolkit.tool_get_product_reviews(None, {'slug': test_product.slug})
        assert out['review_count'] == 0
        assert out['average_rating'] is None
        assert out['reviews'] == []

    def test_unknown_slug(self):
        out = toolkit.tool_get_product_reviews(None, {'slug': 'no-such-thing'})
        assert out['error'] == 'not_found'

    def test_missing_slug(self):
        out = toolkit.tool_get_product_reviews(None, {})
        assert out['error'] == 'bad_args'


# --------------------------------------------------------------------------- #
# list_my_orders
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestListMyOrders:
    def test_anonymous_blocked(self):
        assert toolkit.tool_list_my_orders(None, {})['error'] == 'login_required'

    def test_lists_own_orders(self, test_order, test_user):
        out = toolkit.tool_list_my_orders(test_user, {})
        assert out['count'] == 1
        assert out['orders'][0]['order_number'] == f'ORD-{test_order.id:06d}'
        assert out['orders'][0]['item_count'] == 1

    def test_does_not_list_other_users_orders(self, test_order, test_user2):
        # test_order belongs to test_user; test_user2 must see nothing.
        out = toolkit.tool_list_my_orders(test_user2, {})
        assert out['count'] == 0
        assert out['orders'] == []

    def test_limit_capped(self, test_user):
        out = toolkit.tool_list_my_orders(test_user, {'limit': 9999})
        assert len(out['orders']) <= toolkit.MAX_LIST_LIMIT


# --------------------------------------------------------------------------- #
# get_order_details
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestGetOrderDetails:
    def test_anonymous_blocked(self):
        out = toolkit.tool_get_order_details(None, {'order_number': 'ORD-000001'})
        assert out['error'] == 'login_required'

    def test_own_order_items(self, test_order, test_user, test_product):
        num = f'ORD-{test_order.id:06d}'
        out = toolkit.tool_get_order_details(test_user, {'order_number': num})
        assert out['order_number'] == num
        assert len(out['items']) == 1
        item = out['items'][0]
        assert item['name'] == test_product.name
        assert item['item_type'] == 'product'
        assert item['product_id'] == test_product.id
        assert item['quantity'] == 2

    def test_other_users_order_is_not_found(self, test_order, test_user2):
        """G1: no existence oracle — another user's order looks identical to a
        non-existent one."""
        num = f'ORD-{test_order.id:06d}'
        out = toolkit.tool_get_order_details(test_user2, {'order_number': num})
        assert out['error'] == 'not_found'

    def test_injected_user_id_is_ignored(self, test_order, test_user, test_user2):
        num = f'ORD-{test_order.id:06d}'
        out = toolkit.tool_get_order_details(
            test_user2, {'order_number': num, 'user_id': test_user.id, 'email': test_user.email}
        )
        assert out['error'] == 'not_found'

    def test_bad_order_number(self, test_user):
        out = toolkit.tool_get_order_details(test_user, {'order_number': 'garbage'})
        assert out['error'] == 'bad_args'


# --------------------------------------------------------------------------- #
# Registry wiring
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestRegistry:
    def test_new_tools_registered(self):
        for name in ('browse_products', 'get_product_reviews',
                     'list_my_orders', 'get_order_details'):
            assert name in toolkit.READ_TOOLS
            assert name in toolkit.ALL_TOOL_NAMES

    def test_still_no_enumeration_of_users(self):
        for forbidden in ('list_users', 'search_customers', 'list_all_orders'):
            assert forbidden not in toolkit.ALL_TOOL_NAMES

    def test_run_read_tool_dispatches_new_tool(self, test_product):
        out = toolkit.run_read_tool('browse_products', None, {'include_combos': False})
        assert 'results' in out


# --- From test_unified_chat.py ---

# ==================== Thread title auto-generation ==================== #

@pytest.mark.django_db
class TestThreadTitle:
    # AP9: titles are derived server-side from the opening message (no LLM
    # round spent on them) — first turn only, HTML-stripped, max 80 chars.

    def test_title_set_on_first_turn(self, authenticated_client, monkeypatch):
        _script(monkeypatch, _env(final_reply='Sure!'))
        resp = authenticated_client.post(
            CHAT_URL, {'message': 'I want haldi powder for daily cooking needs please'},
            format='json')
        assert resp.status_code == 200
        conv = AssistantConversation.objects.get(conversation_id=resp.data['conversation_id'])
        assert conv.title == 'I want haldi powder for daily cooking needs'

    def test_title_not_overwritten_on_later_turns(self, authenticated_client, monkeypatch):
        _script(monkeypatch, _env(final_reply='First'), _env(final_reply='Second'))
        r1 = authenticated_client.post(CHAT_URL, {'message': 'one original message here'}, format='json')
        cid = r1.data['conversation_id']
        authenticated_client.post(
            CHAT_URL, {'message': 'two', 'conversation_id': cid}, format='json'
        )
        conv = AssistantConversation.objects.get(conversation_id=cid)
        assert conv.title == 'one original message here'

    def test_title_html_is_stripped(self, authenticated_client, monkeypatch):
        _script(monkeypatch, _env(final_reply='ok'))
        resp = authenticated_client.post(
            CHAT_URL, {'message': '<b>Spice</b> order for biryani night'}, format='json')
        conv = AssistantConversation.objects.get(conversation_id=resp.data['conversation_id'])
        assert '<' not in conv.title and 'Spice' in conv.title


# ==================== Admin in conversation ==================== #

@pytest.mark.django_db
class TestAdminReply:
    def _make_conv(self, user, needs_human=True):
        conv = AssistantConversation.objects.create(user=user, needs_human=needs_human)
        AssistantMessage.objects.create(conversation=conv, role='user', content='help me')
        return conv

    def test_admin_reply_creates_message_and_clears_flag(self, admin_client, test_admin, test_user):
        conv = self._make_conv(test_user)
        url = f'/api/assistant/conversations/{conv.conversation_id}/admin-reply/'
        resp = admin_client.post(url, {'message': 'On it!'}, format='json')
        assert resp.status_code == 200

        conv.refresh_from_db()
        assert conv.needs_human is False
        msg = conv.messages.get(role='admin')
        assert msg.content == 'On it!'
        assert msg.sender_name == 'Admin User'  # from test_admin first/last name

    def test_admin_reply_requires_staff(self, authenticated_client, test_user):
        conv = self._make_conv(test_user)
        url = f'/api/assistant/conversations/{conv.conversation_id}/admin-reply/'
        resp = authenticated_client.post(url, {'message': 'I am not staff'}, format='json')
        assert resp.status_code == 403
        assert not conv.messages.filter(role='admin').exists()

    def test_admin_reply_empty_message_rejected(self, admin_client, test_user):
        conv = self._make_conv(test_user)
        url = f'/api/assistant/conversations/{conv.conversation_id}/admin-reply/'
        resp = admin_client.post(url, {'message': '   '}, format='json')
        assert resp.status_code == 400

    def test_admin_reply_unknown_conversation_404(self, admin_client):
        import uuid
        url = f'/api/assistant/conversations/{uuid.uuid4()}/admin-reply/'
        resp = admin_client.post(url, {'message': 'hi'}, format='json')
        assert resp.status_code == 404

    def test_admin_message_reaches_llm_as_labeled_turn(self, test_user, monkeypatch):
        """The agent must surface admin turns to the model with a clear label so
        it knows a human joined."""
        history = [
            {'role': 'user', 'content': 'where is my order', 'sender_name': ''},
            {'role': 'admin', 'content': 'Let me check that for you.', 'sender_name': 'Kaushal'},
        ]
        captured = _capture(monkeypatch, _env(final_reply='Our team is helping you.'))
        Agent(test_user).run('thanks', history=history)
        joined = ' '.join(m[1] for m in captured['messages'])
        assert 'Kaushal' in joined and 'Nidhi Team' in joined


# ==================== Human handoff (AI pause) ==================== #

@pytest.mark.django_db
class TestHumanHandoff:
    """An admin replying takes the thread; the AI must stop answering it."""

    @staticmethod
    def _admin_client(test_admin):
        """A client of its own: the shared `admin_client`/`authenticated_client`
        fixtures both mutate the SAME api_client, so a test needing both an
        admin and a customer must not use them together."""
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(test_admin).access_token}'
        )
        return client

    def _conv_with_admin_reply(self, admin_client, test_user):
        conv = AssistantConversation.objects.create(user=test_user)
        url = f'/api/assistant/conversations/{conv.conversation_id}/admin-reply/'
        assert admin_client.post(url, {'message': 'I can help'}, format='json').status_code == 200
        conv.refresh_from_db()
        return conv

    def test_admin_reply_pauses_ai(self, admin_client, test_admin, test_user):
        conv = self._conv_with_admin_reply(admin_client, test_user)
        assert conv.ai_paused_at is not None
        assert conv.ai_paused_by == test_admin
        assert conv.is_ai_paused is True

    def test_customer_turn_gets_no_ai_reply_while_paused(
        self, authenticated_client, test_admin, test_user, monkeypatch
    ):
        conv = self._conv_with_admin_reply(self._admin_client(test_admin), test_user)
        # Scripted so that if the view DID call the LLM, it would say this.
        _capture(monkeypatch, _env(final_reply='I should never speak'))

        resp = authenticated_client.post(
            CHAT_URL,
            {'message': 'still there?', 'conversation_id': str(conv.conversation_id)},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['ai_paused'] is True
        assert resp.data['reply'] == ''
        # No assistant turn was written to the thread.
        assert not conv.messages.filter(role='assistant').exists()

    def test_customer_message_is_still_saved_and_reflagged(
        self, authenticated_client, test_admin, test_user, monkeypatch
    ):
        """Silence must never mean a lost message — it is persisted and the
        thread is re-raised for human attention."""
        conv = self._conv_with_admin_reply(self._admin_client(test_admin), test_user)
        conv.refresh_from_db()
        assert conv.needs_human is False      # admin just answered
        _capture(monkeypatch, _env(final_reply='nope'))
        authenticated_client.post(
            CHAT_URL,
            {'message': 'any update?', 'conversation_id': str(conv.conversation_id)},
            format='json',
        )
        conv.refresh_from_db()
        assert conv.needs_human is True
        assert conv.messages.filter(role='user', content='any update?').exists()

    def test_ai_auto_resumes_after_idle_window(self, admin_client, test_user):
        """Safety net: an admin who replies and disappears must not strand the
        customer with nobody answering."""
        import assistant.models as m
        conv = self._conv_with_admin_reply(admin_client, test_user)
        conv.ai_paused_at = timezone.now() - timedelta(hours=m.HANDOFF_IDLE_HOURS + 1)
        conv.save(update_fields=['ai_paused_at'])
        assert conv.is_ai_paused is False

    def test_idle_window_zero_means_never_auto_resume(self, admin_client, test_user, monkeypatch):
        import assistant.models as m
        monkeypatch.setattr(m, 'HANDOFF_IDLE_HOURS', 0)
        conv = self._conv_with_admin_reply(admin_client, test_user)
        conv.ai_paused_at = timezone.now() - timedelta(days=400)
        assert conv.is_ai_paused is True

    def test_ai_answers_again_after_idle_release(
        self, authenticated_client, test_admin, test_user, monkeypatch
    ):
        import assistant.models as m
        conv = self._conv_with_admin_reply(self._admin_client(test_admin), test_user)
        conv.ai_paused_at = timezone.now() - timedelta(hours=m.HANDOFF_IDLE_HOURS + 1)
        conv.save(update_fields=['ai_paused_at'])
        _capture(monkeypatch, _env(final_reply='Back with you'))
        resp = authenticated_client.post(
            CHAT_URL,
            {'message': 'hello?', 'conversation_id': str(conv.conversation_id)},
            format='json',
        )
        assert resp.data['ai_paused'] is False
        assert resp.data['reply'] == 'Back with you'

    def test_admin_can_hand_thread_back(self, admin_client, test_user):
        conv = self._conv_with_admin_reply(admin_client, test_user)
        url = f'/api/assistant/conversations/{conv.conversation_id}/'
        resp = admin_client.patch(url, {'ai_paused': False}, format='json')
        assert resp.status_code == 200
        assert resp.data['ai_paused'] is False
        conv.refresh_from_db()
        assert conv.ai_paused_at is None and conv.ai_paused_by is None

    def test_resolving_thread_releases_the_ai(self, admin_client, test_user):
        conv = self._conv_with_admin_reply(admin_client, test_user)
        url = f'/api/assistant/conversations/{conv.conversation_id}/'
        resp = admin_client.patch(url, {'status': 'resolved'}, format='json')
        assert resp.status_code == 200
        conv.refresh_from_db()
        assert conv.ai_paused_at is None

    def test_second_admin_reply_restarts_the_clock(self, admin_client, test_user):
        conv = self._conv_with_admin_reply(admin_client, test_user)
        stale = timezone.now() - timedelta(hours=11)
        conv.ai_paused_at = stale
        conv.save(update_fields=['ai_paused_at'])
        url = f'/api/assistant/conversations/{conv.conversation_id}/admin-reply/'
        admin_client.post(url, {'message': 'still here'}, format='json')
        conv.refresh_from_db()
        assert conv.ai_paused_at > stale

    def test_paused_thread_is_visible_to_admin_list(self, admin_client, test_user):
        self._conv_with_admin_reply(admin_client, test_user)
        resp = admin_client.get(ADMIN_LIST_URL)
        assert resp.status_code == 200
        assert resp.data[0]['ai_paused'] is True
        assert resp.data[0]['ai_paused_by'] == 'Admin User'


# ==================== Token-budgeted history ==================== #

@pytest.mark.django_db
class TestHistoryBudget:
    def test_full_recent_history_reaches_llm_when_small(self, test_user, monkeypatch):
        """A short thread is passed to the model in full (no fixed 8-msg cap)."""
        history = [
            {'role': 'user', 'content': f'msg {i}', 'sender_name': ''}
            for i in range(40)
        ]
        captured = _capture(monkeypatch, _env(final_reply='ok'))
        Agent(test_user).run('now', history=history)
        joined = ' '.join(m[1] for m in captured['messages'])
        # All 40 prior turns fit comfortably under the budget → none dropped.
        assert 'msg 0' in joined and 'msg 39' in joined

    def test_oldest_turns_dropped_when_over_budget(self, test_user, monkeypatch):
        """When history exceeds the token ceiling, oldest turns are trimmed while
        the newest are always kept — and the prompt stays under the ceiling."""
        import assistant.agent as agent_mod
        # Shrink the ceiling so the test is cheap and deterministic.
        monkeypatch.setattr(agent_mod, 'MODEL_CONTEXT_TOKENS', 4000)
        monkeypatch.setattr(agent_mod, 'TOOL_OBS_RESERVE_TOKENS', 0)
        big = 'x' * 3000  # ~1000 estimated tokens each
        history = [
            {'role': 'user', 'content': f'OLD{i} {big}', 'sender_name': ''}
            for i in range(10)
        ]
        history.append({'role': 'user', 'content': 'NEWEST tiny', 'sender_name': ''})
        captured = _capture(monkeypatch, _env(final_reply='ok'))
        Agent(test_user).run('now', history=history)
        joined = ' '.join(m[1] for m in captured['messages'])
        assert 'NEWEST' in joined        # newest turn always kept
        assert 'OLD0' not in joined       # oldest turns dropped
        total_tokens = sum(agent_mod._estimate_tokens(m[1]) for m in captured['messages'])
        assert total_tokens <= agent_mod.MODEL_CONTEXT_TOKENS

    def test_history_truncated_flag_false_when_everything_fits(self, test_user, monkeypatch):
        history = [{'role': 'user', 'content': f'msg {i}', 'sender_name': ''} for i in range(5)]
        _capture(monkeypatch, _env(final_reply='ok'))
        out = Agent(test_user).run('now', history=history)
        assert out['history_truncated'] is False

    def test_history_truncated_flag_set_when_turns_dropped(self, test_user, monkeypatch):
        """Dropping the oldest turns must be REPORTED, not silent — the client
        uses this to tell the customer to start a new conversation."""
        import assistant.agent as agent_mod
        monkeypatch.setattr(agent_mod, 'MODEL_CONTEXT_TOKENS', 4000)
        monkeypatch.setattr(agent_mod, 'TOOL_OBS_RESERVE_TOKENS', 0)
        big = 'x' * 3000
        history = [{'role': 'user', 'content': f'OLD{i} {big}', 'sender_name': ''}
                   for i in range(10)]
        _capture(monkeypatch, _env(final_reply='ok'))
        out = Agent(test_user).run('now', history=history)
        assert out['history_truncated'] is True

    def test_chat_endpoint_exposes_history_truncated(self, authenticated_client, monkeypatch):
        import assistant.agent as agent_mod
        monkeypatch.setattr(agent_mod, 'MODEL_CONTEXT_TOKENS', 4000)
        monkeypatch.setattr(agent_mod, 'TOOL_OBS_RESERVE_TOKENS', 0)
        _capture(monkeypatch, _env(final_reply='ok'))
        resp = authenticated_client.post(CHAT_URL, {'message': 'hi'}, format='json')
        assert resp.status_code == 200
        assert resp.data['history_truncated'] is False


# ==================== Customer thread endpoints ==================== #

@pytest.mark.django_db
class TestCustomerThreads:
    def test_list_own_threads_only(self, authenticated_client, test_user, test_user2):
        AssistantConversation.objects.create(user=test_user, title='mine')
        AssistantConversation.objects.create(user=test_user2, title='theirs')
        resp = authenticated_client.get(LIST_URL)
        assert resp.status_code == 200
        titles = [c['title'] for c in resp.data]
        assert 'mine' in titles and 'theirs' not in titles

    def test_create_thread(self, authenticated_client, test_user):
        resp = authenticated_client.post(LIST_URL, {}, format='json')
        assert resp.status_code == 201
        assert AssistantConversation.objects.filter(
            user=test_user, conversation_id=resp.data['conversation_id']
        ).exists()

    def test_anonymous_cannot_list(self, api_client):
        resp = api_client.get(LIST_URL)
        assert resp.status_code in (401, 403)

    def test_anonymous_cannot_chat(self, api_client):
        """The AI assistant is login-only: anonymous chat must be rejected before
        any LLM/agent work runs (resource + cost guard)."""
        resp = api_client.post(CHAT_URL, {'message': 'hello'}, format='json')
        assert resp.status_code in (401, 403)
        assert AssistantConversation.objects.count() == 0

    def test_last_message_preview_in_list(self, authenticated_client, test_user):
        conv = AssistantConversation.objects.create(user=test_user, title='t')
        AssistantMessage.objects.create(conversation=conv, role='user', content='first')
        AssistantMessage.objects.create(conversation=conv, role='assistant', content='latest reply')
        resp = authenticated_client.get(LIST_URL)
        assert resp.data[0]['last_message'] == 'latest reply'

    def test_messages_endpoint_excludes_tool_and_system(self, authenticated_client, test_user):
        conv = AssistantConversation.objects.create(user=test_user)
        AssistantMessage.objects.create(conversation=conv, role='user', content='q')
        AssistantMessage.objects.create(conversation=conv, role='tool', content='SECRET TOOL DATA')
        AssistantMessage.objects.create(conversation=conv, role='system', content='SYS')
        AssistantMessage.objects.create(conversation=conv, role='assistant', content='a')
        url = f'/api/assistant/conversations/{conv.conversation_id}/messages/'
        resp = authenticated_client.get(url)
        roles = [m['role'] for m in resp.data]
        assert roles == ['user', 'assistant']

    def test_customer_cannot_read_other_users_messages(
        self, authenticated_client_user2, test_user
    ):
        conv = AssistantConversation.objects.create(user=test_user)
        AssistantMessage.objects.create(conversation=conv, role='user', content='private')
        url = f'/api/assistant/conversations/{conv.conversation_id}/messages/'
        resp = authenticated_client_user2.get(url)
        assert resp.status_code == 404

    def test_admin_can_read_any_users_messages(self, admin_client, test_user):
        conv = AssistantConversation.objects.create(user=test_user)
        AssistantMessage.objects.create(conversation=conv, role='user', content='hello')
        url = f'/api/assistant/conversations/{conv.conversation_id}/messages/'
        resp = admin_client.get(url)
        assert resp.status_code == 200
        assert resp.data[0]['content'] == 'hello'


# ==================== Admin list / patch endpoints ==================== #

@pytest.mark.django_db
class TestAdminEndpoints:
    def test_admin_list_sees_all(self, admin_client, test_user, test_user2):
        AssistantConversation.objects.create(user=test_user, title='a')
        AssistantConversation.objects.create(user=test_user2, title='b')
        resp = admin_client.get(ADMIN_LIST_URL)
        assert resp.status_code == 200
        assert len(resp.data) == 2

    def test_admin_list_requires_staff(self, authenticated_client):
        resp = authenticated_client.get(ADMIN_LIST_URL)
        assert resp.status_code == 403

    def test_admin_list_filter_needs_human(self, admin_client, test_user):
        AssistantConversation.objects.create(user=test_user, title='flagged', needs_human=True)
        AssistantConversation.objects.create(user=test_user, title='calm', needs_human=False)
        resp = admin_client.get(ADMIN_LIST_URL, {'needs_human': 'true'})
        titles = [c['title'] for c in resp.data]
        assert titles == ['flagged']

    def test_admin_list_filter_status(self, admin_client, test_user):
        AssistantConversation.objects.create(user=test_user, title='open1', status='active')
        AssistantConversation.objects.create(user=test_user, title='done1', status='resolved')
        resp = admin_client.get(ADMIN_LIST_URL, {'status': 'resolved'})
        titles = [c['title'] for c in resp.data]
        assert titles == ['done1']

    def test_admin_list_pagination_limit(self, admin_client, test_user):
        for i in range(5):
            AssistantConversation.objects.create(user=test_user, title=f't{i}')
        resp = admin_client.get(ADMIN_LIST_URL, {'limit': 2})
        assert len(resp.data) == 2

    def test_admin_list_last_message_annotation(self, admin_client, test_user):
        conv = AssistantConversation.objects.create(user=test_user, title='t')
        AssistantMessage.objects.create(conversation=conv, role='user', content='old')
        AssistantMessage.objects.create(conversation=conv, role='admin', content='newest')
        resp = admin_client.get(ADMIN_LIST_URL)
        assert resp.data[0]['last_message'] == 'newest'

    def test_admin_patch_status(self, admin_client, test_user):
        conv = AssistantConversation.objects.create(user=test_user, status='active')
        url = f'/api/assistant/conversations/{conv.conversation_id}/'
        resp = admin_client.patch(url, {'status': 'resolved'}, format='json')
        assert resp.status_code == 200
        conv.refresh_from_db()
        assert conv.status == 'resolved'

    def test_admin_patch_requires_staff(self, authenticated_client, test_user):
        conv = AssistantConversation.objects.create(user=test_user, status='active')
        url = f'/api/assistant/conversations/{conv.conversation_id}/'
        resp = authenticated_client.patch(url, {'status': 'resolved'}, format='json')
        assert resp.status_code == 403


# ==================== Chat endpoint sad payloads ==================== #

@pytest.mark.django_db
class TestChatSadPayloads:
    def test_missing_message_field(self, authenticated_client, monkeypatch):
        _script(monkeypatch, _env(final_reply='x'))
        resp = authenticated_client.post(CHAT_URL, {}, format='json')
        assert resp.status_code == 400

    def test_whitespace_only_message(self, authenticated_client, monkeypatch):
        _script(monkeypatch, _env(final_reply='x'))
        resp = authenticated_client.post(CHAT_URL, {'message': '    '}, format='json')
        assert resp.status_code == 400

    def test_invalid_conversation_id_format(self, authenticated_client, monkeypatch):
        _script(monkeypatch, _env(final_reply='x'))
        resp = authenticated_client.post(
            CHAT_URL, {'message': 'hi', 'conversation_id': 'not-a-uuid'}, format='json'
        )
        assert resp.status_code == 400


# ==================== Voice-style ordering flow (end to end) ==================== #

@pytest.mark.django_db
class TestOrderingFlow:
    def test_search_then_confirm_then_add_to_cart(
        self, authenticated_client, test_product, test_user, monkeypatch
    ):
        """Mirrors the voice arc: model searches, then on the next turn proposes
        adding exactly one item, which the endpoint returns as a proposed_action."""
        add_action = {
            'tool': 'add_to_cart',
            'args': {'product_id': test_product.id, 'quantity': 1},
        }
        _script(
            monkeypatch,
            _env(tool='search_products', args={'query': 'turmeric'}),  # turn 1, step 1
            _env(final_reply='Found Test Turmeric Powder — ₹120. Add it?',
                 proposed_action=add_action),                            # turn 1, step 2
        )
        resp = authenticated_client.post(
            CHAT_URL, {'message': 'I want turmeric'}, format='json'
        )
        assert resp.status_code == 200
        action = resp.data['proposed_action']
        assert action is not None
        assert action['type'] == 'add_to_cart'
        assert action['quantity'] == 1
        # Proposal only — nothing was actually added to the cart.
        from cart.models import CartItem
        assert CartItem.objects.filter(cart__user=test_user).count() == 0


# --- From test_admin_assistant.py ---

@pytest.mark.django_db
class TestAdminAssistantAgent:
    def test_admin_persona_uses_admin_tools(self, test_admin, monkeypatch):
        """The admin agent can call a read tool the customer agent doesn't have
        (low_stock_products) and produce a final answer from the observation."""
        _script(
            monkeypatch,
            _env(tool='low_stock_products', args={}),
            _env(final_reply='You have 0 products running low.'),
        )
        result = Agent(test_admin, persona='admin').run('what is running low?')
        assert result['llm_used'] is True
        assert 'running low' in result['reply']
        assert any(s['tool'] == 'low_stock_products' for s in result['sources'])

    def test_admin_persona_has_no_actions(self, test_admin, monkeypatch):
        """Even if the model calls an action tool, the admin persona drops it
        (read-only): no add_to_cart/checkout ever comes back."""
        _script(monkeypatch, _turn(
            content='Here you go.',
            calls=[('add_to_cart', {'product_id': 1})],
        ))
        result = Agent(test_admin, persona='admin').run('add something')
        assert result['proposed_action'] is None

    def test_customer_agent_cannot_call_admin_tools(self, test_user, monkeypatch):
        """A customer-persona agent asked to call an admin tool is told it's not
        a valid tool (the name isn't in its registry) and never executes it."""
        _script(
            monkeypatch,
            _env(tool='low_stock_products', args={}),
            _env(final_reply='Sorry, I can only help you shop.'),
        )
        result = Agent(test_user, persona='customer').run('show me low stock')
        # The admin tool never ran → not recorded as a source.
        assert not any(s['tool'] == 'low_stock_products' for s in result['sources'])


@pytest.mark.django_db
class TestAdminChatEndpoint:
    def test_requires_staff(self, authenticated_client):
        resp = authenticated_client.post(ADMIN_CHAT_URL, {'message': 'hi'}, format='json')
        assert resp.status_code == 403

    def test_anonymous_rejected(self, api_client):
        resp = api_client.post(ADMIN_CHAT_URL, {'message': 'hi'}, format='json')
        assert resp.status_code in (401, 403)

    def test_staff_gets_reply(self, admin_client, monkeypatch):
        _script(monkeypatch, _env(final_reply='Sales look healthy.'))
        resp = admin_client.post(ADMIN_CHAT_URL, {'message': 'how are sales?'}, format='json')
        assert resp.status_code == 200
        assert resp.data['reply'] == 'Sales look healthy.'

    def test_empty_message_rejected(self, admin_client):
        resp = admin_client.post(ADMIN_CHAT_URL, {'message': '   '}, format='json')
        assert resp.status_code == 400
