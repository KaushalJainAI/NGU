from rest_framework import serializers
from .models import ContactSubmission


class ContactSubmissionSerializer(serializers.ModelSerializer):
    """Serializer for creating and listing contact submissions"""
    
    class Meta:
        model = ContactSubmission
        fields = [
            'id', 'name', 'email', 'phone', 'subject', 'message',
            'status', 'created_at'
        ]
        read_only_fields = ['id', 'status', 'created_at']


class ContactSubmissionAdminSerializer(serializers.ModelSerializer):
    """Admin serializer with all fields including admin notes"""
    user_email = serializers.EmailField(source='user.email', read_only=True)
    
    class Meta:
        model = ContactSubmission
        fields = [
            'id', 'name', 'email', 'phone', 'subject', 'message',
            'status', 'user', 'user_email', 'admin_notes', 'replied_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

