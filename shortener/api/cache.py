import logging

from django_redis import get_redis_connection
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..permissions import IsSuperUser

logger = logging.getLogger(__name__)

CACHE_MATCH = "*shortener:url:*"


class CacheKeysView(APIView):
    """List / delete cached short-link keys in Redis. Superuser only."""

    permission_classes = [IsSuperUser]

    @extend_schema(responses=OpenApiResponse(description='List of cache keys'))
    def get(self, request):
        keys_data = []
        try:
            con = get_redis_connection("default")
            for k in con.scan_iter(match=CACHE_MATCH):
                decoded = k.decode('utf-8') if isinstance(k, bytes) else k
                ttl = con.ttl(k)
                k_type = con.type(k)
                k_type = k_type.decode('utf-8') if isinstance(k_type, bytes) else k_type
                display = decoded.split('url:')[-1] if 'url:' in decoded else decoded
                keys_data.append({'key': decoded, 'display_key': display, 'ttl': ttl, 'type': k_type})
        except Exception as e:
            logger.warning("Redis unavailable in CacheKeysView: %s", e)
            return Response({'keys': [], 'error': str(e)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({'keys': keys_data, 'error': None})

    @extend_schema(request=None, responses=OpenApiResponse(description='Delete result'))
    def delete(self, request):
        key = request.data.get('key')
        if not key:
            return Response({'detail': 'key is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            con = get_redis_connection("default")
            deleted = con.delete(key)
        except Exception as e:
            logger.warning("Redis delete failed: %s", e)
            return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({'deleted': bool(deleted), 'key': key})


class CacheClearView(APIView):
    """Clear all shortener:url:* cache keys. Superuser only."""

    permission_classes = [IsSuperUser]

    @extend_schema(request=None, responses=OpenApiResponse(description='Clear result'))
    def post(self, request):
        try:
            con = get_redis_connection("default")
            keys = list(con.scan_iter(match=CACHE_MATCH))
            count = con.delete(*keys) if keys else 0
        except Exception as e:
            logger.warning("Redis clear failed: %s", e)
            return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({'cleared': count})
