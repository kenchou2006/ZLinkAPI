import json

import webauthn
from django.conf import settings
from django.core import signing
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ..models import Passkey
from ..serializers import PasskeySerializer, UserSerializer

# Registration/authentication challenges are signed (not stored server-side),
# so the API stays stateless between the options and verify calls.
SIGNING_SALT = 'shortener.passkey'
CHALLENGE_MAX_AGE = 300  # seconds


def _sign_challenge(challenge: bytes, *, user_id: int | None = None) -> str:
    return signing.dumps(
        {'challenge': bytes_to_base64url(challenge), 'user_id': user_id},
        salt=SIGNING_SALT,
    )


def _unsign_state(state: str) -> dict:
    return signing.loads(state, salt=SIGNING_SALT, max_age=CHALLENGE_MAX_AGE)


class PasskeyRegisterOptionsView(APIView):
    """Generate WebAuthn registration options for the current user."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=OpenApiResponse(description='Registration options'))
    def post(self, request):
        existing = Passkey.objects.filter(user=request.user).values_list('credential_id', flat=True)
        options = webauthn.generate_registration_options(
            rp_id=settings.WEBAUTHN_RP_ID,
            rp_name=settings.WEBAUTHN_RP_NAME,
            user_id=str(request.user.id).encode(),
            user_name=request.user.username,
            user_display_name=request.user.username,
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=webauthn.base64url_to_bytes(cid)) for cid in existing
            ],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )
        return Response({
            'options': json.loads(webauthn.options_to_json(options)),
            'state': _sign_challenge(options.challenge, user_id=request.user.id),
        })


class PasskeyRegisterVerifyView(APIView):
    """Verify a registration response and save the new passkey."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=PasskeySerializer)
    def post(self, request):
        state = request.data.get('state')
        credential = request.data.get('credential')
        if not state or not credential:
            return Response(
                {'detail': 'state and credential are required.'}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            payload = _unsign_state(state)
        except signing.BadSignature:
            return Response(
                {'detail': 'Invalid or expired registration state.'}, status=status.HTTP_400_BAD_REQUEST
            )

        if payload.get('user_id') != request.user.id:
            return Response({'detail': 'Invalid registration state.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            verification = webauthn.verify_registration_response(
                credential=json.dumps(credential),
                expected_challenge=webauthn.base64url_to_bytes(payload['challenge']),
                expected_rp_id=settings.WEBAUTHN_RP_ID,
                expected_origin=settings.WEBAUTHN_ORIGINS,
            )
        except InvalidRegistrationResponse:
            return Response(
                {'detail': 'Could not verify passkey registration.'}, status=status.HTTP_400_BAD_REQUEST
            )

        aaguid = verification.aaguid
        passkey = Passkey.objects.create(
            user=request.user,
            name=(request.data.get('name') or '').strip()[:100],
            credential_id=bytes_to_base64url(verification.credential_id),
            public_key=bytes_to_base64url(verification.credential_public_key),
            sign_count=verification.sign_count,
            transports=(credential.get('response') or {}).get('transports') or [],
            # All-zero AAGUID means the authenticator didn't identify itself.
            aaguid='' if aaguid == '00000000-0000-0000-0000-000000000000' else aaguid,
        )
        return Response(PasskeySerializer(passkey).data, status=status.HTTP_201_CREATED)


class PasskeyLoginOptionsView(APIView):
    """Generate WebAuthn authentication options for a passwordless (discoverable) login.

    No username is required up front: the browser's passkey picker surfaces
    every discoverable credential registered for this RP, and the verify step
    below looks up the matching user from whichever credential was chosen.
    """

    permission_classes = [AllowAny]

    @extend_schema(request=None, responses=OpenApiResponse(description='Authentication options'))
    def post(self, request):
        options = webauthn.generate_authentication_options(
            rp_id=settings.WEBAUTHN_RP_ID,
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        return Response({
            'options': json.loads(webauthn.options_to_json(options)),
            'state': _sign_challenge(options.challenge),
        })


class PasskeyLoginVerifyView(APIView):
    """Verify an authentication response and issue JWT tokens, like password login."""

    permission_classes = [AllowAny]

    @extend_schema(request=None, responses=OpenApiResponse(description='access/refresh tokens + user'))
    def post(self, request):
        state = request.data.get('state')
        credential = request.data.get('credential')
        if not state or not credential:
            return Response(
                {'detail': 'state and credential are required.'}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            payload = _unsign_state(state)
        except signing.BadSignature:
            return Response(
                {'detail': 'Invalid or expired login state.'}, status=status.HTTP_400_BAD_REQUEST
            )

        credential_id = credential.get('id')
        try:
            passkey = Passkey.objects.select_related('user').get(credential_id=credential_id)
        except Passkey.DoesNotExist:
            return Response({'detail': 'Passkey not recognized.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            verification = webauthn.verify_authentication_response(
                credential=json.dumps(credential),
                expected_challenge=webauthn.base64url_to_bytes(payload['challenge']),
                expected_rp_id=settings.WEBAUTHN_RP_ID,
                expected_origin=settings.WEBAUTHN_ORIGINS,
                credential_public_key=webauthn.base64url_to_bytes(passkey.public_key),
                credential_current_sign_count=passkey.sign_count,
            )
        except InvalidAuthenticationResponse:
            return Response({'detail': 'Could not verify passkey.'}, status=status.HTTP_400_BAD_REQUEST)

        passkey.sign_count = verification.new_sign_count
        passkey.last_used_at = timezone.now()
        passkey.save(update_fields=['sign_count', 'last_used_at'])

        refresh = RefreshToken.for_user(passkey.user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(passkey.user).data,
        })


class PasskeyViewSet(
    mixins.ListModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """List, rename, or revoke the current user's own passkeys."""

    serializer_class = PasskeySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Passkey.objects.filter(user=self.request.user).order_by('-created_at')

    def perform_destroy(self, instance):
        user = instance.user
        super().perform_destroy(instance)
        # Removing the last passkey while password login is disabled would
        # lock the user out entirely — re-enable it as a safety net.
        profile = getattr(user, 'profile', None)
        if profile and profile.password_login_disabled and not user.passkeys.exists():
            profile.password_login_disabled = False
            profile.save(update_fields=['password_login_disabled'])
