from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from ..models import ApiKey
from ..permissions import IsStaff
from ..serializers import ApiKeySerializer


class ApiKeyViewSet(viewsets.ModelViewSet):
    """Manage API keys. Staff only, JWT only (API keys cannot manage keys)."""

    queryset = ApiKey.objects.all().order_by('-created_at')
    serializer_class = ApiKeySerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsStaff]
    http_method_names = ['get', 'post', 'patch', 'delete']

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw, key = ApiKey.generate()
        key.name = serializer.validated_data['name']
        key.expires_at = serializer.validated_data.get('expires_at')
        key.created_by = request.user
        key.save()

        data = ApiKeySerializer(key).data
        data['key'] = raw  # shown only once
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def expired(self, request):
        qs = self.get_queryset().filter(expires_at__isnull=False, expires_at__lte=timezone.now())
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, methods=['post'], url_path='purge-expired')
    def purge_expired(self, request):
        expired = self.get_queryset().filter(expires_at__isnull=False, expires_at__lte=timezone.now())
        count = expired.count()
        expired.delete()
        return Response({'deleted': count})
