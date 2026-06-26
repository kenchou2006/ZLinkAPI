from django.contrib.auth.models import User
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from ..permissions import IsStaff, IsSuperUser
from ..serializers import UserCreateSerializer, UserSerializer, UserUpdateSerializer


class UserViewSet(viewsets.ModelViewSet):
    """User management. List/create/toggle are superuser-only; the object-level
    rules from the legacy views are enforced in update/destroy.
    """

    queryset = User.objects.select_related('profile').all().order_by('-date_joined')

    def get_permissions(self):
        if self.action in ('list', 'create', 'toggle_active', 'stats'):
            return [IsSuperUser()]
        return [IsStaff()]

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        if self.action in ('update', 'partial_update'):
            return UserUpdateSerializer
        return UserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    def _assert_can_manage(self, target):
        """Only superusers may manage staff/superuser accounts."""
        if (target.is_superuser or target.is_staff) and not self.request.user.is_superuser:
            raise PermissionDenied("Only superusers can manage staff or superuser accounts.")

    def update(self, request, *args, **kwargs):
        target = self.get_object()
        self._assert_can_manage(target)
        # Only superusers may change the is_superuser flag, and never on self.
        if 'is_superuser' in request.data:
            if not request.user.is_superuser or target == request.user:
                raise PermissionDenied("You cannot change superuser privileges here.")
        serializer = self.get_serializer(target, data=request.data, partial=kwargs.pop('partial', False))
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data)

    def destroy(self, request, *args, **kwargs):
        target = self.get_object()
        if target == request.user:
            raise PermissionDenied("You cannot delete yourself.")
        self._assert_can_manage(target)
        target.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='toggle-active')
    def toggle_active(self, request, pk=None):
        target = self.get_object()
        if target == request.user:
            raise PermissionDenied("You cannot deactivate yourself.")
        if target.is_superuser:
            raise PermissionDenied("Superusers cannot be deactivated.")
        target.is_active = not target.is_active
        target.save()
        return Response(UserSerializer(target).data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        users = User.objects.all()
        return Response({
            'total': users.count(),
            'active': users.filter(is_active=True).count(),
            'superusers': users.filter(is_superuser=True).count(),
        })
