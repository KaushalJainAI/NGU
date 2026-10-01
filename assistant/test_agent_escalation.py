"""AP9 (A3/A4/A5): native calls, honest escalation, truncation handling."""
import time
from decimal import Decimal

import pytest
from django.core import mail
from django.test import override_settings

from assistant.agent import Agent
from assistant.models import AssistantConversation
from assistant.prompts import CONTINUED_SUFFIX


def _turn(content=None, calls=(), finish='stop'):
    return {'content': content,
            'tool_calls': [{'name': n, 'args': a} for n, a in calls],
            'finish': finish}


def _script(monkeypatch, *responses):
    it = iter(responses)
    monkeypatch.setattr('assistant.agent._build_llm', lambda: object())
    monkeypatch.setattr('assistant.agent.Agent._complete', lambda self, messages: next(it))


def _product(db, test_category, name):
    from products.models import Product
    from conftest import create_test_image
    return Product.objects.create(
        name=name, category=test_category, description=f'{name} description',
        price=Decimal('100.00'), stock=10,
        weight=Decimal('100.00'), unit='g', spice_form='powder', is_active=True,
        image=create_test_image(f'{name[:4]}.jpg'),
    )


@pytest.mark.django_db
class TestMultiItemOneTurn:
    def test_three_lookups_in_one_turn(self, monkeypatch, test_category, db):
        _product(db, test_category, 'Haldi Powder')
        _product(db, test_category, 'Jeera Whole')
        _product(db, test_category, 'Dhaniya Powder')
        _script(
            monkeypatch,
            _turn(calls=[('search_products', {'query': 'haldi'}),
                          ('search_products', {'query': 'jeera'}),
                          ('search_products', {'query': 'dhaniya'})]),
            _turn(content='Found all three — tell me quantities.'),
        )
        out = Agent(None).run('haldi, jeera, dhaniya')
        assert [s['tool'] for s in out['sources']] == ['search_products'] * 3
        assert out['escalate'] is False
        assert out['reason'] == 'ok'


@pytest.mark.django_db
class TestLoopExhaustion:
    def test_exhaustion_is_capacity_not_human(self, authenticated_client, monkeypatch):
        blanks = [_turn() for _ in range(6)]
        _script(monkeypatch, *blanks)
        resp = authenticated_client.post('/api/assistant/chat/', {'message': 'hi'}, format='json')
        assert resp.status_code == 200
        conv = AssistantConversation.objects.get(conversation_id=resp.data['conversation_id'])
        assert conv.needs_human is False
        assert 'fewer' in resp.data['reply'].lower()


@pytest.mark.django_db
class TestCustomerAskedHandoff:
    @override_settings(ADMIN_ALERT_EMAIL='owner@test.com',
                       EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_escalation_flags_and_notifies_once(self, authenticated_client, monkeypatch):
        from django.core import mail as djmail
        djmail.outbox = []
        _script(monkeypatch, _turn(
            content='Connecting you now.',
            calls=[('escalate_to_human', {'reason': 'wants a person'})],
        ))
        resp = authenticated_client.post('/api/assistant/chat/', {'message': 'get me a human'},
                                         format='json')
        assert resp.status_code == 200
        conv = AssistantConversation.objects.get(conversation_id=resp.data['conversation_id'])
        assert conv.needs_human is True
        # The notify goes out on a background thread — wait for it, then
        # assert exactly one owner email naming this thread.
        deadline = time.time() + 10
        while not djmail.outbox and time.time() < deadline:
            time.sleep(0.1)
        assert len(djmail.outbox) == 1
        assert 'owner@test.com' in djmail.outbox[0].to
        assert str(conv.conversation_id) in djmail.outbox[0].body


@pytest.mark.django_db
class TestTruncation:
    def test_length_finish_appends_continuation(self, monkeypatch):
        _script(monkeypatch, _turn(content='Here is a very long list', finish='length'))
        out = Agent(None).run('list everything')
        assert out['escalate'] is False
        assert out['reason'] == 'ok'
        assert CONTINUED_SUFFIX in out['reply']
        assert out['reply'].startswith('Here is a very long list')
