# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Easy Painter is a text-to-image generation app with user authentication. Users submit prompts via the frontend; the backend atomically creates the job, billing reservation, credit transaction, and transactional outbox event. A dispatcher publishes the Celery task, the worker calls a private upstream image API and stores the result in MinIO, and the frontend polls for completion.

## Tech Stack

- **Frontend**: Vue 3 + Vite + TypeScript + vue-router
- **Backend**: FastAPI + SQLAlchemy + Celery + Redis + PostgreSQL + MinIO
- **Auth**: JWT (bcrypt password hashing, PyJWT tokens)
- **Python tooling**: `uv` (dependency management), `pytest` (testing)
- **Infra**: Docker Compose (Flyway migrate, nginx, api, dispatcher, worker, redis, postgres, minio, minio-init)

## Common Commands

```bash
# Start infrastructure (postgres, redis, minio, worker) — runs in foreground, Ctrl+C to stop
make deps

# Start backend API server (auto-reload on port 8000)
make backend

# Start frontend dev server (port 5173, proxies /api → localhost:8000)
make frontend

# Production deploy (builds images, starts all services)
make deploy

# Run backend tests
cd backend && uv run pytest

# Run a single test file
cd backend && uv run pytest tests/test_reference_images.py

# Type-check frontend
cd frontend && npx vue-tsc --noEmit

# Synchronize and validate a semantic version
python3 scripts/version.py set vX.Y.Z
python3 scripts/version.py check vX.Y.Z

# Preview the GitHub Release body sourced from CHANGELOG.md
python3 scripts/version.py notes vX.Y.Z
```

## Architecture

### Request Flow

1. Frontend submits `POST /api/v1/jobs` with prompt, model, optional staged reference image, JWT, and a stable `Idempotency-Key`
2. API atomically creates `GenerationJob`, `JobCharge`, the negative credit transaction, and an `OutboxEvent`; the balance update is conditional and cannot go below zero
3. The dispatcher publishes due outbox events to Celery and maintains the heartbeat used by readiness checks
4. A worker conditionally claims the queued job, calls the configured upstream, and uploads a successful result to MinIO
5. Success settles the reserved charge; final failure or watchdog timeout uses the same idempotent path to mark the job failed and refund it in full
6. Frontend polls `GET /api/v1/jobs/{job_id}` until a final state and refreshes balance and billing status

### Auth System

- Public registration verifies email through SMTP; login accepts username or email; password reset uses a one-time email code stored as a Redis HMAC digest
- Existing signed-in users without email can bind one through `POST /users/me/email/code` + `PUT /users/me/email`; a bound email cannot be self-replaced, while admin can still update it directly
- Email code sending uses a Redis atomic 60-second cooldown plus short-window and daily limits across email, IP, and (for authenticated binding) user ID; binding codes are scoped to the current user ID
- Users can also be created by admin or auto-created from `DEFAULT_USERNAME`/`DEFAULT_PASSWORD`/optional `DEFAULT_EMAIL` on first startup
- JWT tokens stored in `localStorage`, sent as `Authorization: Bearer <token>` header
- Admin access via secret key (`ADMIN_SECRET_KEY` env var), produces a separate JWT with `role=admin` claim
- Frontend uses vue-router with routes: `/` (home), `/login`, `/gallery/:username` (public gallery), `/admin`

### Gallery Logic

- Logged-in users see only their own succeeded jobs
- Anonymous visitors see explicitly published succeeded jobs from users with `is_public=True` plus legacy anonymous jobs (`user_id IS NULL`)
- Public user gallery accessible to anonymous and logged-in visitors at `/gallery/{username}`; only jobs explicitly published with `is_public=True` are included

### Announcement Logic

- `GET /announcements` returns enabled plain-text banners filtered by audience: `all`, `authenticated`, or `unbound_email`
- Admin CRUD lives under `/admin/announcements`; notifications are not seeded at startup
- The frontend banner reloads when login state or the current user's email changes, so a successful email binding removes `unbound_email` notices immediately

### Version and Release Logic

