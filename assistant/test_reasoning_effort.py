"""ASSISTANT_REASONING_EFFORT is passed to OpenRouter only when configured."""
from assistant import agent


def test_no_effort_configured_sends_no_reasoning_param(monkeypatch):
    monkeypatch.setattr(agent, 'REASONING_EFFORT', '')
    assert 'reasoning' not in agent._openrouter_body()


def test_effort_is_sent_alongside_the_provider_pin(monkeypatch):
    monkeypatch.setenv('OPENROUTER_PROVIDER_ORDER', 'DeepInfra')
    monkeypatch.setenv('OPENROUTER_ALLOW_FALLBACKS', 'True')
    monkeypatch.setattr(agent, 'REASONING_EFFORT', 'high')
    body = agent._openrouter_body()
    assert body['provider'] == {'order': ['DeepInfra'], 'allow_fallbacks': True}
    assert body['reasoning'] == {'effort': 'high'}


def test_built_model_carries_the_effort(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'sk-test')
    monkeypatch.setenv('ASSISTANT_MODEL_PROVIDER', 'openrouter')
    monkeypatch.setenv('ASSISTANT_LLM_MODEL', 'openai/gpt-6-luna')
    monkeypatch.setattr(agent, 'REASONING_EFFORT', 'high')
    llm = agent._build_llm()
    assert llm.model_name == 'openai/gpt-6-luna'
    assert llm.extra_body['reasoning'] == {'effort': 'high'}
