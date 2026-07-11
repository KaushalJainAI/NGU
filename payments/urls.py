"""Razorpay payment endpoints (the saved PaymentMethod CRUD stays on the router
in spices_backend/urls.py)."""
from django.urls import path

from . import views

urlpatterns = [
    path('create-order/', views.create_razorpay_order, name='payments-create-order'),
    path('verify/', views.verify_payment, name='payments-verify'),
    path('webhook/', views.razorpay_webhook, name='payments-webhook'),
    path('status/', views.payment_status, name='payments-status'),
]
