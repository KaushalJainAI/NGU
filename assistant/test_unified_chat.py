"""Integration tests for the unified chat system.

Covers the new multi-thread + admin-in-conversation behaviour added on top of
the AI assistant:
  - thread title auto-generation (first turn only)
  - admin role: reply endpoint, history inclusion, needs_human lifecycle
  - customer thread list / create / messages endpoints (+ isolation)
  - admin list / reply / patch endpoints (+ permission gates)
  - N+1-avoiding last_message annotation and limit/offset pagination

The LLM is never called for real — `_build_llm` is stubbed and `Agent._complete`
is monkeypatched to return scripted JSON envelopes (same pattern as tests.py).
"""
import json

import pytest
from django.core.cache import cache

from assistant.agent import Agent
from assistant.models import AssistantConversation, AssistantMessage


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _script(monkeypatch, *responses):
    """Make the agent's LLM return the given strings in order."""
    it = iter(responses)
    monkeypatch.setattr('assistant.agent._build_llm', lambda: object())
    monkeypatch.setattr('assistant.agent.Agent._complete', lambda self, messages: next(it))


def _capture(monkeypatch, response):
    """Stub the LLM but record the message list it was handed (for asserting
    what history actually reaches the model)."""
    captured = {}
    monkeypatch.setattr('assistant.agent._build_llm', lambda: object())

    def fake_complete(self, messages):
        captured['messages'] = messages
        return response

    monkeypatch.setattr('assistant.agent.Agent._complete', fake_complete)
    return captured


def _env(*, tool=None, args=None, final_reply=None, proposed_action=None, title=None):
    payload = {
        'thought': 't', 'tool': tool, 'args': args or {},
        'final_reply': final_reply, 'proposed_action': proposed_action,
    }
    if title is not None:
        payload['title'] = title
    return json.dumps(payload)


CHAT_URL = '/api/assistant/chat/'
LIST_URL = '/api/assistant/conversations/'
ADMIN_LIST_URL = '/api/assistant/conversations/admin/'


# ==================== Thread title auto-generation ==================== #

@pytest.mark.django_db
class TestThreadTitle:
    def test_title_set_on_first_turn(self, authenticated_client, monkeypatch):
        _script(monkeypatch, _env(final_reply='Sure!', title='Haldi powder order'))
        resp = authenticated_client.post(CHAT_URL, {'message': 'I want haldi'}, format='json')
        assert resp.status_code == 200
        conv = AssistantConversation.objects.get(conversation_id=resp.data['conversation_id'])
        assert conv.title == 'Haldi powder order'

    def test_title_omitted_leaves_blank(self, authenticated_client, monkeypatch):
        _script(monkeypatch, _env(final_reply='Hello there'))  # no title key
        resp = authenticated_client.post(CHAT_URL, {'message': 'hi'}, format='json')
        conv = AssistantConversation.objects.get(conversation_id=resp.data['conversation_id'])
        assert conv.title == ''

    def test_title_not_overwritten_on_later_turns(self, authenticated_client, monkeypatch):
        _script(
            monkeypatch,
            _env(final_reply='First', title='Original title'),
            _env(final_reply='Second', title='A different title'),
        )
        r1 = authenticated_client.post(CHAT_URL, {'message': 'one'}, format='json')
        cid = r1.data['conversation_id']
        authenticated_client.post(
            CHAT_URL, {'message': 'two', 'conversation_id': cid}, format='json'
        )
        conv = AssistantConversation.objects.get(conversation_id=cid)
        assert conv.title == 'Original title'

    def test_title_html_is_stripped(self, authenticated_client, monkeypatch):
        _script(monkeypatch, _env(final_reply='ok', title='<b>Spice</b> order'))
        resp = authenticated_client.post(CHAT_URL, {'message': 'hi'}, format='json')
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
