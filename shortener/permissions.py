from rest_framework.permissions import BasePermission

from .models import ApiKey


class IsStaffOrApiKey(BasePermission):
    """Allow active staff (via JWT) OR a valid API key.

    The API key is already validated in ApiKeyAuthentication, so its presence
    on request.auth is sufficient here.
    """

    def has_permission(self, request, view):
        if isinstance(request.auth, ApiKey):
            return True
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_staff)


class IsStaff(BasePermission):
    """Allow access only to active staff users (管理者)."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_staff)


class IsSuperUser(BasePermission):
    """Allow access only to active superusers (超級管理者)."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_superuser)
