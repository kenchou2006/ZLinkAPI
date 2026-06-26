from django.db.models.signals import post_save, post_delete,post_migrate
from django.dispatch import receiver
from django.core.cache import cache
from .models import Link
from .utils import link_cache_key
from django.contrib.auth import get_user_model
from django.conf import settings


import logging

logger = logging.getLogger(__name__)


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