from django.contrib import admin
from .models import Payment, PaymentMethod, PaymentEvent, ProcessedWebhookEvent


class PaymentEventInline(admin.TabularInline):
    """Read-only lifecycle timeline shown on the Payment page."""
    model = PaymentEvent
    extra = 0
    can_delete = False
    fields = ['created_at', 'event_type', 'source', 'from_status', 'to_status',
              'is_exception', 'resolved', 'message']
    readonly_fields = fields
    ordering = ['-created_at']

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['payment_id', 'order', 'payment_gateway', 'amount', 'status',
                    'razorpay_payment_id', 'created_at']
    list_filter = ['payment_gateway', 'status', 'created_at']
    search_fields = ['payment_id', 'razorpay_payment_id', 'order__order_id']
    readonly_fields = ['payment_id', 'razorpay_payment_id', 'transaction_details',
                       'failure_code', 'failure_reason', 'created_at', 'updated_at']
    ordering = ['-created_at']
    inlines = [PaymentEventInline]


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    """Audit trail + exceptions queue. Default filter surfaces open exceptions —
    the highest-value view for the admin (§7.6c)."""
    list_display = ['created_at', 'event_type', 'source', 'payment', 'order',
                    'is_exception', 'resolved']
    list_filter = ['is_exception', 'resolved', 'source', 'event_type', 'created_at']
    search_fields = ['payment__payment_id', 'order__order_id', 'message']
    readonly_fields = ['payment', 'order', 'event_type', 'source', 'from_status',
                       'to_status', 'message', 'raw_payload', 'created_at']
    list_editable = ['resolved']
    ordering = ['-created_at']
    actions = ['mark_resolved']

    def has_add_permission(self, request):
        return False  # append-only

    @admin.action(description="Mark selected events resolved")
    def mark_resolved(self, request, queryset):
        queryset.update(resolved=True)


@admin.register(ProcessedWebhookEvent)
class ProcessedWebhookEventAdmin(admin.ModelAdmin):
    list_display = ['event_id', 'event_type', 'received_at']
    search_fields = ['event_id']
    readonly_fields = ['event_id', 'event_type', 'received_at']
    ordering = ['-received_at']

    def has_add_permission(self, request):
        return False


class PaymentMethodInline(admin.TabularInline):
    model = PaymentMethod
    extra = 0
    fields = ['payment_type', 'upi_id', 'card_last_four', 'card_brand', 
              'bank_name', 'wallet_provider', 'is_default', 'is_active']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['user', 'payment_type', 'masked_display', 'is_default', 
                    'is_active', 'created_at']
    list_filter = ['payment_type', 'is_default', 'is_active', 'created_at']
    search_fields = ['user__email', 'upi_id', 'card_brand', 'bank_name']
    readonly_fields = ['created_at', 'updated_at', 'masked_display']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('user', 'payment_type', 'is_default', 'is_active')
        }),
        ('UPI Details', {
            'fields': ('upi_id',),
            'classes': ('collapse',)
        }),
        ('Card Details', {
            'fields': ('card_last_four', 'card_brand', 'card_expiry_month', 
                      'card_expiry_year', 'gateway_token', 'gateway_name'),
            'classes': ('collapse',)
        }),
        ('Banking Details', {
            'fields': ('bank_name',),
            'classes': ('collapse',)
        }),
        ('Wallet Details', {
            'fields': ('wallet_provider',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )