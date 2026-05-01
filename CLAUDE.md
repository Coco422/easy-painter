# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Easy Painter is a text-to-image generation app with user authentication. Users submit prompts via the frontend; the backend enqueues a Celery task that calls a private upstream image API, stores the result in MinIO, and the frontend polls for completion.

## Tech Stack

- **Frontend**: Vue 3 + Vite + TypeScript + vue-router
- **Backend**: FastAPI + SQLAlchemy + Celery + Redis + PostgreSQL + MinIO
- **Auth**: JWT (bcrypt password hashing, PyJWT tokens)
- **Python tooling**: `uv` (dependency management), `pytest` (testing)
- **Infra**: Docker Compose (nginx, api, worker, redis, postgres, minio, minio-init)

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
```

## Architecture

### Request Flow

1. Frontend submits `POST /api/v1/jobs` with prompt + model + optional reference image (+ JWT if logged in)
2. API validates, saves `GenerationJob` to PostgreSQL (with `user_id` if authenticated), enqueues `generate_image_task` via Celery
3. Celery worker calls upstream image API (configured via `UPSTREAM_BASE_URL` / `UPSTREAM_API_KEY` in `.env`)
4. Result image is uploaded to MinIO; job status updated in DB
5. Frontend polls `GET /api/v1/jobs/{job_id}` until status is `succeeded` or `failed`

### Auth System

- No public registration — users created by admin or auto-created from `DEFAULT_USERNAME`/`DEFAULT_PASSWORD` env vars on first startup
- JWT tokens stored in `localStorage`, sent as `Authorization: Bearer <token>` header
- Admin access via secret key (`ADMIN_SECRET_KEY` env var), produces a separate JWT with `role=admin` claim
- Frontend uses vue-router with routes: `/` (home), `/login`, `/gallery/:username` (public gallery), `/admin`

### Gallery Logic

- Logged-in users see only their own succeeded jobs
- Anonymous visitors see succeeded jobs from users with `is_public=True` plus legacy anonymous jobs (`user_id IS NULL`)
- Public user gallery accessible at `/gallery/{username}` (requires `is_public=True`)

### Backend Structure (`backend/app/`)

- `api/routes.py` — Job endpoints (meta, jobs CRUD, gallery, healthz)
- `api/auth_routes.py` — Login and admin verify endpoints
- `api/user_routes.py` — User profile (GET/PUT /users/me)
- `api/admin_routes.py` — Admin endpoints (list/delete jobs, list/create users)
- `core/auth.py` — JWT encode/decode, password hashing, FastAPI auth dependencies
- `core/config.py` — Pydantic `Settings` class, reads `.env`
- `models/generation_job.py` — SQLAlchemy model with status enum and `user_id` FK
- `models/user.py` — User model (username, password_hash, display_name, is_public)
- `services/tasks.py` — Celery task definition and result handling
- `services/upstream.py` — HTTP client to upstream image API
- `services/storage.py` — MinIO upload/download/delete
- `services/rate_limit.py` — Redis-based rate limiting
- `db/init_db.py` — Table creation, column migrations, default user creation

### Frontend Structure (`frontend/src/`)

- `App.vue` — Router shell with persistent header
- `router.ts` — Vue Router config
- `pages/HomePage.vue` — Generate panel + gallery (main page)
- `pages/LoginPage.vue` — Login form
- `pages/PublicGalleryPage.vue` — Per-user public gallery view
- `pages/AdminPage.vue` — Admin dashboard (secret key auth, job/user management)
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
