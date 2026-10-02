"""
Comprehensive tests for the Payments app.
Covers payment method CRUD, default payment, and authorization tests.
"""
import pytest
from rest_framework import status
from payments.models import PaymentMethod


# ==================== PAYMENT METHOD CRUD TESTS ====================

@pytest.mark.django_db
class TestPaymentMethodCRUD:
    """Tests for payment method CRUD operations."""
    
    base_url = '/api/payment-methods/'
    
    def test_list_payment_methods_authenticated(self, authenticated_client, test_payment_method):
        """Test authenticated user can list their payment methods."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_list_payment_methods_unauthenticated(self, api_client):
        """Test unauthenticated user cannot list payment methods."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_create_upi_payment_method(self, authenticated_client):
        """Test creating UPI payment method."""
        data = {
            'payment_type': 'UPI',
            'upi_id': 'newuser@upi'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
    
    def test_create_card_payment_method(self, authenticated_client):
        """Test creating card payment method."""
        data = {
            'payment_type': 'CARD',
            'card_last_four': '1234',
            'card_brand': 'Visa'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
    
    def test_create_netbanking_payment_method(self, authenticated_client):
        """Test creating netbanking payment method."""
        data = {
            'payment_type': 'NETBANKING',
            'bank_name': 'Test Bank'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
    
    def test_retrieve_payment_method(self, authenticated_client, test_payment_method):
        """Test retrieving specific payment method."""
        response = authenticated_client.get(f'{self.base_url}{test_payment_method.id}/')
        assert response.status_code == status.HTTP_200_OK
    
    def test_update_payment_method(self, authenticated_client, test_payment_method):
        """Test updating payment method."""
        data = {'upi_id': 'updated@upi'}
        response = authenticated_client.patch(
            f'{self.base_url}{test_payment_method.id}/', 
            data, 
            format='json'
        )
        assert response.status_code == status.HTTP_200_OK
    
    def test_delete_payment_method(self, authenticated_client, test_payment_method):
        """Test deleting (soft delete) payment method."""
        response = authenticated_client.delete(f'{self.base_url}{test_payment_method.id}/')
        assert response.status_code == status.HTTP_204_NO_CONTENT
        
        # Verify soft deleted (is_active = False)
        test_payment_method.refresh_from_db()
        assert test_payment_method.is_active == False


# ==================== DEFAULT PAYMENT METHOD TESTS ====================

@pytest.mark.django_db
class TestDefaultPaymentMethod:
    """Tests for default payment method functionality."""
    
    base_url = '/api/payment-methods/'
    
    def test_set_default_payment_method(self, authenticated_client, test_payment_method):
        """Test setting payment method as default."""
        response = authenticated_client.post(
            f'{self.base_url}{test_payment_method.id}/set_default/'
        )
        assert response.status_code == status.HTTP_200_OK
        
        test_payment_method.refresh_from_db()
        assert test_payment_method.is_default == True
    
    def test_get_default_payment_method(self, authenticated_client, test_payment_method):
        """Test getting default payment method."""
        response = authenticated_client.get(f'{self.base_url}default/')
        assert response.status_code == status.HTTP_200_OK
    
    def test_get_default_when_none_set(self, authenticated_client, test_user):
        """Test getting default when none is set."""
        # Remove default
        PaymentMethod.objects.filter(user=test_user).update(is_default=False)
        
        response = authenticated_client.get(f'{self.base_url}default/')
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ==================== PAYMENT METHOD FILTERING TESTS ====================

@pytest.mark.django_db
class TestPaymentMethodFiltering:
    """Tests for payment method filtering."""
    
    base_url = '/api/payment-methods/'
    
    def test_filter_by_type_upi(self, authenticated_client, test_payment_method):
        """Test filtering payment methods by UPI type."""
        response = authenticated_client.get(f'{self.base_url}by_type/?type=UPI')
        assert response.status_code == status.HTTP_200_OK
    
    def test_filter_by_type_card(self, authenticated_client):
        """Test filtering payment methods by CARD type."""
        response = authenticated_client.get(f'{self.base_url}by_type/?type=CARD')
        assert response.status_code == status.HTTP_200_OK
    
    def test_filter_by_invalid_type(self, authenticated_client):
        """Test filtering by invalid type returns error."""
        response = authenticated_client.get(f'{self.base_url}by_type/?type=INVALID')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_filter_missing_type_param(self, authenticated_client):
        """Test filtering without type parameter fails."""
        response = authenticated_client.get(f'{self.base_url}by_type/')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_get_stats(self, authenticated_client, test_payment_method):
        """Test getting payment method statistics."""
        response = authenticated_client.get(f'{self.base_url}stats/')
        assert response.status_code == status.HTTP_200_OK
        assert 'total' in response.data
        assert 'by_type' in response.data


# ==================== PAYMENT METHOD AUTHORIZATION TESTS ====================

@pytest.mark.django_db
class TestPaymentMethodAuthorization:
    """Authorization tests for payment methods."""
    
    base_url = '/api/payment-methods/'
    
    def test_cannot_view_other_user_payment_methods(self, authenticated_client_user2, test_payment_method):
        """Test user cannot view another user's payment methods."""
        response = authenticated_client_user2.get(f'{self.base_url}{test_payment_method.id}/')
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_cannot_update_other_user_payment_method(self, authenticated_client_user2, test_payment_method):
        """Test user cannot update another user's payment method."""
        data = {'upi_id': 'hacked@upi'}
        response = authenticated_client_user2.patch(
            f'{self.base_url}{test_payment_method.id}/',
            data,
            format='json'
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_cannot_delete_other_user_payment_method(self, authenticated_client_user2, test_payment_method):
        """Test user cannot delete another user's payment method."""
        response = authenticated_client_user2.delete(f'{self.base_url}{test_payment_method.id}/')
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ==================== PAYMENT METHOD EDGE CASES ====================

@pytest.mark.django_db
class TestPaymentMethodEdgeCases:
    """Edge case tests for payment methods."""
    
    base_url = '/api/payment-methods/'
    
    def test_create_invalid_payment_type(self, authenticated_client):
        """Test creating with invalid payment type."""
        data = {
            'payment_type': 'BITCOIN'  # Invalid
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_create_missing_payment_type(self, authenticated_client):
        """Test creating without payment type."""
        data = {
            'upi_id': 'test@upi'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_sql_injection_in_upi_id(self, authenticated_client, malicious_inputs):
        """Test SQL injection in UPI ID."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'payment_type': 'UPI',
                'upi_id': payload
            }
            response = authenticated_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
