from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User



@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'username', 'first_name', 'last_name', 'phone', 'is_staff', 'created_at']
    list_filter = ['is_staff', 'is_superuser', 'is_active', 'created_at']
    search_fields = ['email', 'username', 'phone']
    ordering = ['-created_at']
    
    fieldsets = tuple(BaseUserAdmin.fieldsets or ()) + (
        ('Additional Info', {
            'fields': ('phone', 'address', 'city', 'state', 'pincode', 'profile_picture')
        }),
    )

