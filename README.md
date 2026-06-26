# ZLink

A self-hostable URL shortener with a clean, JSON-first management API.

**ZLink** is the backend of the ZLink project — a Django REST Framework service
that handles everything around *managing* short links: authentication, link
CRUD, user management, API keys for external automation, and cache control.
It exposes a pure JSON API (no server-rendered pages) documented with OpenAPI.

> The actual click **redirects** are served by a separate, lightweight Go
> service ([ZLinkClient](../ZLinkClient)) for speed, and the admin UI is a
> standalone Angular app ([ZLinkFE](../ZLinkFE)). All three share one
> PostgreSQL database and one Redis cache.

## Features

- 🔗 **Short link CRUD** with custom aliases, reserved-word protection, and auto-generated codes
- ⏳ **Link expiry** — optional expiry time per link (or never-expiring); expired links stop redirecting and can be auto-purged
- 🔐 **JWT authentication** (access/refresh tokens, rotation + blacklist on logout)
- 👥 **User management** with staff / superuser roles and self-service profiles
- 🔑 **API keys** so external clients can manage links without a login — with optional expiry (or never-expiring), one-time secret display, and instant revocation
- ⚡ **Redis cache management** shared with the Go redirect service
- 📖 **OpenAPI 3 schema** with Swagger UI at `/api/docs/`
- 🛟 **Django admin** retained as an emergency backend

## Architecture

```
┌────────────────┐   REST/JSON (JWT or API key)   ┌────────────────────┐
│  ZLinkFE (SPA) │ ─────────────────────────────▶ │  ZLink  (this API) │
│  Angular admin │ ◀───────────────────────────── │  Django + DRF      │
└────────────────┘                                 └─────────┬──────────┘
                                                             │ ORM / cache
                                              ┌──────────────▼──────────────┐
                                              │   PostgreSQL  +  Redis       │
                                              └──────────────▲──────────────┘
                                                             │ reads
   end users ── GET /{code} ──────────────────▶  ┌──────────┴──────────┐
                                                  │  ZLinkClient (Go)   │
                                                  │  redirects + GA4    │
                                                  └─────────────────────┘
```

## Tech stack

Django 6 · Django REST Framework · SimpleJWT · drf-spectacular ·
django-cors-headers · PostgreSQL (SQLite for local dev) · Redis

## Requirements

- Python 3.11+ (developed on 3.13)
- Redis (optional but recommended — easy to run via Docker, see below)
- PostgreSQL for production (falls back to local SQLite when unconfigured)

## Quick start

```bash
cd ZLink

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.template .env                 # then edit it (at minimum set SECRET_KEY)

python manage.py migrate
python manage.py createsuperuser      # create your first admin
python manage.py runserver 8000
```

Then open:

- API base — `http://localhost:8000/api/`
- Swagger UI — `http://localhost:8000/api/docs/`
- Django admin — `http://localhost:8000/admin/`

### Run Redis with Docker

```bash
docker run -d --name zlink-redis -p 6379:6379 redis:7-alpine
```

Set `REDIS_URL=redis://localhost:6379` in `.env`. Redis is optional — if it is
unreachable the API still works (cache operations are skipped gracefully).

> **Tip:** the database is chosen at runtime by the `POSTGRES_*` env vars. Always
> run `createsuperuser` in a shell with the *same* env as the server, or the
> account may land in a different database (a common "can't log in" cause).

## Configuration

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | **Required.** Django secret key |
| `DEBUG` | `True` for development (uses SQLite, skips auto-superuser) |
| `REDIS_URL` | Redis connection, e.g. `redis://localhost:6379` |
| `CACHE_TTL` | Cache seconds; `None` = persistent |
| `SHORT_LINK_BASE_URL` | Public redirect domain (the Go service), e.g. `https://zli.nk` — used to build clickable short links in the admin UI |
| `FRONTEND_URL` | ZLinkFE domain(s) allowed via CORS — bare domains, comma-separated, e.g. `example.com, test.com` (each expands to https/http; defaults to the Angular dev server) |
| `POSTGRES_*` | Set to use PostgreSQL (otherwise SQLite) |
| `DB_SSLMODE` | PostgreSQL SSL mode, default `require`; use `disable` for local Docker |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | Token lifetimes (default 15 min / 7 days) |

