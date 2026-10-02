from django.db import models
from django.conf import settings


# ---------------------------------------------------------------------------
# Retained ONLY because historical migrations (0001, 0003) reference these by
# dotted path for the now-deleted ChatMessage.attachment field. The order-scoped
# chat system has been removed (replaced by the unified assistant chat); these
# are dead at runtime and exist solely so old migrations stay importable.
# Safe to delete once the support migrations are squashed.
# ---------------------------------------------------------------------------
def get_chat_attachment_path(instance, filename):  # pragma: no cover
    import os
    import uuid
    ext = os.path.splitext(filename)[1]
    return f"chat_attachments/{uuid.uuid4()}{ext}"


def validate_chat_attachment(value):  # pragma: no cover
    return value


class ContactSubmission(models.Model):
    """Contact form submissions from the Contact Us page"""
    STATUS_CHOICES = [
        ('new', 'New'),
        ('read', 'Read'),
        ('replied', 'Replied'),
        ('closed', 'Closed'),
    ]
    
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, default='')
    subject = models.CharField(max_length=200)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    
    # Optional: link to user if logged in
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='contact_submissions'
    )
    
    # Admin response
    admin_notes = models.TextField(blank=True, default='')
    replied_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Contact Submission'
        verbose_name_plural = 'Contact Submissions'

    def __str__(self):
        return f"{self.name} - {self.subject[:30]}"
