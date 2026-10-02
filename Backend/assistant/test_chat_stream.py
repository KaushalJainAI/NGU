"""AP10b: SSE stream delivery + saved actions returned with history."""
import json

import pytest

from assistant.models import AssistantConversation


def _turn(content=None, calls=(), finish='stop'):
    return {'content': content,
            'tool_calls': [{'name': n, 'args': a} for n, a in calls],
            'finish': finish}


def _script(monkeypatch, *responses):
    it = iter(responses)
    monkeypatch.setattr('assistant.agent._build_llm', lambda: object())
    monkeypatch.setattr('assistant.agent.Agent._complete', lambda self, messages: next(it))


def _events(response):
    body = b''.join(response.streaming_content).decode()
    out = []
    for block in body.strip().split('\n\n'):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith('event: '):
                event = line[len('event: '):]
            elif line.startswith('data: '):
                data = json.loads(line[len('data: '):])
        out.append((event, data))
    return out


@pytest.mark.django_db
class TestChatStream:
    def test_stream_delivers_meta_reply_done(self, authenticated_client, monkeypatch, test_product):
        _script(monkeypatch, _turn(
            content='Adding it now.',
            calls=[('add_to_cart', {'product_id': test_product.id, 'quantity': 1})],
        ))
        r = authenticated_client.post('/api/assistant/chat/stream/', {'message': 'add haldi'},
                                      format='json')
        assert r.status_code == 200
        assert r['Content-Type'] == 'text/event-stream'
        events = _events(r)
        assert events[0][0] == 'meta' and 'conversation_id' in events[0][1]
        assert events[-1][0] == 'done'
        done = events[-1][1]
        assert ''.join(e[1]['chunk'] for e in events if e[0] == 'reply') == done['reply']
        assert done['proposed_action']['type'] == 'add_to_cart'
        assert done['proposed_action']['product_id'] == test_product.id
        # Persisted exactly like the non-stream route.
        conv = AssistantConversation.objects.get(conversation_id=done['conversation_id'])
        assert conv.messages.filter(role='assistant').count() == 1

    def test_stream_paused_thread_closes(self, authenticated_client, test_admin,
                                         test_user, monkeypatch):
        # NOTE: admin_client and authenticated_client share one underlying
        # APIClient (credentials overwrite each other), so the admin gets a
        # client of its own here.
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken
        admin = APIClient()
        admin.credentials(
            HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(test_admin).access_token}')
        _script(monkeypatch, _turn(content='ok'))
        conv = AssistantConversation.objects.create(user=test_user)
        assert admin.post(
            f'/api/assistant/conversations/{conv.conversation_id}/admin-reply/',
            {'message': 'On it!'}, format='json').status_code == 200
        assert conv.__class__.objects.get(pk=conv.pk).is_ai_paused is True
        r = authenticated_client.post('/api/assistant/chat/stream/',
                                      {'message': 'hi there',
                                       'conversation_id': str(conv.conversation_id)},
                                      format='json')
        assert r.status_code == 200
        done = _events(r)[-1][1]
        assert done['ai_paused'] is True


@pytest.mark.django_db
class TestHistoryActions:
    def test_messages_return_saved_proposal(self, authenticated_client, monkeypatch, test_product):
        _script(monkeypatch, _turn(
            content='Added!',
            calls=[('add_to_cart', {'product_id': test_product.id, 'quantity': 2})],
        ))
        r = authenticated_client.post('/api/assistant/chat/', {'message': 'add it'}, format='json')
        cid = r.data['conversation_id']
        assert r.data['proposed_action']['quantity'] == 2
        msgs = authenticated_client.get(
            f'/api/assistant/conversations/{cid}/messages/').data
        assistant_msgs = [m for m in msgs if m['role'] == 'assistant']
        assert len(assistant_msgs) == 1
        # The saved action travels WITH history, so buttons survive reload.
        assert assistant_msgs[0]['proposed_action']['type'] == 'add_to_cart'
        assert assistant_msgs[0]['proposed_action']['quantity'] == 2
