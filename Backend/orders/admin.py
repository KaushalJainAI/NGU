from django.contrib import admin
from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product', 'product_name', 'product_weight', 'quantity', 
                      'price', 'discount_amount', 'discounted_price', 
                      'tax_amount', 'final_price', 'original_subtotal_display']
    fields = ['product', 'product_name', 'product_weight', 'quantity', 
              'price', 'original_subtotal_display', 'discount_amount', 
              'discounted_price', 'tax_amount', 'final_price']
    can_delete = False
    
    def original_subtotal_display(self, obj):
        """Display original subtotal before discount"""
        if obj.id:
            return f"₹{obj.original_subtotal:.2f}"
        return "-"
    original_subtotal_display.short_description = "Original Total"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_id', 'user', 'status', 'payment_method', 'coupon_display', 
                    'discount_amount', 'total_amount', 'created_at']
    list_filter = ['status', 'payment_method', 'payment_status', 'created_at', 'coupon']
    search_fields = ['order_id', 'user__email', 'user__username', 'phone_number', 'coupon__code']
    readonly_fields = ['order_id', 'subtotal', 'discount_amount', 'shipping_charge', 
                      'tax', 'total_amount', 'created_at', 'updated_at']
    list_editable = ['status']
    ordering = ['-created_at']
    inlines = [OrderItemInline]
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order_id', 'user', 'status', 'payment_method', 'payment_status')
        }),
        ('Shipping Details', {
            'fields': ('shipping_address', 'phone_number')
        }),
        ('Pricing & Discount', {
            'fields': ('subtotal', 'coupon', 'discount_amount', 'shipping_charge', 
                      'tax', 'total_amount')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'delivered_at')
        }),
    )
    
    def coupon_display(self, obj):
        """Display coupon code if applied"""
        if obj.coupon:
            return f"{obj.coupon.code} (-₹{obj.discount_amount:.2f})"
        return "-"
    coupon_display.short_description = "Coupon"


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['order', 'product_name', 'quantity', 'price', 
                    'discount_amount', 'discounted_price', 'final_price']
    list_filter = ['order__status', 'order__created_at']
    search_fields = ['product_name', 'order__order_id', 'product__name']
    readonly_fields = ['order', 'product', 'product_name', 'product_weight', 
                      'quantity', 'price', 'discount_amount', 'discounted_price', 
                      'tax_amount', 'final_price']
    
    fieldsets = (
        ('Order & Product', {
            'fields': ('order', 'product', 'product_name', 'product_weight', 'quantity')
        }),
        ('Pricing Details', {
            'fields': ('price', 'discount_amount', 'discounted_price', 'tax_amount', 'final_price')
        }),
    )
