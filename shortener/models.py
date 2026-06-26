from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import hashlib
import secrets
import string
import random


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_short_code():
    length = 6
    while True:
        code = ''.join(random.choices(string.ascii_letters + string.digits, k=length))
        if not Link.objects.filter(short_code=code).exists():
            return code

class Link(models.Model):
    original_url = models.URLField()
    short_code = models.CharField(max_length=15, unique=True, default=generate_short_code, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # None = never expires.
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    def __str__(self):
        return f"{self.short_code} -> {self.original_url}"

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    avatar_url = models.URLField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}'s profile"


class ApiKey(models.Model):
    """An API key for managing short links via the API without a login session.

    Only the SHA-256 hash of the key is stored; the plaintext is shown once at
    creation. `expires_at = None` means the key never expires.
    """
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='api_keys'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    @classmethod
    def generate(cls):
        """Return (raw_key, unsaved ApiKey). The raw key is shown to the user once."""
        raw = 'zlk_' + secrets.token_urlsafe(32)
        return raw, cls(prefix=raw[:12], key_hash=hash_api_key(raw))

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_valid(self) -> bool:
        return self.is_active and not self.is_expired

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"


class Passkey(models.Model):
    """A WebAuthn credential (passkey) registered by a user as a login method."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='passkeys')
    name = models.CharField(max_length=100, blank=True)
    credential_id = models.CharField(max_length=255, unique=True, db_index=True)
    public_key = models.TextField()
    sign_count = models.BigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    # Identifies the authenticator model (e.g. Google Password Manager, iCloud
    # Keychain) so the UI can show where a passkey lives. Blank when the
    # authenticator reports an all-zero/unrecognized AAGUID.
    aaguid = models.CharField(max_length=36, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username}'s passkey ({self.name or self.credential_id[:8]})"
