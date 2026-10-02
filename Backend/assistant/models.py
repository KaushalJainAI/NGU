import uuid
from datetime import timedelta

from django.db import models
from django.conf import settings
from django.utils import timezone

from decouple import config

# How long the AI stays silent after a team member's last message in a thread.
# The pause is sticky (an admin releases it explicitly), but this is the safety
# net: without it, an admin who replies at 11pm and goes to bed leaves the
# customer with NOBODY answering — worse than the AI talking over a human.
# Every admin reply restarts the clock. 0 disables the auto-release entirely.
HANDOFF_IDLE_HOURS = config('ASSISTANT_HANDOFF_IDLE_HOURS', default=12, cast=int)


class AssistantConversation(models.Model):
    """A single chat thread. One user can have many threads and switch between them.

    Scoped to a user when authenticated, otherwise to an anonymous browser
    session id. A conversation can never be loaded by a different user (G1).

    Three participant types exist within a thread:
    - user    → customer (typed or voice-transcribed)
    - assistant → Nidhi AI
    - admin   → team member who replied directly into the thread
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('resolved', 'Resolved'),
        ('archived', 'Archived'),
    ]

    conversation_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assistant_conversations',
    )
    # For anonymous users we bind the thread to an opaque client-generated id.
    anon_session = models.CharField(max_length=64, blank=True, default='', db_index=True)

    # Auto-set from the LLM on the first turn; shown in the thread list.
    title = models.CharField(max_length=80, blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    # True when the AI escalates or an admin flags the thread for attention.
    # Highlighted in the admin dashboard.
    needs_human = models.BooleanField(default=False)

    # Admin who owns / is handling this thread.
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_conversations',
    )

    # Set to now() on every admin reply. While the pause is live the AI does not
    # answer this thread at all (the chat view short-circuits before the LLM
    # call, so a handed-off thread also costs no tokens). Cleared when an admin
    # hands the thread back or resolves it.
    ai_paused_at = models.DateTimeField(null=True, blank=True)
    ai_paused_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paused_conversations',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Assistant Conversation'
        verbose_name_plural = 'Assistant Conversations'

    @property
    def is_ai_paused(self):
        """True while a human is handling this thread and the AI must stay quiet.

        Computed, never stored as a bool: the auto-release must take effect on
        read, without a scheduler tick, so a stale row can't strand a customer."""
        if self.ai_paused_at is None:
            return False
        if HANDOFF_IDLE_HOURS <= 0:
            return True          # auto-release disabled — sticky until released
        return timezone.now() - self.ai_paused_at < timedelta(hours=HANDOFF_IDLE_HOURS)

    def pause_ai(self, admin_user=None):
        """An admin spoke — silence the AI and restart the idle clock."""
        self.ai_paused_at = timezone.now()
        self.ai_paused_by = admin_user
        return ['ai_paused_at', 'ai_paused_by']

    def resume_ai(self):
        """Hand the thread back to the AI."""
        self.ai_paused_at = None
        self.ai_paused_by = None
        return ['ai_paused_at', 'ai_paused_by']

    def __str__(self):
        who = self.user.email if self.user else (self.anon_session or 'guest')
        label = self.title or str(self.conversation_id)
        return f'AssistantConversation "{label}" ({who})'


class AssistantMessage(models.Model):
    """One turn in a conversation.

    `role` can be user | assistant | tool | system | admin.
    Admin messages are written directly by team members and are visible to both
    the customer and the LLM (included in history so the AI can acknowledge
    the handoff and defer cart actions).

    `meta` holds the full audit record for abuse review (G6).
    """
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('tool', 'Tool'),
        ('system', 'System'),
        ('admin', 'Admin'),
    ]

    conversation = models.ForeignKey(
        AssistantConversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    role = models.CharField(max_length=12, choices=ROLE_CHOICES)
    content = models.TextField(blank=True, default='')
    # Set for admin role (e.g. "Kaushal"); blank for AI / user turns.
    sender_name = models.CharField(max_length=100, blank=True, default='')
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Assistant Message'
        verbose_name_plural = 'Assistant Messages'

    def __str__(self):
        prefix = f"{self.role}" + (f" ({self.sender_name})" if self.sender_name else "")
        return f"{prefix}: {self.content[:50]}"
