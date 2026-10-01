import json
import logging

from django.conf import settings
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny

from orders.models import Order
from spices_backend.throttles import PaymentRateThrottle
from .models import Payment, PaymentMethod
from .serializers import (
    PaymentMethodSerializer, PaymentMethodCreateSerializer,
    CreateOrderSerializer, VerifyPaymentSerializer,
)
from .gateway import get_razorpay_client, get_public_key_id, RazorpayNotConfigured
from . import services

logger = logging.getLogger(__name__)

# Customer-facing status text derived from Order.payment_status (§7.6b). Crucially
# the "paid at Razorpay but our /verify/ hasn't confirmed" window shows
# "Confirming…", never "failed".
PAYMENT_STATUS_LABELS = {
    'pending': 'Payment pending',
    'processing': 'Confirming your payment…',
    'paid': 'Payment received',
    'failed': 'Payment failed — retry',
    'rejected': 'Payment not completed — order cancelled',
    'refunded': 'Refunded',
}


# Create your views here.


class PaymentMethodViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing payment methods
    
    Endpoints:
    - GET /api/payment-methods/ - List all payment methods
    - POST /api/payment-methods/ - Create new payment method
    - GET /api/payment-methods/{id}/ - Get specific payment method
    - PUT/PATCH /api/payment-methods/{id}/ - Update payment method
    - DELETE /api/payment-methods/{id}/ - Delete (soft delete) payment method
    - POST /api/payment-methods/{id}/set_default/ - Set as default
    - GET /api/payment-methods/default/ - Get default payment method
    - GET /api/payment-methods/by_type/?type=UPI - Filter by type
    """
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Users can only see their own payment methods
        """
        return PaymentMethod.objects.filter(
            user=self.request.user,
            is_active=True
        )

    def get_serializer_class(self):
        """
        Use different serializer for create action
        """
        if self.action == 'create':
            return PaymentMethodCreateSerializer
        return PaymentMethodSerializer

    def perform_create(self, serializer):
        """
        Automatically set the user when creating a payment method
        """
        serializer.save(user=self.request.user)

    def perform_destroy(self, instance):
        """
        Soft delete - set is_active to False instead of deleting
        """
        instance.is_active = False
        instance.save()

    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """
        Set a payment method as default
        
        Usage: POST /api/payment-methods/{id}/set_default/
        """
        payment_method = self.get_object()
        
        # Remove default from all other payment methods
        PaymentMethod.objects.filter(
            user=request.user,
            is_default=True
        ).update(is_default=False)
        
        # Set this one as default
        payment_method.is_default = True
        payment_method.save()
        
        serializer = self.get_serializer(payment_method)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def default(self, request):
        """
        Get the default payment method
        
        Usage: GET /api/payment-methods/default/
        """
        payment_method = PaymentMethod.objects.filter(
            user=request.user,
            is_default=True,
            is_active=True
        ).first()
        
        if not payment_method:
            return Response(
                {'detail': 'No default payment method found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(payment_method)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_type(self, request):
        """
        Get payment methods filtered by type
        
        Usage: GET /api/payment-methods/by_type/?type=UPI
        Supported types: UPI, CARD, NETBANKING, WALLET
        """
        payment_type = request.query_params.get('type', None)
        
        if not payment_type:
            return Response(
                {'detail': 'Payment type parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate payment type
        valid_types = ['UPI', 'CARD', 'NETBANKING', 'WALLET']
        payment_type_upper = payment_type.upper()
        
        if payment_type_upper not in valid_types:
            return Response(
                {
                    'detail': f'Invalid payment type. Must be one of: {", ".join(valid_types)}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment_methods = self.get_queryset().filter(payment_type=payment_type_upper)
        serializer = self.get_serializer(payment_methods, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Get statistics about user's payment methods
        
        Usage: GET /api/payment-methods/stats/
        """
        queryset = self.get_queryset()
        
        stats = {
            'total': queryset.count(),
            'by_type': {
                'upi': queryset.filter(payment_type='UPI').count(),
                'card': queryset.filter(payment_type='CARD').count(),
                'netbanking': queryset.filter(payment_type='NETBANKING').count(),
                'wallet': queryset.filter(payment_type='WALLET').count(),
            },
            'has_default': queryset.filter(is_default=True).exists()
        }

        return Response(stats)


# ===========================================================================
# Razorpay online-payment endpoints
# ===========================================================================

def _amount_paise(order):
    from decimal import Decimal
    return int((Decimal(str(order.total_amount)) * 100).to_integral_value())


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([PaymentRateThrottle])
def create_razorpay_order(request):
    """POST /api/payments/create-order/  {order_id}

    Creates (or returns the existing) Razorpay order for a payable Order. The
    amount is always computed server-side from Order.total_amount; the client
    never sends an amount. Idempotent: one live Razorpay order per Order (§7.7).
    """
    serializer = CreateOrderSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    order_id = serializer.validated_data['order_id']

    order = Order.objects.filter(pk=order_id).first()
    if order is None or order.user_id != request.user.id:
        return Response({'error': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

    if order.status == 'cancelled':
        return Response({'error': 'This order has been cancelled.'},
                        status=status.HTTP_400_BAD_REQUEST)
    if order.payment_status == 'paid':
        return Response({'error': 'This order is already paid.'},
                        status=status.HTTP_400_BAD_REQUEST)
    if _amount_paise(order) <= 0:
        return Response({'error': 'This order has no payable amount.'},
                        status=status.HTTP_400_BAD_REQUEST)

    # Idempotency: reuse an existing pending Razorpay order for this Order — never
    # mint a second live one the customer could also pay. Only reuse when its
    # amount still matches the order total; a changed total must supersede it.
    existing = Payment.objects.filter(order=order, payment_gateway='razorpay').first()
    if (existing and existing.status == 'pending' and existing.payment_id
            and existing.amount == order.total_amount):
        return Response({
            'razorpay_order_id': existing.payment_id,
            'razorpay_key_id': get_public_key_id(),
            'amount': _amount_paise(order),
            'currency': 'INR',
            'order_id': order.id,
        })

    try:
        client = get_razorpay_client()
    except RazorpayNotConfigured:
        logger.error("Razorpay keys not configured; cannot create order")
        return Response({'error': 'Online payment is temporarily unavailable.'},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)

    try:
        rzp_order = client.order.create({
            'amount': _amount_paise(order),
            'currency': 'INR',
            'receipt': f'order_{order.id}',
            'payment_capture': 1,
        })
    except Exception:  # noqa: BLE001
        logger.exception("Razorpay order.create failed for order %s", order.id)
        return Response({'error': 'Could not start payment. Please try again.'},
                        status=status.HTTP_502_BAD_GATEWAY)

    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)
        payment = Payment.objects.select_for_update().filter(order=locked_order).first()

        # Concurrency guard: a double-submit could pass the unlocked check above
        # and both reach client.order.create(). Under the lock, if a live pending
        # Razorpay order for the current amount already exists, reuse it and let
        # the one we just minted go unused — never overwrite a live order the
        # customer may already be paying.
        if (payment is not None and payment.status == 'pending' and payment.payment_id
                and payment.amount == locked_order.total_amount):
            active_order_id = payment.payment_id
        else:
            superseded = None
            if payment is None:
                payment = Payment(order=locked_order, payment_gateway='razorpay',
                                  amount=locked_order.total_amount)
            else:
                # Legitimate supersession — record the old id so a late capture on
                # it can still be resolved (→ refund, §7.7).
                if payment.payment_id and payment.payment_id != rzp_order['id']:
                    superseded = payment.payment_id
                payment.amount = locked_order.total_amount
                payment.status = 'pending'
            payment.payment_id = rzp_order['id']
            details = dict(payment.transaction_details or {})
            if superseded:
                details.setdefault('superseded_order_ids', []).append(superseded)
            payment.transaction_details = details
            payment.save()

            services.log_payment_event(
                payment, event_type='order_created', source='client',
                to_status='pending',
                message=f"Razorpay order {rzp_order['id']} created for ₹{locked_order.total_amount}.")
            active_order_id = rzp_order['id']

    return Response({
        'razorpay_order_id': active_order_id,
        'razorpay_key_id': get_public_key_id(),
        'amount': _amount_paise(order),
        'currency': 'INR',
        'order_id': order.id,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([PaymentRateThrottle])
def verify_payment(request):
    """POST /api/payments/verify/  {razorpay_order_id, razorpay_payment_id, razorpay_signature}

    L1 fast-path confirmation from the browser. Verifies the HMAC signature, then
    funnels through the shared idempotent capture. UX confirmation only — the
    webhook (L2) reconciles reality.
    """
    serializer = VerifyPaymentSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    # Ownership: the razorpay_order_id must map to one of THIS user's orders.
    payment = Payment.objects.select_related('order').filter(
        payment_id=data['razorpay_order_id']).first()
    if payment is None or payment.order.user_id != request.user.id:
        return Response({'error': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)

    try:
        client = get_razorpay_client()
    except RazorpayNotConfigured:
        return Response({'error': 'Online payment is temporarily unavailable.'},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)

    try:
        client.utility.verify_payment_signature({
            'razorpay_order_id': data['razorpay_order_id'],
            'razorpay_payment_id': data['razorpay_payment_id'],
            'razorpay_signature': data['razorpay_signature'],
        })
    except Exception:  # noqa: BLE001 — razorpay raises SignatureVerificationError
        services.log_payment_event(
            payment, event_type='verify_signature_failed', source='client',
            message='Invalid signature on /verify/.', is_exception=True)
        return Response({'error': 'Payment verification failed.'},
                        status=status.HTTP_400_BAD_REQUEST)

    result = services.mark_payment_captured(
        razorpay_order_id=data['razorpay_order_id'],
        razorpay_payment_id=data['razorpay_payment_id'],
        source='client',
    )

    # Capture-after-cancel: the money was recorded truthfully and routed to refund,
    # but the order is NOT confirmed — don't show the customer a false success.
    if result is not None and result.order.status == 'cancelled':
        return Response({
            'success': False,
            'order_id': payment.order_id,
            'status': 'cancelled',
            'message': ('This order was cancelled. If you were charged, a refund '
                        'will be issued automatically — no action needed.'),
        })
    return Response({'success': True, 'order_id': payment.order_id})


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def razorpay_webhook(request):
    """POST /api/payments/webhook/  (called by Razorpay — no auth, signature-gated)

    L2 source of truth. Verifies the signature over the RAW body, then dispatches
    the event through the shared idempotent handlers. ACKs 200 only after the DB
    commits; unknown events are ACKed 200 (don't trigger 24h of retries).
    """
    secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')
    signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE', '')
    event_id = request.META.get('HTTP_X_RAZORPAY_EVENT_ID', '') or None
    raw_body = request.body  # raw bytes — must not be re-serialised

    if not secret:
        logger.error("Razorpay webhook received but RAZORPAY_WEBHOOK_SECRET is unset")
        return Response({'error': 'Webhook not configured.'}, status=status.HTTP_400_BAD_REQUEST)

    # Cap body size (defence against absurd payloads).
    if len(raw_body) > 1_000_000:
        return Response({'error': 'Payload too large.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        client = get_razorpay_client()
        client.utility.verify_webhook_signature(
            raw_body.decode('utf-8'), signature, secret)
    except Exception:  # noqa: BLE001
        logger.warning("Razorpay webhook signature verification failed")
        return Response({'error': 'Invalid signature.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return Response({'error': 'Invalid JSON.'}, status=status.HTTP_400_BAD_REQUEST)

    event_type = payload.get('event', '')

    try:
        _dispatch_webhook_event(event_type, payload, event_id)
    except services.PaymentNotFound:
        # Money we can't match to a local Payment — record + alert, still ACK 200
        # (a 4xx would just trigger retries; L3/resync will reconcile).
        _log_orphan(event_type, payload)
    except Exception:  # noqa: BLE001
        # A real processing error: do NOT ACK — let Razorpay redeliver.
        logger.exception("Webhook processing error for event %s", event_type)
        return Response({'error': 'processing error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ACK only after the transaction(s) above committed.
    return Response({'status': 'ok'})


def _dispatch_webhook_event(event_type, payload, event_id):
    entity = payload.get('payload', {})
    if event_type in ('payment.captured', 'order.paid'):
        pay = entity.get('payment', {}).get('entity', {})
        services.mark_payment_captured(
            razorpay_order_id=pay.get('order_id'),
            razorpay_payment_id=pay.get('id'),
            event_id=event_id, source='webhook',
            amount=pay.get('amount'), raw_payload=payload,
            payment_entity=pay)
    elif event_type == 'payment.failed':
        pay = entity.get('payment', {}).get('entity', {})
        err = pay.get('error_code') or pay.get('error_reason')
        services.mark_payment_failed(
            razorpay_order_id=pay.get('order_id'), event_id=event_id, source='webhook',
            error_code=err, error_description=pay.get('error_description'),
            raw_payload=payload, payment_entity=pay)
    elif event_type == 'refund.processed':
        # DISABLED 2026-08-01 — refunds are MANUAL-ONLY for now. The gateway no
        # longer writes to the refund ledger; an admin records the refund in the
        # panel (PATCH status='refunded' → orders/refunds.py record_refund) after
        # issuing it at Razorpay. Logged loudly rather than dropped, because an
        # unrecorded refund leaves the order reading 'paid' and its GST
        # un-reversed — i.e. tax paid on money already returned.
        #
        # To re-enable: restore the call below and un-comment
        # test_refund_webhook_without_order_id_still_refunds.
        #
        # refund = entity.get('refund', {}).get('entity', {})
        # services.mark_payment_refunded(
        #     razorpay_order_id=refund.get('order_id'),
        #     razorpay_payment_id=refund.get('payment_id'), event_id=event_id,
        #     source='webhook', raw_payload=payload,
        #     # Amount (paise) and the gateway refund id drive the GST reversal and
        #     # its idempotency — without them a refund can't reduce what's owed.
        #     refund_amount_paise=refund.get('amount'),
        #     refund_reference=refund.get('id'))
        refund = entity.get('refund', {}).get('entity', {})
        logger.warning(
            "refund.processed IGNORED (manual-only mode): refund %s on payment %s. "
            "Record it in the admin panel or the order's GST stays un-reversed.",
            refund.get('id'), refund.get('payment_id'))
    else:
        # Unknown/unsubscribed — ACK without action.
        logger.info("Ignoring unsubscribed webhook event: %s", event_type)


def _log_orphan(event_type, payload):
    services.log_payment_event(
        payment=None, order=None, event_type='orphan_payment', source='webhook',
        message=f"Webhook {event_type} for an unknown/absent local Payment.",
        raw_payload=payload, is_exception=True)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_status(request):
    """GET /api/payments/status/?order_id=  → honest, non-alarming payment state.

    Frontend polls this after Checkout so the "paid but /verify/ not yet
    confirmed" window shows "Confirming…" and flips to "Payment received" once
    the webhook lands — never a false failure.
    """
    order_id = request.query_params.get('order_id')
    if not order_id:
        return Response({'error': 'order_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
    order = Order.objects.filter(pk=order_id).first()
    if order is None or order.user_id != request.user.id:
        return Response({'error': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

    pay = getattr(order, 'payment', None)
    return Response({
        'order_id': order.id,
        'payment_status': order.payment_status,
        'order_status': order.status,
        'label': PAYMENT_STATUS_LABELS.get(order.payment_status, order.payment_status),
        'razorpay_payment_id': getattr(pay, 'razorpay_payment_id', None),
    })



