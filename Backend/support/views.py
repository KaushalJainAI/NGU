from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.throttling import AnonRateThrottle
from django.utils import timezone

from admin_panel.recycle import RecycleBinDestroyMixin
from .models import ContactSubmission
from .serializers import (
    ContactSubmissionSerializer,
    ContactSubmissionAdminSerializer,
)


# ==================== CUSTOM THROTTLES ====================

class ContactRateThrottle(AnonRateThrottle):
    """Throttle for contact form - prevents spam submissions"""
    scope = 'contact'


class ContactSubmissionViewSet(RecycleBinDestroyMixin, viewsets.ModelViewSet):
    """
    ViewSet for contact form submissions.
    - Anyone can POST (submit a contact form) - rate limited to 5/hour
    - Only admins can GET/PUT/DELETE (DELETE moves it to the Recycle Bin)
    """
    recycle_kind = 'contact_submission'

    def recycle_label(self, instance):
        return f"{instance.name} — {instance.subject}"

    throttle_classes = [ContactRateThrottle]
    # Admin inbox has no pagination UI, so return every submission — otherwise
    # the 13th+ customer message is invisible (hidden by global PAGE_SIZE).
    pagination_class = None

    def get_permissions(self):
        if self.action == 'create':
            return []
        from rest_framework.permissions import IsAdminUser
        return [IsAdminUser()]
    
    def get_queryset(self):
        return ContactSubmission.objects.all().select_related('user')
    
    def get_serializer_class(self):
        if self.request.user and self.request.user.is_staff:
            return ContactSubmissionAdminSerializer
        return ContactSubmissionSerializer
    
    def perform_create(self, serializer):
        # Link to user if authenticated
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(user=user)
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """Mark a submission as read"""
        submission = self.get_object()
        submission.status = 'read'
        submission.save(update_fields=['status', 'updated_at'])
        return Response({'status': 'marked as read'})
    
    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        """Mark as replied with admin notes"""
        submission = self.get_object()
        submission.status = 'replied'
        from django.utils.html import escape, strip_tags
        notes = request.data.get('notes', '')
        submission.admin_notes = escape(strip_tags(notes)) if notes else ''
        submission.replied_at = timezone.now()
        submission.save(update_fields=['status', 'admin_notes', 'replied_at', 'updated_at'])
        return Response({'status': 'marked as replied'})
