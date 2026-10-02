from rest_framework import serializers

from .agent import MAX_MESSAGE_LEN
from .models import AssistantConversation, AssistantMessage


class AssistantChatRequestSerializer(serializers.Serializer):
    # AP10: chat is login-only — the anonymous-session arg is gone (the model
    # column stays as a vestigial field; no code path reads it anymore).
    message = serializers.CharField(max_length=MAX_MESSAGE_LEN, trim_whitespace=True)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    language = serializers.CharField(max_length=16, required=False, allow_blank=True)


class ConversationSummarySerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    # True while a team member is handling the thread and the AI is staying out
    # of it. Computed (see AssistantConversation.is_ai_paused) so the idle
    # auto-release is reflected on read without a scheduler tick.
    ai_paused = serializers.BooleanField(source='is_ai_paused', read_only=True)
    ai_paused_by = serializers.SerializerMethodField()

    class Meta:
        model = AssistantConversation
        fields = [
            'conversation_id', 'title', 'status', 'needs_human',
            'last_message', 'user_email', 'updated_at', 'created_at',
            'ai_paused', 'ai_paused_by',
        ]
        read_only_fields = fields

    def get_ai_paused_by(self, obj):
        admin = obj.ai_paused_by
        if not admin:
            return ''
        return admin.get_full_name() or admin.email

    def get_last_message(self, obj):
        # Prefer the value annotated on the queryset (avoids an N+1 when the
        # view annotates `last_message_content`); fall back to a query for
        # single-object serialization (create / patch responses).
        annotated = getattr(obj, 'last_message_content', False)
        if annotated is not False:
            return (annotated or '')[:120]
        msg = obj.messages.filter(role__in=['user', 'assistant', 'admin']) \
            .order_by('-created_at', '-id').first()
        return msg.content[:120] if msg else ''

    def get_user_email(self, obj):
        return obj.user.email if obj.user else None


class MessageSerializer(serializers.ModelSerializer):
    # AP10: the saved proposal travels WITH history so action buttons survive
    # reload (the widget disables them again client-side once tapped — one tap
    # can no longer repeat). Nothing else from the audit meta is exposed.
    proposed_action = serializers.SerializerMethodField()

    class Meta:
        model = AssistantMessage
        fields = ['id', 'role', 'content', 'sender_name', 'created_at', 'proposed_action']
        read_only_fields = fields

    def get_proposed_action(self, obj):
        action = (obj.meta or {}).get('proposed_action')
        return action if isinstance(action, dict) else None


class AdminReplySerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000, trim_whitespace=True)


class ConversationPatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssistantConversation
        fields = ['status', 'assigned_to', 'needs_human', 'title']
