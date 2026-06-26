from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import ApiKey, Link, Profile

@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ('short_code', 'original_url', 'created_at')
    search_fields = ('short_code', 'original_url')
    readonly_fields = ('short_code',)

@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'prefix', 'created_by', 'is_active', 'expires_at', 'last_used_at', 'created_at')
    search_fields = ('name', 'prefix')
    readonly_fields = ('prefix', 'key_hash', 'last_used_at', 'created_at')

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profile'

class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_avatar_url')
    
    def get_avatar_url(self, obj):
        return obj.profile.avatar_url
    get_avatar_url.short_description = 'Avatar URL'

admin.site.unregister(User)
admin.site.register(User, UserAdmin)
