"""AP7c (S5-rest, S8): one in-flight turn, tighter throttles, smaller history."""
import json

import pytest
from django.conf import settings
from django.core.cache import cache

from assistant.agent import MODEL_CONTEXT_TOKENS, Agent


def _env(final_reply='ok'):
    return {'content': final_reply, 'tool_calls': [], 'finish': 'stop'}


def _stub_llm(monkeypatch, reply='ok'):
    monkeypatch.setattr('assistant.agent._build_llm', lambda: object())
    monkeypatch.setattr('assistant.agent.Agent._complete',
                        lambda self, messages: _env(final_reply=reply))


@pytest.mark.django_db
class TestInflightGuard:
    def test_second_concurrent_turn_is_429(self, authenticated_client, test_user):
        cache.set(f'ngu:chat:inflight:{test_user.pk}', 1, timeout=60)
        r = authenticated_client.post('/api/assistant/chat/', {'message': 'hi'}, format='json')
        assert r.status_code == 429
        assert 'already in progress' in r.data['detail']

    def test_finished_turn_releases_guard(self, authenticated_client, test_user, monkeypatch):
        _stub_llm(monkeypatch)
        r = authenticated_client.post('/api/assistant/chat/', {'message': 'hi'}, format='json')
        assert r.status_code == 200
        assert cache.get(f'ngu:chat:inflight:{test_user.pk}') is None


@pytest.mark.django_db
class TestHistoryBudget:
    def test_long_thread_trims_oldest_keeps_newest(self, monkeypatch):
        _stub_llm(monkeypatch)
        captured = {}
        orig_complete = Agent._complete

        def spy(self, messages):
            captured['messages'] = list(messages)
            return orig_complete(self, messages)

        monkeypatch.setattr('assistant.agent.Agent._complete', spy)
        history = [{'role': 'user', 'content': f'msg-{i}-' + 'x' * 490} for i in range(200)]
        out = Agent(None).run('new question', history=history)
        assert out['history_truncated'] is True
        assert out['reply'] == 'ok'
        sent = captured['messages']
        assert sent[-1] == ('user', 'new question')
        # Newest history turn survived the trim (oldest were dropped instead).
        assert any(m == ('user', history[-1]['content']) for m in sent)


class TestThrottleBudget:
    def test_assistant_burst_is_10_per_min(self):
        assert settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['assistant'] == '10/min'

    def test_assistant_daily_cap_is_100(self):
        assert settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['assistant_day'] == '100/day'

    def test_history_budget_is_small(self):
        assert MODEL_CONTEXT_TOKENS == 12000


@pytest.mark.django_db
class TestOrdinaryThreadIsRemembered:
    def test_a_dozen_exchanges_fit_at_default_settings(self, monkeypatch):
        """The budget is a cost guard for runaway threads, not for normal ones:
        an everyday conversation must reach the model whole, with no
        "start a new chat" notice."""
        import assistant.agent as agent_mod
        # Pin the shipped defaults: a developer .env may override them.
        monkeypatch.setattr(agent_mod, 'MODEL_CONTEXT_TOKENS', 12000)
        monkeypatch.setattr(agent_mod, 'MAX_OUTPUT_TOKENS', 1000)
        monkeypatch.setattr(agent_mod, 'TOOL_OBS_RESERVE_TOKENS', 4000)
        _stub_llm(monkeypatch)
        captured = {}
        orig_complete = Agent._complete

        def spy(self, messages):
            captured['messages'] = list(messages)
            return orig_complete(self, messages)

        monkeypatch.setattr('assistant.agent.Agent._complete', spy)
        history = []
        for i in range(12):
            history.append({'role': 'user',
                            'content': f'q{i} haldi 500g aur jeera 100g chahiye, kitna hoga?'})
            history.append({'role': 'assistant', 'content': f'a{i} ' + 'x' * 450})
        out = Agent(None).run('aur dhaniya bhi', history=history)
        assert out['history_truncated'] is False
        assert len(captured['messages']) == 1 + len(history) + 1   # system + thread + new


@pytest.mark.django_db
class TestRefusedTurnLeavesNothingBehind:
    def test_busy_429_does_not_save_the_message(self, authenticated_client, test_user):
        from assistant.models import AssistantConversation, AssistantMessage
        cache.add(f'ngu:chat:inflight:{test_user.pk}', 1, 60)
        try:
            r = authenticated_client.post('/api/assistant/chat/', {'message': 'hello'},
                                          format='json')
        finally:
            cache.delete(f'ngu:chat:inflight:{test_user.pk}')
        assert r.status_code == 429
        assert AssistantMessage.objects.count() == 0
        assert AssistantConversation.objects.count() == 0
