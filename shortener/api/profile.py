from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers import ProfileSerializer, UserSerializer


class ProfileView(APIView):
    """Self-service profile: any authenticated user can view/update their own."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=UserSerializer)
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @extend_schema(request=ProfileSerializer, responses=UserSerializer)
    def patch(self, request):
        serializer = ProfileSerializer(data=request.data, context={'request': request}, partial=True)
        serializer.is_valid(raise_exception=True)
        user, password_changed = serializer.save()
        return Response({
            'user': UserSerializer(user).data,
            'password_changed': password_changed,
        })
