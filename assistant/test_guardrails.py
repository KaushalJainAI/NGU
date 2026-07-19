"""Guardrail tests for the AI assistant (G1–G6).

The LLM is never called for real — `_build_llm` is stubbed to a sentinel and
`Agent._complete` is monkeypatched to return scripted JSON envelopes. The real
security boundary (tools.py) is unit-tested directly.
"""
import json

import pytest
from django.core.cache import cache
from django.contrib.auth.models import AnonymousUser

from assistant import tools as toolkit
from assistant.agent import Agent
from assistant.models import AssistantConversation, AssistantMessage


@pytest.fixture(autouse=True)
def _clear_cache():
    # Throttle counters + search corpus live in the locmem cache; isolate tests.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def policy_shipping(db):
    from admin_panel.models import Policy
    return Policy.objects.create(type='shipping', content='We ship in 3-5 days.')


def _script(monkeypatch, *responses):
    """Make the agent's LLM return the given strings in order."""
    it = iter(responses)
    monkeypatch.setattr('assistant.agent._build_llm', lambda: object())
    monkeypatch.setattr('assistant.agent.Agent._complete', lambda self, messages: next(it))


def _env(tool=None, args=None, final_reply=None, proposed_action=None):
    return json.dumps({
        'thought': 't', 'tool': tool, 'args': args or {},
        'final_reply': final_reply, 'proposed_action': proposed_action,
    })


# ==================== G1 — cross-user data isolation ====================

@pytest.mark.django_db
class TestG1Isolation:
    def test_order_status_other_user_is_not_found(self, test_order, test_user2):
        """A user querying someone else's order number gets the same 'not found'
        as a non-existent order — no leak, no existence oracle."""
        num = f"ORD-{test_order.id:06d}"  # belongs to test_user
        res = toolkit.tool_get_order_status(test_user2, {'order_number': num})
        assert res['error'] == 'not_found'

    def test_order_status_own_order_works(self, test_order, test_user):
        num = f"ORD-{test_order.id:06d}"
        res = toolkit.tool_get_order_status(test_user, {'order_number': num})
        assert res['status'] == 'pending'
        assert res['order_number'] == num

    def test_injected_user_identifier_is_ignored(self, test_order, test_user, test_user2):
        """Even if the model smuggles a user_id/email into args, the tool scopes
        strictly to the caller — user2 still cannot read user1's order."""
        num = f"ORD-{test_order.id:06d}"
        res = toolkit.tool_get_order_status(
            test_user2, {'order_number': num, 'user_id': test_user.id, 'email': test_user.email}
        )
        assert res['error'] == 'not_found'

    def test_anon_blocked_from_order_and_cart(self):
        assert toolkit.tool_get_order_status(None, {'order_number': 'ORD-000001'})['error'] == 'login_required'
        assert toolkit.tool_get_cart(None, {})['error'] == 'login_required'

    def test_user_cannot_resume_another_users_conversation(self, authenticated_client_user2, test_user, monkeypatch):
        conv = AssistantConversation.objects.create(user=test_user)
        AssistantMessage.objects.create(conversation=conv, role='user', content='secret of user1')
        _script(monkeypatch, _env(final_reply='hi'))
        resp = authenticated_client_user2.post(
            '/api/assistant/chat/',
            {'message': 'hello', 'conversation_id': str(conv.conversation_id)},
            format='json',
        )
        assert resp.status_code == 200
        # A fresh conversation is started rather than loading user1's thread.
        assert resp.data['conversation_id'] != str(conv.conversation_id)


# ==================== G2 — platform / internal data protection ====================

@pytest.mark.django_db
class TestG2PlatformData:
    def test_product_details_exposes_only_public_fields(self, test_product):
        res = toolkit.tool_get_product_details(test_product, {'slug': test_product.slug})
        # No cost price, margins, raw stock count, or internal flags.
        assert set(res).issubset({
            'id', 'name', 'slug', 'type', 'price', 'original_price', 'in_stock',
            'route', 'category', 'spice_form', 'weight', 'description', 'ingredients',
        })
        assert 'cost' not in res and 'stock' not in res

    def test_policy_returns_only_kind_and_content(self, policy_shipping):
        res = toolkit.tool_get_policy(None, {'kind': 'shipping'})
        assert set(res) == {'kind', 'content'}

    def test_registry_has_no_enumeration_or_admin_tools(self):
        for forbidden in ('list_orders', 'list_users', 'search_customers', 'run_sql', 'get_config'):
            assert forbidden not in toolkit.ALL_TOOL_NAMES


# ==================== G3 — prompt injection ====================

