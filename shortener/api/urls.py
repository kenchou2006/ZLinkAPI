from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .apikeys import ApiKeyViewSet
from .auth import LoginView, LogoutView, MeView
from .cache import CacheClearView, CacheKeysView
from .links import LinkViewSet
from .profile import ProfileView
from .users import UserViewSet
from .views import HealthzView

router = DefaultRouter()
router.register('links', LinkViewSet, basename='link')
router.register('users', UserViewSet, basename='user')
router.register('api-keys', ApiKeyViewSet, basename='apikey')

urlpatterns = [
    path('', include(router.urls)),

    path('profile/', ProfileView.as_view(), name='api_profile'),

    # Cache (Redis) management
    path('cache/keys/', CacheKeysView.as_view(), name='api_cache_keys'),
    path('cache/clear/', CacheClearView.as_view(), name='api_cache_clear'),

    path('healthz/', HealthzView.as_view(), name='api_healthz'),

    # Auth
    path('auth/login/', LoginView.as_view(), name='api_login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='api_token_refresh'),
    path('auth/logout/', LogoutView.as_view(), name='api_logout'),
    path('auth/me/', MeView.as_view(), name='api_me'),

    # OpenAPI schema / docs
    path('schema/', SpectacularAPIView.as_view(), name='api_schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api_schema'), name='api_docs'),
]
