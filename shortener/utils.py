from .models import Link

# Reserved aliases that must never be used as short codes.
# Includes the API/admin namespaces served by Django and legacy management
# routes, so a short code can never shadow a real route. Redirect resolution
# itself is served by the Go client (ZLinkClient); Django no longer owns it.
RESERVED_ALIASES = {
    'api', 'admin', 'static', 'healthz',
    'links', 'login', 'logout', 'create', 'delete', 'settings', 'cache', 'users',
}
RESERVED_PREFIXES = (
    'api/', 'admin/', 'static/',
    'settings/', 'delete/', 'users/', 'cache/', 'links/',
)


def normalize_short_code(short_code: str) -> str:
    """Normalize special aliases like root."""
    if short_code in {'/', '@root'}:
        return '@root'
    return short_code


def validate_short_code(short_code: str, exclude_link_id=None) -> str | None:
    """Return error message if short code is invalid; None if ok."""
    if not short_code:
        return "Alias is required."

    normalized = normalize_short_code(short_code)

    if normalized.lower() in RESERVED_ALIASES:
        return f"Alias '{normalized}' is reserved and cannot be used."

    for prefix in RESERVED_PREFIXES:
        if normalized.lower().startswith(prefix):
            return f"Alias '{normalized}' is reserved and cannot be used."

    qs = Link.objects.filter(short_code=normalized)
    if exclude_link_id:
        qs = qs.exclude(id=exclude_link_id)
    if qs.exists():
        return f"Alias '{normalized}' is already taken."

    return None


def link_cache_key(short_code):
    return f"shortener:url:{short_code}"
