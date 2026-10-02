from django.contrib import admin

from .models import (
    UserEvent, UserGeo,
    DailySalesRollup, DailyFunnelRollup, SearchTermStat, DailyAnonStat,
)


@admin.register(UserEvent)
class UserEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'event_type', 'product', 'category', 'query', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('user__email', 'query')
    raw_id_fields = ('user', 'product', 'combo', 'category')
    date_hierarchy = 'created_at'


@admin.register(UserGeo)
class UserGeoAdmin(admin.ModelAdmin):
    list_display = ('user', 'city', 'state', 'pincode_prefix', 'updated_at')
    list_filter = ('state',)
    search_fields = ('user__email', 'city', 'state', 'pincode_prefix')
    raw_id_fields = ('user',)


# Rollup tables are computed by the rollup_analytics command; expose them
# read-only for inspection rather than manual editing.

@admin.register(DailySalesRollup)
class DailySalesRollupAdmin(admin.ModelAdmin):
    list_display = ('date', 'orders', 'units', 'revenue', 'aov',
                    'coupon_orders', 'new_customers', 'returning_customers')
    date_hierarchy = 'date'

    def has_add_permission(self, request):
        return False


@admin.register(DailyFunnelRollup)
class DailyFunnelRollupAdmin(admin.ModelAdmin):
    list_display = ('date', 'event_type', 'count')
    list_filter = ('event_type',)
    date_hierarchy = 'date'

    def has_add_permission(self, request):
        return False


@admin.register(SearchTermStat)
class SearchTermStatAdmin(admin.ModelAdmin):
    list_display = ('date', 'term', 'count', 'zero_result')
    list_filter = ('zero_result',)
    search_fields = ('term',)
    date_hierarchy = 'date'

    def has_add_permission(self, request):
        return False


@admin.register(DailyAnonStat)
class DailyAnonStatAdmin(admin.ModelAdmin):
    list_display = ('date', 'metric', 'dimension_key', 'count')
    list_filter = ('metric',)
    search_fields = ('dimension_key',)
    date_hierarchy = 'date'

    def has_add_permission(self, request):
        return False