- Root `VERSION` is the canonical current version; frontend/backend manifests store the same value without the `v` prefix
- Root `CHANGELOG.md` is the only release-notes source and uses `## vX.Y.Z - YYYY-MM-DD` plus `+ [type] content` entries
- Vite embeds the current version and parsed changelog at build time; the header version dialog checks the latest stable GitHub Release only when opened
- GitHub failures never block the bundled release history, and the UI never downloads or installs updates
- Pushing a semantic-version tag runs `scripts/version.py check` and creates the GitHub Release from that changelog section

### Backend Structure (`backend/app/`)

- `api/routes.py` — Job endpoints (meta, idempotent creation, jobs CRUD, gallery, liveness/readiness)
- `api/auth_routes.py` — Login, registration, email-code, password-reset, and admin verify endpoints
- `api/user_routes.py` — User profile, email binding, redemption, and credit history
- `api/announcement_routes.py` — Audience-filtered announcement reads and admin CRUD
- `api/admin_routes.py` — Admin overview/health, task inspection, users, billing, models, and upstream management
- `core/auth.py` — JWT encode/decode, password hashing, FastAPI auth dependencies
- `core/config.py` — Pydantic `Settings` class, reads `.env`
- `models/generation_job.py` — SQLAlchemy model with status enum and `user_id` FK
- `models/job_charge.py` — Per-job reserved/settled/refunded billing state and price snapshot
- `models/outbox_event.py` — Transactional task-dispatch events and retry state
- `models/user.py` — User model (username, password_hash, display_name, is_public)
- `services/billing.py` — Atomic balance changes, immutable credit ledger, settlement, refund, and reconciliation
- `services/dispatcher.py` — Outbox publishing, heartbeat, watchdog, and periodic reconciliation loop
- `services/job_lifecycle.py` — Idempotent job claim, success settlement, and failure/refund transitions
- `services/health.py` — Public readiness and detailed admin dependency health
- `services/tasks.py` — Idempotent Celery worker execution and result handling
- `services/upstream.py` — HTTP client to upstream image API
- `services/storage.py` — MinIO upload/download/delete
- `services/rate_limit.py` — Redis-based rate limiting
- `db/init_db.py` — Default user, upstream, and model seed data only; schema changes live in `backend/db/migration/`

### Frontend Structure (`frontend/src/`)

- `App.vue` — Router shell with persistent header
- `router.ts` — Vue Router config
- `pages/HomePage.vue` — Generate panel + gallery (main page)
- `pages/LoginPage.vue` — Login, registration, and email-code password reset
- `components/AnnouncementBanner.vue` — Audience-filtered system banners
- `components/VersionReleaseDialog.vue` — Build version, changelog timeline, and read-only GitHub Release check
- `pages/PublicGalleryPage.vue` — Per-user public gallery view
- `pages/admin/AdminPage.vue` — Naive UI admin shell with lazy-loaded overview, upstream, model, user, job, billing, and announcement sections
- `components/AppHeader.vue` — Header with auth-aware navigation
- `lib/auth.ts` — Reactive auth state, login/logout/admin-verify functions
- `lib/api.ts` — API client with auto-injected auth headers
- `lib/types.ts` — TypeScript type definitions

## Key Design Decisions

- Upstream API credentials never reach the frontend — only stored in `.env` and backend container env vars
- Model list, reference image support, and size constraints are configured via `PUBLIC_MODELS_JSON` in `.env` and fallback to defaults in `config.py`
- The `api` and `worker` services share the same Docker image (`backend/Dockerfile`)
- Dev mode (`make backend`) rewrites DB/Redis/MinIO connection strings to use localhost ports
- `backend/.env` is a symlink to the project root `.env`
- Admin uses a separate JWT (not a user account) — verified via `ADMIN_SECRET_KEY` env var
- No frontend state management library — auth state is a simple Vue `reactive()` object in `lib/auth.ts`
- Frontend and backend must be released together; the version center only reports updates and does not perform partial upgrades
- Database schema is managed only by forward-only Flyway SQL migrations; API startup must not run `create_all` or ad-hoc `ALTER TABLE`
