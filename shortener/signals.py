from django.db.models.signals import post_save, post_delete,post_migrate
from django.dispatch import receiver
from django.core.cache import cache
from .models import Link
from .utils import link_cache_key
from django.contrib.auth import get_user_model
from django.conf import settings


import logging

logger = logging.getLogger(__name__)

# No cron/worker process is available on this (serverless) deployment, so
# expired JWT OutstandingToken/BlacklistedToken rows are never cleaned up on
# a schedule. Piggyback on the thing that grows the table in the first place:
# every login/refresh issues a new OutstandingToken. Use a cache-backed
# debounce (not randomness) so cleanup runs at most once per interval no
# matter how many tokens get issued in between.
EXPIRED_TOKEN_CLEANUP_INTERVAL_SECONDS = 60 * 60  # at most once per hour
EXPIRED_TOKEN_CLEANUP_LOCK_KEY = "jwt:expired_token_cleanup_lock"


@receiver(post_save, sender="token_blacklist.OutstandingToken")
def maybe_flush_expired_tokens(sender, created, **kwargs):
    if not created:
        return
    # cache.add only succeeds (and sets the lock) if the key isn't already
    # present, so this is a no-op for every issuance except the first one
    # after the lock expires. Token issuance must still succeed even if the
    # cache backend (Redis) is unreachable, so skip cleanup rather than raise.
    try:
        acquired_lock = cache.add(EXPIRED_TOKEN_CLEANUP_LOCK_KEY, True, timeout=EXPIRED_TOKEN_CLEANUP_INTERVAL_SECONDS)
    except Exception:
        logger.warning("Cache unavailable, skipping expired token cleanup check")
        return
    if not acquired_lock:
        return
    from django.core.management import call_command

    try:
        call_command("flushexpiredtokens")
    except Exception:
        logger.warning("flushexpiredtokens failed", exc_info=True)


@receiver([post_save, post_delete], sender=Link)
def clear_link_cache(sender, instance, **kwargs):
    try:
        cache.delete(link_cache_key(instance.short_code))
    except Exception:
        # Cache backend (Redis) may be unavailable; the link write must still
        # succeed. The Go client tolerates stale cache via TTL.
        logger.warning("Cache delete failed for %s", instance.short_code)

@receiver(post_migrate)
def create_superuser(sender, **kwargs):
    User = get_user_model()
    if not User.objects.filter(is_superuser=True).exists() and not settings.DEBUG:
        User.objects.create_superuser(
            username=settings.DEFAULT_SUPERUSER_USERNAME,
            email=settings.DEFAULT_SUPERUSER_EMAIL,
            password=settings.DEFAULT_SUPERUSER_PASSWORD
        )
        print(f"Superuser '{settings.DEFAULT_SUPERUSER_USERNAME}' created successfully.")

@receiver(post_save, sender=get_user_model())
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        from .models import Profile
        Profile.objects.create(user=instance)
    else:
        # Just in case it doesn't exist for some reason
        from .models import Profile
        if not hasattr(instance, 'profile'):
            Profile.objects.create(user=instance)
        instance.profile.save()