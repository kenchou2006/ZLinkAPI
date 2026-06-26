from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthzView(APIView):
    """Public health check endpoint."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses=OpenApiResponse(description='Service status'))
    def get(self, request):
        return Response({'status': 'ok'})
