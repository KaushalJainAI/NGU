"""AP2: LLM provider failure is a friendly reply, never a 500/escalation (A2)."""
import json

import pytest

from assistant.agent import Agent, FALLBACK_REPLY, LLM_REQUEST_TIMEOUT, LLM_MAX_RETRIES
from assistant.models import AssistantConversation
from assistant.prompts import FALLBACK_REPLY as PROMPT_FALLBACK


def _env(**kw):
    base = {'thought': 't', 'tool': None, 'args': {}, 'final_reply': None,
            'proposed_action': None}
    base.update(kw)
    return json.dumps(base)


@pytest.mark.django_db
class TestLLMFailure:
    def test_timeout_returns_friendly_no_escalation(self, monkeypatch):
        monkeypatch.setattr('assistant.agent._build_llm', lambda: object())

        def boom(self, messages):
            raise TimeoutError('provider slow')
        monkeypatch.setattr('assistant.agent.Agent._complete', boom)
        out = Agent(None).run('hi')
        assert out['reply'] == FALLBACK_REPLY == PROMPT_FALLBACK
        assert out['escalate'] is False
        assert out['reason'] == 'llm_error'
        assert out['llm_used'] is True

    def test_garbage_twice_still_escalates(self, monkeypatch):
        # AP2 keeps the bad-JSON path unchanged (AP9 reworks it).
        monkeypatch.setattr('assistant.agent._build_llm', lambda: object())
        it = iter(['not json', 'still not json'])
        monkeypatch.setattr('assistant.agent.Agent._complete',
                            lambda self, messages: next(it))
        out = Agent(None).run('hi')
        assert out['escalate'] is True
        assert out['reason'] == 'loop_exhausted'

    def test_endpoint_does_not_flag_human_on_llm_error(self, authenticated_client, monkeypatch):
        monkeypatch.setattr('assistant.agent._build_llm', lambda: object())

        def boom(self, messages):
            raise TimeoutError('down')
        monkeypatch.setattr('assistant.agent.Agent._complete', boom)
        resp = authenticated_client.post('/api/assistant/chat/', {'message': 'hi'}, format='json')
        assert resp.status_code == 200
        assert resp.data['reply'] == FALLBACK_REPLY
        conv = AssistantConversation.objects.get(conversation_id=resp.data['conversation_id'])
        assert conv.needs_human is False

    def test_llm_timeout_and_retry_budget(self):
        assert LLM_REQUEST_TIMEOUT == 20
        assert LLM_MAX_RETRIES <= 1
