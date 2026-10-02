from django.contrib import admin

# Register your models here.
from .models import ReceivableAccount, Coupon

@admin.register(ReceivableAccount)
class ReceivableAccountAdmin(admin.ModelAdmin):
    list_display = ('account_holder_name', 'upi_id', 'bank_name', 'contact_email', 'contact_phone', 'created_at')
    search_fields = ('account_holder_name', 'upi_id', 'bank_name', 'contact_email')
    list_filter = ('bank_name', 'created_at')
    ordering = ('-created_at',)

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('code', 'discount_percent', 'is_active', 'valid_until')
    search_fields = ('code',)
    list_filter = ('is_active', 'valid_until')
    ordering = ('-valid_until', '-id')

# Policy admin is intentionally not registered — policy content is served as
# static storefront pages. The Policy model is kept but inactive.