from django.utils import timezone
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from ..authentication import ApiKeyAuthentication
from ..models import Link
from ..permissions import IsStaffOrApiKey
from ..serializers import LinkSerializer
from ..services import delete_link as service_delete_link
from ..services import purge_expired_links


class LinkViewSet(viewsets.ModelViewSet):
    """CRUD for short links. Accessible to staff (JWT) or a valid API key."""

    queryset = Link.objects.all().order_by('-created_at')
    serializer_class = LinkSerializer
    authentication_classes = [JWTAuthentication, ApiKeyAuthentication]
    permission_classes = [IsStaffOrApiKey]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['original_url', 'short_code']
    ordering_fields = ['created_at', 'short_code', 'id']
    ordering = ['-created_at']

    def perform_destroy(self, instance):
        # Use the service so cache is invalidated consistently.
        service_delete_link(instance)

    @action(detail=False, methods=['get'])
    def expired(self, request):
        qs = self.get_queryset().filter(expires_at__isnull=False, expires_at__lte=timezone.now())
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, methods=['post'], url_path='purge-expired')
    def purge_expired(self, request):
        return Response({'deleted': purge_expired_links()})

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        ids = request.data.get('ids')
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'ids must be a non-empty list.'}, status=400)
        links = list(self.get_queryset().filter(id__in=ids))
        for link in links:
            service_delete_link(link)
        return Response({'deleted': len(links)})
