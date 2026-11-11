from django.contrib import admin
from .models import OfficerProfile


@admin.register(OfficerProfile)
class OfficerProfileAdmin(admin.ModelAdmin):
    list_display = ('officer_id', 'user', 'designation', 'badge_number', 'is_active', 'created_at')
    list_filter = ('is_active', 'designation')
    search_fields = ('officer_id', 'badge_number', 'user__username', 'user__first_name', 'user__last_name', 'user__email')
    ordering = ('officer_id',)