## API overview

| Method | Path | Access |
|--------|------|--------|
| POST | `/api/auth/login/` · `refresh/` · `logout/`, GET `me/` | public / authenticated |
| CRUD | `/api/links/` | staff (JWT) **or** a valid API key |
| CRUD | `/api/api-keys/` | staff (JWT only) |
| GET/PATCH | `/api/profile/` | authenticated |
| CRUD | `/api/users/`, `/api/users/{id}/toggle-active/`, `/api/users/stats/` | superuser (some staff) |
| GET/DELETE | `/api/cache/keys/`, POST `/api/cache/clear/` | superuser |
| GET/PATCH/DELETE | `/api/auth/passkeys/` | authenticated (own passkeys only) |
| POST | `/api/auth/passkeys/register/options/` · `register/verify/` | authenticated |
| POST | `/api/auth/passkeys/login/options/` · `login/verify/` | public |

Full schema at `/api/docs/`.

### Passkeys (WebAuthn)

Users can register one or more passkeys (from the **Profile** page in the
admin UI) as a passwordless login method, alongside the regular
username/password login:

1. `register/options/` returns a signed, short-lived challenge (no
   server-side session/cache needed between steps).
2. The browser's WebAuthn API (`navigator.credentials.create()`) produces an
   attestation, which `register/verify/` checks before saving the credential.
3. Logging in works the same way without a username — `login/options/` issues
   a discoverable-credential challenge, the OS passkey picker shows every
   passkey registered for this site, and `login/verify/` looks up the chosen
   credential's owner and issues the same JWT pair as password login.

`WEBAUTHN_RP_ID` must match the bare domain the frontend is served from (not
the API's domain) — see `.env.template`.

### Managing links with an API key

1. Create a key on the **API Keys** page of the admin UI (set an expiry or make it never-expire).
2. The plaintext key is shown **once** (only its SHA-256 hash is stored).
3. Call the API with the `X-API-Key` header:

```bash
curl -X POST https://your-domain/api/links/ \
  -H "X-API-Key: zlk_xxxxxxxx..." \
  -H 'Content-Type: application/json' \
  -d '{"original_url":"https://example.com","short_code":"promo"}'
```

API keys can manage **links only** — never users, cache, or other keys.
Expired or revoked keys return `401`.

## Link expiry & auto-deletion

Each link can have an optional `expires_at` (leave it empty for a permanent
link). Once a link is past its expiry:

- the **redirect service (Go) returns 404** for it — even if it was cached
  (the stale cache entry is dropped on access);
- it still appears in the admin UI (flagged as *Expired*) so you can review or
  delete it.

To physically remove expired items, you have two options:

**1. From the admin UI (no scheduler needed).** The **Expired** page lists all
expired links and API keys and offers a one-click *Clear all* for each. Backed by:

| Method | Path |
|--------|------|
| GET | `/api/links/expired/` · `/api/api-keys/expired/` |
| POST | `/api/links/purge-expired/` · `/api/api-keys/purge-expired/` |

**2. Management command** (for scripted/scheduled cleanup):

```bash
python manage.py delete_expired_links            # delete expired links
python manage.py delete_expired_links --dry-run  # preview without deleting
```

Run it on a schedule with whatever your host provides, e.g. a daily cron job:

```cron
0 3 * * *  cd /path/to/ZLink && /path/to/.venv/bin/python manage.py delete_expired_links
```

## Deployment

`vercel.json` deploys via `zlink/wsgi.py`, running migrations and
`collectstatic` (Django admin assets only) through `build_files.sh`. For
production set `DEBUG=False`, `POSTGRES_*`, `REDIS_URL`,
`CORS_ALLOWED_ORIGINS`, and a strong `SECRET_KEY`.

## License

MIT — see [LICENSE](LICENSE).
