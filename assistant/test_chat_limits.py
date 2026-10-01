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
