"""
Comprehensive tests for the Admin Panel app.
Covers dashboard, coupons, policies, and superuser authorization.
"""
import pytest
from decimal import Decimal
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
from admin_panel.models import Coupon, Policy


# ==================== DASHBOARD TESTS ====================

@pytest.mark.django_db
class TestDashboard:
    """Tests for dashboard endpoint."""
    
    base_url = '/api/dashboard/'
    
    def test_dashboard_authenticated(self, authenticated_client):
        """Test a regular (non-admin) user is forbidden from the dashboard.

        DashboardViewSet is IsAdminUser-only (sales/business stats)."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_dashboard_admin(self, admin_client):
        """Test admin can access dashboard."""
        response = admin_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_dashboard_unauthenticated(self, api_client):
        """Test unauthenticated user cannot access dashboard."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ==================== COUPON MANAGEMENT TESTS ====================

@pytest.mark.django_db
class TestCouponManagement:
    """Tests for coupon management (superuser only)."""
    
    base_url = '/api/coupons/'
    
    def test_list_coupons_admin(self, admin_client, test_coupon):
        """Test admin can list coupons."""
        response = admin_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_list_coupons_regular_user_forbidden(self, authenticated_client):
        """Test regular user cannot list coupons."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_list_coupons_unauthenticated_forbidden(self, api_client):
        """Test unauthenticated user cannot list coupons."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_create_coupon_admin(self, admin_client):
        """Test admin can create coupon."""
        data = {
            'code': 'NEWCOUPON20',
            'discount_percent': 20,
            'is_active': True,
            'valid_until': (timezone.now() + timedelta(days=30)).isoformat()
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
    
    def test_create_coupon_regular_user_forbidden(self, authenticated_client):
        """Test regular user cannot create coupon."""
        data = {
            'code': 'HACKEDCOUPON',
            'discount_percent': 100,
            'is_active': True
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_update_coupon_admin(self, admin_client, test_coupon):
        """Test admin can update coupon."""
        data = {'discount_percent': 15}
        response = admin_client.patch(
            f'{self.base_url}{test_coupon.id}/',
            data,
            format='json'
        )
        assert response.status_code == status.HTTP_200_OK
    
    def test_delete_coupon_admin(self, admin_client, test_coupon):
        """Test admin can delete coupon."""
        response = admin_client.delete(f'{self.base_url}{test_coupon.id}/')
        assert response.status_code == status.HTTP_204_NO_CONTENT
    
    def test_delete_coupon_regular_user_forbidden(self, authenticated_client, test_coupon):
        """Test regular user cannot delete coupon."""
        response = authenticated_client.delete(f'{self.base_url}{test_coupon.id}/')
        assert response.status_code == status.HTTP_403_FORBIDDEN


# ==================== COUPON EDGE CASES ====================

@pytest.mark.django_db
class TestCouponEdgeCases:
    """Edge case tests for coupons."""
    
    base_url = '/api/coupons/'
    
    def test_create_coupon_duplicate_code(self, admin_client, test_coupon):
        """Test creating coupon with duplicate code fails."""
        data = {
            'code': test_coupon.code,  # Duplicate
            'discount_percent': 15,
            'is_active': True
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_create_coupon_negative_discount(self, admin_client):
        """Test creating coupon with negative discount."""
        data = {
            'code': 'NEGATIVEDISCOUNT',
            'discount_percent': -10,
            'is_active': True
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_coupon_over_100_discount(self, admin_client):
        """Test creating coupon with > 100% discount."""
        data = {
            'code': 'FREEDISCOUNT',
            'discount_percent': 150,
            'is_active': True
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_coupon_zero_discount(self, admin_client):
        """Test creating coupon with zero discount."""
        data = {
            'code': 'ZERODISCOUNT',
            'discount_percent': 0,
            'is_active': True
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_coupon_sql_injection_in_code(self, admin_client, malicious_inputs):
        """Test SQL injection in coupon code."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'code': payload[:20],  # Truncate for code field
                'discount_percent': 10,
                'is_active': True
            }
            response = admin_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== POLICY MANAGEMENT TESTS ====================

@pytest.mark.skip(
    reason="Policy API retired — routes unregistered in spices_backend/urls.py; "
           "the storefront serves static policy pages. Remove this skip if the "
           "PolicyViewSet is re-registered."
)
@pytest.mark.django_db
class TestPolicyManagement:
    """Tests for policy management."""

    base_url = '/api/policies/'
    
    def test_list_policies_public(self, api_client):
        """Test anyone can list policies."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_retrieve_policy_public(self, api_client, db):
        """Test anyone can retrieve a policy."""
        # Create a policy first
        policy = Policy.objects.create(
            type='shipping',
            content='Test privacy policy content'
        )
        
        # Use ID for lookup
        response = api_client.get(f'{self.base_url}{policy.type}/')
        assert response.status_code == status.HTTP_200_OK
    
    def test_update_policy_admin_only(self, admin_client, db):
        """Test only admin can update policy."""
        policy = Policy.objects.create(
            type='shipping',
            content='Original terms'
        )
        
        data = {'content': 'Updated terms content'}
        response = admin_client.patch(f'{self.base_url}{policy.type}/', data, format='json')
        assert response.status_code == status.HTTP_200_OK
    
    def test_update_policy_regular_user_forbidden(self, authenticated_client, db):
        """Test regular user cannot update policy."""
        policy = Policy.objects.create(
            type='return',
            content='Original refund policy'
        )
        
        data = {'content': 'Hacked content'}
        response = authenticated_client.patch(
            f'{self.base_url}{policy.type}/',
            data,
            format='json'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_update_policy_unauthenticated_forbidden(self, api_client, db):
        """Test unauthenticated user cannot update policy."""
        policy = Policy.objects.create(
            type='shipping',
            content='Original shipping policy'
        )
        
        data = {'content': 'Hacked content'}
        response = api_client.patch(f'{self.base_url}{policy.type}/', data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ==================== POLICY EDGE CASES ====================

@pytest.mark.skip(
    reason="Policy API retired — routes unregistered in spices_backend/urls.py; "
           "the storefront serves static policy pages. Remove this skip if the "
           "PolicyViewSet is re-registered."
)
@pytest.mark.django_db
class TestPolicyEdgeCases:
    """Edge case tests for policies."""

    base_url = '/api/policies/'
    
    def test_retrieve_nonexistent_policy(self, api_client, db):
        """Test retrieving a valid-but-unconfigured policy type returns 404.

        Policies are looked up by type (shipping/return); a valid type with no
        row yields 404, while an invalid type yields 400."""
        response = api_client.get(f'{self.base_url}shipping/')
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_policy_xss_in_content(self, admin_client, db, malicious_inputs):
        """Test XSS payloads in policy content."""
        policy = Policy.objects.create(
            type='shipping',
            content='Original content'
        )
        
        for payload in malicious_inputs.XSS_PAYLOADS:
            data = {'content': payload}
            response = admin_client.patch(
                f'{self.base_url}{policy.type}/',
                data,
                format='json'
            )
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_policy_sql_injection_in_content(self, admin_client, db, malicious_inputs):
        """Test SQL injection in policy content."""
        policy = Policy.objects.create(
            type='return',
            content='Original'
        )
        
        for payload in malicious_inputs.SQL_INJECTION:
            data = {'content': payload}
            response = admin_client.patch(
                f'{self.base_url}{policy.type}/',
                data,
                format='json'
            )
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== RECEIVABLE ACCOUNT TESTS ====================

@pytest.mark.django_db
class TestReceivableAccount:
    """Tests for receivable account management."""
    
    base_url = '/api/receivable-accounts/'
    
    def test_list_receivable_accounts_authenticated(self, authenticated_client):
        """Test a regular (non-admin) user is forbidden from receivable accounts.

        ReceivableAccountViewSet is IsAdminUser-only (payment collection data)."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_list_receivable_accounts_unauthenticated(self, api_client):
        """Test unauthenticated user cannot list receivable accounts."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
