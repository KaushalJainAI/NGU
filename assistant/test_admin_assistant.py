"""Tests for the admin (store-manager) assistant persona.

Same LLM-stubbing pattern as test_unified_chat.py: the model is scripted to
return JSON envelopes so we exercise the agent loop + admin tools deterministically.
"""
import json

import pytest
from django.core.cache import cache

from assistant.agent import Agent


ADMIN_CHAT_URL = '/api/assistant/admin-chat/'


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _script(monkeypatch, *responses):
    it = iter(responses)
    monkeypatch.setattr('assistant.agent._build_llm', lambda: object())
    monkeypatch.setattr('assistant.agent.Agent._complete', lambda self, messages: next(it))


def _env(*, tool=None, args=None, final_reply=None):
    return json.dumps({'thought': 't', 'tool': tool, 'args': args or {},
                       'final_reply': final_reply})


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
        """Even if the model emits a proposed_action, the admin persona drops it
        (read-only): no add_to_cart/checkout ever comes back."""
        raw = json.dumps({
            'thought': 't', 'tool': None, 'args': {},
            'final_reply': 'Here you go.',
            'proposed_action': {'tool': 'add_to_cart', 'args': {'product_id': 1}},
        })
        _script(monkeypatch, raw)
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
