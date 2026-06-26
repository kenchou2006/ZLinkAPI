from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import ApiKey, hash_api_key


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate via the `X-API-Key` header.

    Returns (owner_user, api_key). The key's owner must still be active.
    Use alongside JWTAuthentication on endpoints that accept either.
    """

    def authenticate(self, request):
        raw = request.META.get('HTTP_X_API_KEY')
        if not raw:
            return None  # let other authenticators try

        key = (
            ApiKey.objects
            .select_related('created_by')
            .filter(key_hash=hash_api_key(raw))
            .first()
        )
        if key is None:
            raise exceptions.AuthenticationFailed('Invalid API key.')
        if not key.is_valid:
            raise exceptions.AuthenticationFailed('API key is inactive or expired.')

        owner = key.created_by
        if owner is None or not owner.is_active:
            raise exceptions.AuthenticationFailed('API key owner is disabled.')

        # Best-effort last-used timestamp (single UPDATE, no model save signals).
        ApiKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())

        return (owner, key)
