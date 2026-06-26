from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta
from io import StringIO
from rest_framework import status
from rest_framework.test import APITestCase

from .models import ApiKey, Link


class AuthTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('admin', 'a@a.com', 'pass12345')
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()

    def test_login_returns_tokens_and_user(self):
        res = self.client.post('/api/auth/login/', {'username': 'admin', 'password': 'pass12345'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('access', res.data)
        self.assertIn('refresh', res.data)
        self.assertEqual(res.data['user']['username'], 'admin')

    def test_login_wrong_password(self):
        res = self.client.post('/api/auth/login/', {'username': 'admin', 'password': 'nope'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_requires_auth(self):
        self.assertEqual(self.client.get('/api/auth/me/').status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_blacklists_refresh(self):
        login = self.client.post('/api/auth/login/', {'username': 'admin', 'password': 'pass12345'}, format='json')
        refresh = login.data['refresh']
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        out = self.client.post('/api/auth/logout/', {'refresh': refresh}, format='json')
        self.assertEqual(out.status_code, status.HTTP_205_RESET_CONTENT)
        # reusing the blacklisted refresh must fail
        again = self.client.post('/api/auth/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(again.status_code, status.HTTP_401_UNAUTHORIZED)


class LinkApiTests(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', 's@s.com', 'pass12345')
        self.staff.is_staff = True
        self.staff.save()
        self.plain = User.objects.create_user('plain', 'p@p.com', 'pass12345')

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get('/api/links/').status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_staff_forbidden(self):
        self.auth(self.plain)
        self.assertEqual(self.client.get('/api/links/').status_code, status.HTTP_403_FORBIDDEN)

    def test_create_with_alias(self):
        self.auth(self.staff)
        res = self.client.post('/api/links/', {'original_url': 'https://example.com', 'short_code': 'promo'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['short_code'], 'promo')

    def test_create_autogenerates_code(self):
        self.auth(self.staff)
        res = self.client.post('/api/links/', {'original_url': 'https://example.com'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data['short_code'])

    def test_reserved_alias_rejected(self):
        self.auth(self.staff)
        res = self.client.post('/api/links/', {'original_url': 'https://x.com', 'short_code': 'admin'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_alias_rejected(self):
        self.auth(self.staff)
        Link.objects.create(original_url='https://x.com', short_code='dup')
        res = self.client.post('/api/links/', {'original_url': 'https://y.com', 'short_code': 'dup'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_url_rejected(self):
        self.auth(self.staff)
        res = self.client.post('/api/links/', {'original_url': 'not-a-url'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_and_delete(self):
        self.auth(self.staff)
        link = Link.objects.create(original_url='https://old.com', short_code='edit')
        upd = self.client.patch(f'/api/links/{link.id}/', {'original_url': 'https://new.com'}, format='json')
        self.assertEqual(upd.status_code, status.HTTP_200_OK)
        self.assertEqual(upd.data['original_url'], 'https://new.com')
        delete = self.client.delete(f'/api/links/{link.id}/')
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Link.objects.filter(id=link.id).exists())

    def test_create_with_expiry(self):
        self.auth(self.staff)
        expires = (timezone.now() + timedelta(days=7)).isoformat()
        res = self.client.post(
            '/api/links/',
            {'original_url': 'https://example.com', 'short_code': 'temp', 'expires_at': expires},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(res.data['expires_at'])
        self.assertFalse(res.data['is_expired'])

    def test_create_without_expiry_is_unlimited(self):
        self.auth(self.staff)
        res = self.client.post('/api/links/', {'original_url': 'https://example.com'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(res.data['expires_at'])

    def test_is_expired_flag(self):
        self.auth(self.staff)
        link = Link.objects.create(
            original_url='https://x.com', short_code='gone',
            expires_at=timezone.now() - timedelta(hours=1),
        )
        res = self.client.get(f'/api/links/{link.id}/')
        self.assertTrue(res.data['is_expired'])


class ExpiredLinkCleanupTests(APITestCase):
    def test_command_deletes_only_expired(self):
        Link.objects.create(original_url='https://a.com', short_code='keep')  # no expiry
        Link.objects.create(
            original_url='https://b.com', short_code='future',
            expires_at=timezone.now() + timedelta(days=1),
        )
        Link.objects.create(
            original_url='https://c.com', short_code='past',
            expires_at=timezone.now() - timedelta(days=1),
        )
        call_command('delete_expired_links', stdout=StringIO())
        codes = set(Link.objects.values_list('short_code', flat=True))
        self.assertEqual(codes, {'keep', 'future'})

    def test_dry_run_deletes_nothing(self):
        Link.objects.create(
            original_url='https://c.com', short_code='past',
            expires_at=timezone.now() - timedelta(days=1),
        )
        call_command('delete_expired_links', '--dry-run', stdout=StringIO())
        self.assertEqual(Link.objects.count(), 1)


class ExpiredReviewEndpointTests(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', 's@s.com', 'pass12345')
        self.staff.is_staff = True
        self.staff.save()
        self.client.force_authenticate(user=self.staff)
        Link.objects.create(original_url='https://a.com', short_code='keep')
        Link.objects.create(
            original_url='https://c.com', short_code='past',
            expires_at=timezone.now() - timedelta(days=1),
        )

    def test_links_expired_lists_only_expired(self):
        res = self.client.get('/api/links/expired/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([l['short_code'] for l in res.data], ['past'])

    def test_links_purge_expired(self):
        res = self.client.post('/api/links/purge-expired/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['deleted'], 1)
        self.assertEqual(set(Link.objects.values_list('short_code', flat=True)), {'keep'})

    def test_links_bulk_delete(self):
        a = Link.objects.create(original_url='https://1.com', short_code='b1')
        b = Link.objects.create(original_url='https://2.com', short_code='b2')
        res = self.client.post('/api/links/bulk-delete/', {'ids': [a.id, b.id]}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['deleted'], 2)
        self.assertFalse(Link.objects.filter(id__in=[a.id, b.id]).exists())

    def test_links_bulk_delete_requires_ids(self):
        res = self.client.post('/api/links/bulk-delete/', {'ids': []}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_apikeys_expired_and_purge(self):
        ApiKey.generate()  # not saved
        live_raw, live = ApiKey.generate()
        live.name = 'live'
        live.created_by = self.staff
        live.save()
        exp_raw, exp = ApiKey.generate()
        exp.name = 'exp'
        exp.created_by = self.staff
        exp.expires_at = timezone.now() - timedelta(days=1)
        exp.save()

        listed = self.client.get('/api/api-keys/expired/')
        self.assertEqual([k['name'] for k in listed.data], ['exp'])

        purged = self.client.post('/api/api-keys/purge-expired/')
        self.assertEqual(purged.data['deleted'], 1)
        self.assertEqual(set(ApiKey.objects.values_list('name', flat=True)), {'live'})


class ApiKeyTests(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', 's@s.com', 'pass12345')
        self.staff.is_staff = True
        self.staff.save()

    def _create_key(self, **extra):
        self.client.force_authenticate(user=self.staff)
        res = self.client.post('/api/api-keys/', {'name': 'k', **extra}, format='json')
        self.client.force_authenticate(user=None)
        return res

    def test_create_returns_plaintext_once(self):
        res = self._create_key()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn('key', res.data)
        self.assertTrue(res.data['key'].startswith('zlk_'))

    def test_key_can_manage_links(self):
        key = self._create_key().data['key']
        self.client.credentials(HTTP_X_API_KEY=key)
        res = self.client.post('/api/links/', {'original_url': 'https://example.com'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_key_cannot_manage_users_or_keys(self):
        key = self._create_key().data['key']
        self.client.credentials(HTTP_X_API_KEY=key)
        self.assertEqual(self.client.get('/api/users/').status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.client.get('/api/api-keys/').status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_key_rejected(self):
        self.client.credentials(HTTP_X_API_KEY='zlk_invalid')
        self.assertEqual(self.client.get('/api/links/').status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_key_rejected(self):
        key = self._create_key(expires_at=(timezone.now() - timedelta(days=1)).isoformat()).data['key']
        self.client.credentials(HTTP_X_API_KEY=key)
        self.assertEqual(self.client.get('/api/links/').status_code, status.HTTP_401_UNAUTHORIZED)

    def test_revoked_key_rejected(self):
        res = self._create_key()
        key, kid = res.data['key'], res.data['id']
        self.client.force_authenticate(user=self.staff)
        self.client.patch(f'/api/api-keys/{kid}/', {'is_active': False}, format='json')
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_X_API_KEY=key)
        self.assertEqual(self.client.get('/api/links/').status_code, status.HTTP_401_UNAUTHORIZED)


class UserApiTests(APITestCase):
    def setUp(self):
        self.super = User.objects.create_superuser('root', 'r@r.com', 'pass12345')
        self.staff = User.objects.create_user('staff', 's@s.com', 'pass12345')
        self.staff.is_staff = True
        self.staff.save()

    def test_staff_cannot_list_users(self):
        self.client.force_authenticate(user=self.staff)
        self.assertEqual(self.client.get('/api/users/').status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_lists_and_stats(self):
        self.client.force_authenticate(user=self.super)
        self.assertEqual(self.client.get('/api/users/').status_code, status.HTTP_200_OK)
        stats = self.client.get('/api/users/stats/')
        self.assertEqual(stats.status_code, status.HTTP_200_OK)
        self.assertIn('superusers', stats.data)

    def test_create_user_is_staff(self):
        self.client.force_authenticate(user=self.super)
        res = self.client.post('/api/users/', {
            'username': 'new', 'password': 'pass12345', 'confirm_password': 'pass12345',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.get(username='new').is_staff)

    def test_password_mismatch_rejected(self):
        self.client.force_authenticate(user=self.super)
        res = self.client.post('/api/users/', {
            'username': 'x', 'password': 'a', 'confirm_password': 'b',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_delete_self(self):
        self.client.force_authenticate(user=self.super)
        res = self.client.delete(f'/api/users/{self.super.id}/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class ProfileTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('me', 'm@m.com', 'pass12345')

    def test_get_profile(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get('/api/profile/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['username'], 'me')

    def test_change_password_requires_correct_current(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.patch('/api/profile/', {
            'current_password': 'wrong', 'new_password': 'newpass123', 'confirm_password': 'newpass123',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_avatar(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.patch('/api/profile/', {'avatar_url': 'https://img.example.com/a.png'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['user']['avatar_url'], 'https://img.example.com/a.png')
