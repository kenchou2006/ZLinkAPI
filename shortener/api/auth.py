from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from ..serializers import CustomTokenObtainPairSerializer, UserSerializer


class LoginView(TokenObtainPairView):
    """POST username/password -> access + refresh tokens (and user info)."""

    serializer_class = CustomTokenObtainPairSerializer


class LogoutView(APIView):
    """Blacklist a refresh token to log the user out."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=OpenApiResponse(description='Logged out'))
    def post(self, request):
        refresh = request.data.get('refresh')
        if not refresh:
            return Response(
                {'detail': 'refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            return Response(
                {'detail': 'Invalid or expired refresh token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(APIView):
    """Return the currently authenticated user."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=UserSerializer)
    def get(self, request):
        return Response(UserSerializer(request.user).data)
