from django.contrib.auth.models import User
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import ApiKey, Link
from .services import update_link as service_update_link
from .utils import normalize_short_code, validate_short_code


class UserSerializer(serializers.ModelSerializer):
    """Read-only representation of the authenticated user."""

    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email',
            'is_staff', 'is_superuser', 'is_active',
            'date_joined', 'avatar_url',
        )
        read_only_fields = fields

    def get_avatar_url(self, obj) -> str | None:
        profile = getattr(obj, 'profile', None)
        return profile.avatar_url if profile else None


class LinkSerializer(serializers.ModelSerializer):
    """Serializer for Link CRUD.

    `short_code` doubles as the custom alias on write: leave it blank to let
    the model auto-generate one. Validation mirrors the old LinkCreateForm /
    LinkUpdateForm logic (reserved words, conflicts, uniqueness).
    """

    short_code = serializers.CharField(max_length=15, required=False, allow_blank=True)
    short_url = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Link
        fields = ('id', 'original_url', 'short_code', 'short_url', 'expires_at', 'is_expired', 'created_at')
        read_only_fields = ('id', 'is_expired', 'created_at')

    def get_short_url(self, obj) -> str:
        # Prefer the configured public redirect domain (the Go service) so the
        # link is clickable from anywhere; fall back to the request host.
        from django.conf import settings
        base = getattr(settings, 'SHORT_LINK_BASE_URL', '')
        if base:
            return f"{base}/{obj.short_code}"
        request = self.context.get('request')
        if request is None:
            return obj.short_code
        return f"{request.scheme}://{request.get_host()}/{obj.short_code}"

    def validate_short_code(self, value):
        alias = (value or '').strip()
        if not alias:
            # Blank on create -> auto-generate; on update -> keep existing.
            return ''
        # Allow keeping the same alias unchanged on update.
        if self.instance and alias == self.instance.short_code:
            return normalize_short_code(alias)
        exclude_id = self.instance.id if self.instance else None
        error = validate_short_code(alias, exclude_link_id=exclude_id)
        if error:
            raise serializers.ValidationError(error)
        return normalize_short_code(alias)

    def create(self, validated_data):
        short_code = validated_data.pop('short_code', '')
        if short_code:
            return Link.objects.create(short_code=short_code, **validated_data)
        # No alias: rely on the model's generate_short_code default.
        return Link.objects.create(**validated_data)

    def update(self, instance, validated_data):
        short_code = validated_data.pop('short_code', '')
        new_url = validated_data.get('original_url')
        new_code = short_code or None
        if 'expires_at' in validated_data:
            instance.expires_at = validated_data['expires_at']
        # services.update_link handles the old-code cache invalidation that the
        # post_save signal (which only sees the new code) would otherwise miss.
        return service_update_link(instance, new_url, new_code)


class UserCreateSerializer(serializers.ModelSerializer):
    """Create a staff/admin user (mirrors AdminUserCreateForm)."""

    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    confirm_password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'confirm_password')

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already exists.")
        return value

    def validate_email(self, value):
        value = (value or '').strip()
        if value and User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already exists.")
        return value

    def validate(self, attrs):
        if attrs.get('password') != attrs.get('confirm_password'):
            raise serializers.ValidationError({'confirm_password': "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        from .services import create_admin_user
        return create_admin_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
        )


class UserUpdateSerializer(serializers.ModelSerializer):
    """Update a user (mirrors AdminUserUpdateForm). Caller-level permission
    rules (who may edit whom / change privilege flags) are enforced in the view.
    """

    password = serializers.CharField(write_only=True, required=False, allow_blank=True,
                                     style={'input_type': 'password'})
    confirm_password = serializers.CharField(write_only=True, required=False, allow_blank=True,
                                             style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'confirm_password', 'is_superuser')

    def validate_username(self, value):
        qs = User.objects.filter(username=value)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError("Username already exists.")
        return value

    def validate_email(self, value):
        value = (value or '').strip()
        if value:
            qs = User.objects.filter(email=value)
            if self.instance:
                qs = qs.exclude(id=self.instance.id)
            if qs.exists():
                raise serializers.ValidationError("Email already exists.")
        return value

    def validate(self, attrs):
        pwd = attrs.get('password')
        confirm = attrs.get('confirm_password')
        if pwd or confirm:
            if pwd != confirm:
                raise serializers.ValidationError({'confirm_password': "Passwords do not match."})
        return attrs

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        validated_data.pop('confirm_password', None)
        for field in ('username', 'email', 'is_superuser'):
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class ProfileSerializer(serializers.Serializer):
    """Self-service profile update (mirrors ProfileForm)."""

    username = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    avatar_url = serializers.URLField(required=False, allow_blank=True)
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True,
                                             style={'input_type': 'password'})
    new_password = serializers.CharField(write_only=True, required=False, allow_blank=True,
                                         style={'input_type': 'password'})
    confirm_password = serializers.CharField(write_only=True, required=False, allow_blank=True,
                                             style={'input_type': 'password'})

    def validate_username(self, value):
        user = self.context['request'].user
        if value and value != user.username and \
                User.objects.filter(username=value).exclude(id=user.id).exists():
            raise serializers.ValidationError("Username already exists.")
        return value

    def validate_email(self, value):
        user = self.context['request'].user
        value = (value or '').strip()
        if value and value != user.email and \
                User.objects.filter(email=value).exclude(id=user.id).exists():
            raise serializers.ValidationError("Email already exists.")
        return value

    def validate(self, attrs):
        user = self.context['request'].user
        new_pwd = attrs.get('new_password')
        confirm = attrs.get('confirm_password')
        current = attrs.get('current_password')
        if new_pwd or confirm:
            if new_pwd != confirm:
                raise serializers.ValidationError({'confirm_password': "New passwords do not match."})
            if not current:
                raise serializers.ValidationError({'current_password': "Current password is required to change password."})
            if not user.check_password(current):
                raise serializers.ValidationError({'current_password': "Current password is incorrect."})
        return attrs

    def save(self):
        user = self.context['request'].user
        data = self.validated_data
        if data.get('username'):
            user.username = data['username']
        if 'email' in data:
            user.email = data['email']
        if 'avatar_url' in data:
            profile = getattr(user, 'profile', None)
            if profile is None:
                from .models import Profile
                profile = Profile.objects.create(user=user)
            profile.avatar_url = data['avatar_url']
            profile.save()
        password_changed = False
        if data.get('new_password'):
            user.set_password(data['new_password'])
            password_changed = True
        user.save()
        return user, password_changed


class ApiKeySerializer(serializers.ModelSerializer):
    """API key management. The plaintext key is only returned once on create."""

    class Meta:
        model = ApiKey
        fields = ('id', 'name', 'prefix', 'expires_at', 'last_used_at', 'is_active', 'created_at')
        read_only_fields = ('id', 'prefix', 'last_used_at', 'created_at')


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login serializer that embeds basic user info alongside the tokens."""

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserSerializer(self.user).data
        return data
