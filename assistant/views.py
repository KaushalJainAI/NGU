"""Unified chat views.

Endpoints:
  POST /api/assistant/chat/                           — send a message (AI responds)
  GET  /api/assistant/conversations/                  — list user's own threads
  POST /api/assistant/conversations/                  — create a new empty thread
  GET  /api/assistant/conversations/<id>/messages/    — full message history

  GET  /api/assistant/conversations/admin/            — admin: list all threads
  POST /api/assistant/conversations/<id>/admin-reply/ — admin: reply into a thread
  PATCH /api/assistant/conversations/<id>/            — admin: update status / assigned_to

Trust boundary: the authenticated user is injected by the view — the model never
chooses whose data to read (G1).
"""

import logging

from django.conf import settings
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework import status

from . import stt
from .models import AssistantConversation, AssistantMessage
from .serializers import (
    AssistantChatRequestSerializer,
    ConversationSummarySerializer,
    MessageSerializer,
    AdminReplySerializer,
    ConversationPatchSerializer,
)
from .throttles import (
    AssistantBurstThrottle,
    AssistantDailyThrottle,
    AssistantTranscribeThrottle,
)
from .agent import Agent, MAX_HISTORY_MESSAGES

logger = logging.getLogger(__name__)

# Bound on how many conversations a single list response returns (admin + customer).
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


def _annotate_last_message(qs):
    """Annotate each conversation with its most recent visible message content,
    so serializing a list does not trigger an N+1 query (one subquery instead)."""
    last_msg = AssistantMessage.objects.filter(
        conversation=OuterRef('pk'),
        role__in=['user', 'assistant', 'admin'],
    ).order_by('-created_at', '-id').values('content')[:1]
    return qs.annotate(last_message_content=Subquery(last_msg))