@pytest.mark.django_db
class TestG3Injection:
    def test_unknown_tool_is_not_executed(self, monkeypatch):
        # Model tries a non-existent tool, then answers normally.
        _script(monkeypatch, _env(tool='delete_all_users', args={}), _env(final_reply='Done'))
        out = Agent(None).run('hi')
        assert out['reply'] == 'Done'
        assert out['sources'] == []  # nothing executed

    def test_malformed_output_falls_back_safely(self, monkeypatch):
        _script(monkeypatch, 'not json at all', 'still not json')
        out = Agent(None).run('hi')
        assert out['llm_used'] is True
        assert out['escalate'] is True
        assert 'trouble' in out['reply'].lower()

    def test_indirect_injection_in_proposal_is_clamped_not_executed(self, test_product, test_user, monkeypatch):
        """A proposed add-to-cart with an absurd quantity is clamped and never
        mutates the cart in the loop (G5 too)."""
        action = {'tool': 'add_to_cart',
                  'args': {'product_id': test_product.id, 'quantity': 999}}
        _script(monkeypatch, _env(final_reply='Adding', proposed_action=action))
        out = Agent(test_user).run('add 999')
        assert out['proposed_action']['quantity'] == toolkit.MAX_PROPOSE_QTY
        from cart.models import CartItem
        assert CartItem.objects.filter(cart__user=test_user).count() == 0


# ==================== G4 — abuse / cost / DoS ====================

@pytest.mark.django_db
class TestG4Abuse:
    def test_loop_stops_at_max_iterations(self, policy_shipping, monkeypatch):
        # Model keeps calling a read tool forever; loop must bail to fallback.
        many = [_env(tool='get_policy', args={'kind': 'shipping'})] * 10
        _script(monkeypatch, *many)
        out = Agent(None).run('policy?')
        assert out['escalate'] is True  # exhausted -> safe fallback

    def test_message_over_length_rejected(self, authenticated_client):
        resp = authenticated_client.post(
            '/api/assistant/chat/', {'message': 'A' * 1001}, format='json'
        )
        assert resp.status_code == 400

    def test_burst_throttle_returns_429(self, authenticated_client, monkeypatch):
        _script(monkeypatch, *[_env(final_reply='ok')] * 60)
        # Re-stub per call isn't needed; _complete is patched on the class.
        codes = set()
        for _ in range(25):
            r = authenticated_client.post('/api/assistant/chat/', {'message': 'hi'}, format='json')
            codes.add(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in codes


# ==================== G5 — action safety ====================

@pytest.mark.django_db
class TestG5Actions:
    def test_navigate_allowlist_blocks_external(self, test_user):
        ok, _ = toolkit.build_navigate(test_user, {'route': '/products'})
        assert ok['route'] == '/products'
        bad, msg = toolkit.build_navigate(test_user, {'route': 'https://evil.example/phish'})
        assert bad is None and msg
        admin, _ = toolkit.build_navigate(test_user, {'route': '/admin'})
        assert admin is None

    def test_add_to_cart_out_of_stock_refused(self, out_of_stock_product, test_user):
        action, msg = toolkit.build_add_to_cart(
            test_user, {'product_id': out_of_stock_product.id, 'quantity': 1}
        )
        assert action is None and 'stock' in msg.lower()

    def test_checkout_anon_routes_to_login(self):
        action, _ = toolkit.build_checkout(None, {})
        assert action['route'] == '/login'


# ==================== G6 — output safety & audit ====================

@pytest.mark.django_db
class TestG6OutputAudit:
    def test_reply_html_tags_stripped(self, monkeypatch):
        _script(monkeypatch, _env(final_reply="<script>alert('hi')</script> hello there"))
        out = Agent(None).run('hi')
        # Tags removed (no executable markup), readable text preserved.
        assert '<script>' not in out['reply'] and '<' not in out['reply']
        assert 'hello there' in out['reply']

    def test_reply_strips_urls(self, monkeypatch):
        _script(monkeypatch, _env(final_reply="Visit https://evil.example/phish now"))
        out = Agent(None).run('hi')
        assert 'http' not in out['reply']

    def test_endpoint_persists_audit_trail(self, authenticated_client, test_user, monkeypatch):
        _script(monkeypatch, _env(final_reply='Hello!'))
        resp = authenticated_client.post('/api/assistant/chat/', {'message': 'hi'}, format='json')
        assert resp.status_code == 200
        conv = AssistantConversation.objects.get(conversation_id=resp.data['conversation_id'])
        roles = list(conv.messages.values_list('role', flat=True))
        assert roles == ['user', 'assistant']
        meta = conv.messages.get(role='assistant').meta
        assert 'sources' in meta and 'proposed_action' in meta

    def test_escalation_flags_thread_for_human(self, authenticated_client, monkeypatch):
        """Unified chat: escalation flags the thread (needs_human). The separate
        support.ChatSession system has been removed entirely."""
        _script(monkeypatch, 'broken', 'broken')  # forces fallback -> escalate
        resp = authenticated_client.post('/api/assistant/chat/', {'message': 'help'}, format='json')
        assert resp.status_code == 200
        conv = AssistantConversation.objects.get(conversation_id=resp.data['conversation_id'])
        assert conv.needs_human is True


# ==================== LLM-unavailable degradation ====================

@pytest.mark.django_db
def test_agent_degrades_without_llm(monkeypatch):
    monkeypatch.setattr('assistant.agent._build_llm', lambda: None)
    out = Agent(None).run('hello')
    assert out['llm_used'] is False
    assert out['escalate'] is True
