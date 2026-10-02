"""
Comprehensive tests for the Support app.
Covers contact form submissions, chat sessions, and admin operations.
"""
import pytest
from rest_framework import status


# ==================== CONTACT SUBMISSION TESTS ====================

@pytest.mark.django_db
class TestContactSubmission:
    """Tests for contact form submissions."""
    
    base_url = '/api/contact/'
    
    def test_submit_contact_form_public(self, api_client):
        """Test anyone can submit a contact form."""
        data = {
            'name': 'Test User',
            'email': 'contact@example.com',
            'phone': '1234567890',
            'subject': 'Test Subject',
            'message': 'This is a test message.'
        }
        response = api_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
    
    def test_submit_contact_form_authenticated(self, authenticated_client):
        """Test authenticated user can submit contact form."""
        data = {
            'name': 'Auth User',
            'email': 'auth@example.com',
            'subject': 'Auth Subject',
            'message': 'Authenticated message.'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
    
    def test_submit_contact_missing_fields(self, api_client):
        """Test contact submission with missing fields fails."""
        data = {
            'name': 'Test User'
            # Missing email, subject, message
        }
        response = api_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_submit_contact_invalid_email(self, api_client):
        """Test contact submission with invalid email fails."""
        data = {
            'name': 'Test User',
            'email': 'not-an-email',
            'subject': 'Test',
            'message': 'Test message'
        }
        response = api_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_list_contacts_admin_only(self, admin_client):
        """Test only admin can list contact submissions."""
        response = admin_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_list_contacts_regular_user_forbidden(self, authenticated_client):
        """Test regular user cannot list contact submissions."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_list_contacts_unauthenticated_forbidden(self, api_client):
        """Test unauthenticated user cannot list contacts."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ==================== CONTACT SUBMISSION SECURITY TESTS ====================

@pytest.mark.django_db
class TestContactSubmissionSecurity:
    """Security tests for contact submissions."""
    
    base_url = '/api/contact/'
    
    def test_xss_in_message(self, api_client, malicious_inputs):
        """Test XSS payloads in contact message."""
        for payload in malicious_inputs.XSS_PAYLOADS:
            data = {
                'name': 'Test User',
                'email': 'test@example.com',
                'subject': 'XSS Test',
                'message': payload
            }
            response = api_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_sql_injection_in_fields(self, api_client, malicious_inputs):
        """Test SQL injection in contact fields."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'name': payload,
                'email': 'test@example.com',
                'subject': payload,
                'message': payload
            }
            response = api_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_oversized_message(self, api_client, malicious_inputs):
        """Test contact with oversized message."""
        data = {
            'name': 'Test User',
            'email': 'test@example.com',
            'subject': 'Oversized Test',
            'message': malicious_inputs.OVERSIZED_STRING
        }
        response = api_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