def _paginate(qs, request):
    """Simple limit/offset slice returning a plain list (keeps the array response
    contract the frontends expect). Bounded so a huge table can't be dumped."""
    try:
        limit = int(request.query_params.get('limit', DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        limit = DEFAULT_PAGE_SIZE
    try:
        offset = int(request.query_params.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    offset = max(0, offset)
    return qs[offset:offset + limit]


# ---------------------------------------------------------------------------
# Chat endpoint (AI responds)
# ---------------------------------------------------------------------------

class AssistantChatView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AssistantBurstThrottle, AssistantDailyThrottle]

    def post(self, request):
        ser = AssistantChatRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        message = data['message'].strip()
        if not message:
            return Response({'error': 'Empty message'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user and request.user.is_authenticated else None
        anon_session = '' if user else (data.get('anon_session') or '')

        conversation = self._get_or_create_conversation(
            data.get('conversation_id'), user, anon_session
        )
        # Human handoff: a team member is on this thread, so the AI stays out of
        # it entirely. The customer's message is still persisted and the thread
        # is re-flagged for attention — silence must never mean a lost message.
        if conversation.is_ai_paused:
            admin = conversation.ai_paused_by
            handled_by = (admin.get_full_name() or admin.email) if admin else ''
            AssistantMessage.objects.create(
                conversation=conversation, role='user', content=message
            )
            fields = ['updated_at']
            if not conversation.needs_human:
                conversation.needs_human = True
                fields.append('needs_human')
            conversation.save(update_fields=fields)
            return Response({
                'conversation_id': str(conversation.conversation_id),
                'reply': '',
                'proposed_action': None,
                'sources': [],
                'history_truncated': False,
                'ai_paused': True,
                'handled_by': handled_by,
            })

        is_first_turn = not conversation.messages.filter(role='assistant').exists()

        history = self._load_history(conversation)

        AssistantMessage.objects.create(
            conversation=conversation, role='user', content=message
        )

        # AP7c/S5: one in-flight turn per account. A multi-call turn occupies a
        # gunicorn slot for seconds; parallel turns from one account multiply
        # that (and the LLM bill). cache.add is set-if-absent: losers get 429.
        # The 60 s TTL is a dead-man's release if the worker dies mid-turn.
        from django.core.cache import cache
        inflight_key = f'ngu:chat:inflight:{user.pk}' if user else None
        if inflight_key is not None and not cache.add(inflight_key, 1, timeout=60):
            return Response({'detail': 'A reply is already in progress.'},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        try:
            completion = getattr(request, '_assistant_completion', None)
            agent = Agent(user, completion=completion)
            result = agent.run(message, history=history, language=data.get('language') or '')

            proposed_action = result.get('proposed_action')

            # Escalation: flag thread for human attention (no ChatSession created).
            # AP2: an LLM provider failure (reason llm_error) is never an escalation
            # even if a future caller sets escalate alongside it — the friendly
            # fallback is still persisted below so history shows it.
            if result.get('escalate') and result.get('reason') != 'llm_error' and not conversation.needs_human:
                conversation.needs_human = True
                conversation.save(update_fields=['needs_human', 'updated_at'])

            # Auto-set thread title from the LLM on the first turn.
            if is_first_turn and result.get('title') and not conversation.title:
                conversation.title = result['title']
                conversation.save(update_fields=['title', 'updated_at'])
            else:
                conversation.save(update_fields=['updated_at'])

            AssistantMessage.objects.create(
                conversation=conversation,
                role='assistant',
                content=result.get('reply', ''),
                meta={
                    'sources': result.get('sources', []),
                    'proposed_action': proposed_action,
                    'escalate': bool(result.get('escalate')),
                    'llm_used': result.get('llm_used'),
                    'reason': result.get('reason', 'ok'),
                },
            )

            return Response({
                'conversation_id': str(conversation.conversation_id),
                'reply': result.get('reply', ''),
                'proposed_action': proposed_action,
                'sources': result.get('sources', []),
                # True once the thread no longer fits the model's context window and
                # its oldest turns were dropped from the prompt. The client shows a
                # "start a new chat" notice — the assistant is now answering without
                # the earliest part of this conversation.
                'history_truncated': bool(result.get('history_truncated')),
                'ai_paused': False,
                'handled_by': '',
            })
        finally:
            if inflight_key is not None:
                cache.delete(inflight_key)

    # ------------------------------------------------------------------
    def _get_or_create_conversation(self, conversation_id, user, anon_session):
        """G1: a conversation can only be resumed by its own owner."""
        if conversation_id:
            qs = AssistantConversation.objects.filter(conversation_id=conversation_id)
            if user:
                qs = qs.filter(user=user)
            else:
                qs = qs.filter(user__isnull=True, anon_session=anon_session) \
                    if anon_session else qs.none()
            existing = qs.first()
            if existing:
                return existing
        return AssistantConversation.objects.create(user=user, anon_session=anon_session)

    def _load_history(self, conversation):
        # Load the most recent messages (bounded to avoid an unbounded queryset
        # on a runaway thread); the agent then token-trims to the context budget.
        msgs = conversation.messages.filter(role__in=['user', 'assistant', 'admin']) \
            .order_by('-created_at', '-id')[:MAX_HISTORY_MESSAGES]
        return [
            {'role': m.role, 'content': m.content, 'sender_name': m.sender_name}
            for m in reversed(list(msgs))
        ]


# ---------------------------------------------------------------------------
# Admin assistant chat (store-manager Q&A over business data)
# ---------------------------------------------------------------------------

class AdminAssistantChatView(APIView):
    """Plain-English Q&A over the store's own data for staff.

    Stateless by design: the admin panel holds the short conversation in the
    browser and posts the recent history each turn, so these admin chats never
    land in the customer support inbox (AssistantConversation) and no migration
    is needed. The agent runs with persona='admin' — read-only reporting tools
    that read across all customers/orders. Gated by IsAdminUser AND the persona,
    so a customer path can never reach these tools.
    """
    permission_classes = [IsAdminUser]
    throttle_classes = [AssistantBurstThrottle, AssistantDailyThrottle]

    MAX_HISTORY = 20  # recent turns the client may send back

    def post(self, request):
        message = (request.data.get('message') or '').strip()
        if not message:
            return Response({'error': 'Empty message'}, status=status.HTTP_400_BAD_REQUEST)

        # Sanitise the client-provided history to the small shape the agent wants.
        raw_history = request.data.get('history') or []
        history = []
        if isinstance(raw_history, list):
            for h in raw_history[-self.MAX_HISTORY:]:
                if not isinstance(h, dict):
                    continue
                role = h.get('role')
                content = h.get('content')
                if role in ('user', 'assistant') and isinstance(content, str):
                    history.append({'role': role, 'content': content[:2000]})

        completion = getattr(request, '_assistant_completion', None)
        agent = Agent(request.user, completion=completion, persona='admin')
        result = agent.run(message, history=history, language='en')

        return Response({
            'reply': result.get('reply', ''),
            'sources': result.get('sources', []),
            'history_truncated': bool(result.get('history_truncated')),
        })


# ---------------------------------------------------------------------------
# Voice transcription (self-hosted whisper.cpp)
# ---------------------------------------------------------------------------

class AssistantTranscribeView(APIView):
    """Speech-to-text for voice chat input.

    Accepts an audio blob (multipart field ``audio``), runs it through the
    configured STT backend (``STT_PROVIDER`` — Voxtral over OpenRouter, or the
    self-hosted whisper.cpp container), and returns the transcript. The frontend
    then sends that transcript to /chat/ exactly like typed text — this endpoint
    never touches the LLM and persists nothing. Login-only, like the rest of the
    assistant (G1)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [AssistantTranscribeThrottle, AssistantDailyThrottle]

    # Voice orders are short; cap upload size so a bad client can't hand the STT
    # backend a huge file (a metered one, on Voxtral — audio is billed per minute).
    # 16 kHz mono WAV is ~32 KB/s, so this is minutes.
    MAX_AUDIO_BYTES = 8 * 1024 * 1024

    def post(self, request):
        if not settings.USE_SELF_HOSTED_STT:
            return Response(
                {'error': 'Voice transcription is not enabled.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        audio = request.FILES.get('audio')
        if not audio:
            return Response({'error': 'No audio provided.'}, status=status.HTTP_400_BAD_REQUEST)
        if audio.size and audio.size > self.MAX_AUDIO_BYTES:
            return Response(
                {'error': 'Audio too large.'},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        language = (request.data.get('language') or '').strip()
        try:
            result = stt.transcribe(
                audio.read(), audio.name, audio.content_type, language,
            )
        except stt.TranscriptionUnavailable:
            return Response(
                {'error': 'Transcription service is temporarily unavailable.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(result)


# ---------------------------------------------------------------------------
# Customer: list threads / create thread / get messages
# ---------------------------------------------------------------------------

class ConversationListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        convos = AssistantConversation.objects.filter(user=request.user) \
            .order_by('-updated_at')
        convos = _paginate(_annotate_last_message(convos), request)
        ser = ConversationSummarySerializer(convos, many=True)
        return Response(ser.data)

    def post(self, request):
        convo = AssistantConversation.objects.create(user=request.user)
        return Response(
            ConversationSummarySerializer(convo).data,
            status=status.HTTP_201_CREATED,
        )


class ConversationMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id):
        # Admins can read any thread; customers only their own.
        if request.user.is_staff:
            convo = get_object_or_404(AssistantConversation, conversation_id=conversation_id)
        else:
            convo = get_object_or_404(
                AssistantConversation, conversation_id=conversation_id, user=request.user
            )
        msgs = convo.messages.exclude(role__in=['tool', 'system']).order_by('created_at', 'id')
        return Response(MessageSerializer(msgs, many=True).data)


# ---------------------------------------------------------------------------
# Admin: list all threads / reply / patch status
# ---------------------------------------------------------------------------

class AdminConversationListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = AssistantConversation.objects.select_related('user', 'assigned_to') \
            .order_by('-updated_at')

        if request.query_params.get('needs_human') == 'true':
            qs = qs.filter(needs_human=True)
        if request.query_params.get('status'):
            qs = qs.filter(status=request.query_params['status'])
        if request.query_params.get('user_id'):
            qs = qs.filter(user_id=request.query_params['user_id'])

        qs = _paginate(_annotate_last_message(qs), request)
        ser = ConversationSummarySerializer(qs, many=True)
        return Response(ser.data)


class AdminConversationReplyView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, conversation_id):
        convo = get_object_or_404(AssistantConversation, conversation_id=conversation_id)
        ser = AdminReplySerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        sender_name = (
            request.user.get_full_name() or request.user.email or 'Admin'
        )
        AssistantMessage.objects.create(
            conversation=convo,
            role='admin',
            content=ser.validated_data['message'],
            sender_name=sender_name,
        )
        # An admin speaking silences the AI on this thread and (re)starts the
        # idle clock, so the two can't answer the same customer at once.
        fields = convo.pause_ai(request.user) + ['updated_at']
        # The admin has just answered, so nothing is waiting on a human right
        # now. A later customer message re-raises the flag (see AssistantChatView).
        if convo.needs_human:
            convo.needs_human = False
            fields.append('needs_human')
        convo.save(update_fields=fields)

        return Response({'status': 'sent', 'ai_paused': convo.is_ai_paused})


class AdminConversationPatchView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request, conversation_id):
        convo = get_object_or_404(AssistantConversation, conversation_id=conversation_id)
        ser = ConversationPatchSerializer(convo, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()

        # Hand the thread back to the AI — either explicitly (`ai_paused: false`)
        # or implicitly by resolving/archiving it, which ends the human's turn.
        wants_resume = request.data.get('ai_paused') is False
        closed = ser.validated_data.get('status') in ('resolved', 'archived')
        if (wants_resume or closed) and convo.ai_paused_at is not None:
            convo.save(update_fields=convo.resume_ai() + ['updated_at'])

        return Response(ConversationSummarySerializer(convo).data)
