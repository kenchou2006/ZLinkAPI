from django.core.cache import cache
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from .models import Link
from .utils import link_cache_key
import logging

logger = logging.getLogger(__name__)


def invalidate_link_cache(short_code: str):
    try:
        cache.delete(link_cache_key(short_code))
    except Exception:
        logger.debug("Cache delete failed for %s", short_code)


def purge_expired_links() -> int:
    """Delete all expired links (and clear their cache). Returns the count."""
    expired = Link.objects.filter(expires_at__isnull=False, expires_at__lte=timezone.now())
    count = expired.count()
    for link in expired:
        invalidate_link_cache(link.short_code)
    expired.delete()
    return count


def update_link(link: Link, original_url: str | None, new_short_code: str | None):
    old_code = link.short_code
    if original_url:
        link.original_url = original_url
    if new_short_code and new_short_code != link.short_code:
        link.short_code = new_short_code
    with transaction.atomic():
        link.save()
        invalidate_link_cache(old_code)
        if old_code != link.short_code:
            invalidate_link_cache(link.short_code)
    return link


def delete_link(link: Link):
    invalidate_link_cache(link.short_code)
    link.delete()


def create_admin_user(username: str, email: str, password: str) -> User:
    user = User.objects.create_user(username=username, email=email, password=password)
    user.is_staff = True
    user.save()
    return user
