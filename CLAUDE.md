# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Easy Painter is a text-to-image generation app with user authentication. Users submit prompts via the frontend; the backend atomically creates the job, billing reservation, credit transaction, and transactional outbox event. A dispatcher publishes the Celery task, the worker calls a private upstream image API and stores the result in RustFS, and the frontend polls for completion.

## Tech Stack

- **Frontend**: Vue 3 + Vite + TypeScript + vue-router
- **Backend**: FastAPI + SQLAlchemy + Celery + Redis + PostgreSQL + RustFS
- **Auth**: JWT (bcrypt password hashing, PyJWT tokens)
- **Python tooling**: `uv` (dependency management), `pytest` (testing)
- **Infra**: Docker Compose (Flyway migrate, nginx, api, dispatcher, worker, redis, postgres, rustfs, storage-init)

## Common Commands

```bash
# Start infrastructure (postgres, redis, rustfs, worker) — runs in foreground, Ctrl+C to stop
make deps

# Start backend API server (auto-reload on port 8000)
make backend

# Start frontend dev server (port 5173, proxies /api → localhost:8000)
make frontend

# Local container deployment (production uses formal-tag CD)
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

# Validate the production backup script
bash -n scripts/backup-production.sh
```

Production backup contents, snapshot validation, and disaster recovery procedures live in `docs/backup-and-disaster-recovery.md`. Infrastructure identities and access topology must remain outside the repository.

## Architecture

### Request Flow

1. Frontend submits `POST /api/v1/jobs` with prompt, model, optional ordered staged reference image IDs, JWT, and a stable `Idempotency-Key`
2. API atomically creates `GenerationJob`, `JobCharge`, the negative credit transaction, and an `OutboxEvent`; the balance update is conditional and cannot go below zero
3. The dispatcher publishes due outbox events to Celery and maintains the heartbeat used by readiness checks
4. A worker conditionally claims the queued job, calls the configured upstream, and uploads a successful result to RustFS
5. Success settles the reserved charge; final failure or watchdog timeout uses the same idempotent path to mark the job failed and refund it in full
6. Frontend polls `GET /api/v1/jobs/{job_id}` until a final state and refreshes balance and billing status

### Auth System

- Public registration asks only for email, verification code and password, assigning a random internal username and default display name when omitted. Email is the primary login identifier; exact username login remains supported, while email matching is case-insensitive. Password reset uses a one-time email code stored as a Redis HMAC digest
- Existing signed-in users without email can bind one through `POST /users/me/email/code` + `PUT /users/me/email`; a bound email cannot be self-replaced, while admin can still update it directly
- Email code sending uses a Redis atomic 60-second cooldown plus short-window and daily limits across email, IP, and (for authenticated binding) user ID; binding codes are scoped to the current user ID
- Users can also be created by admin or auto-created from `DEFAULT_USERNAME`/`DEFAULT_PASSWORD`/optional `DEFAULT_EMAIL` on first startup
- New or changed usernames must be 3–32 lowercase ASCII letters, digits or underscores and begin with a letter; `public` is reserved for the community gallery API route. Registration, profile rename and admin creation reject case-insensitive collisions; existing legacy names remain valid until changed. Users edit username and display name in their profile; a rename changes the public gallery URL and invalidates its old URL, with an explicit client warning. Database uniqueness also catches concurrent writes. Admin forms validate optional emails and passwords (6–128 characters); 422 errors retain readable Chinese field messages.
- User access JWTs (15 minutes, `typ=access`, `sid`) remain in `localStorage` and use `Authorization: Bearer <token>`. Refresh credentials live only in a host-only HttpOnly, SameSite=Strict Cookie scoped to `/api/v1/auth`, Secure in production. Flyway V11 `auth_sessions` stores session state and rotation counters, never raw refresh credentials.
- Visible-page authenticated requests renew on demand: 30-day idle expiry capped at 180 days from login. No timer or hidden-tab polling extends sessions. Web Locks coordinate tabs; the server locks session rows and accepts the immediate predecessor for 30 seconds, returning the same successor. Later replay revokes the session. Logout and password-hash changes invalidate session-backed access and refresh credentials.
- `/auth/session` migrates valid legacy user JWTs once per browser transition; session-backed JWTs cannot use it to reset the absolute deadline. Legacy JWTs retain their original expiry during compatibility; already expired legacy JWTs require login. Admin JWTs keep the existing separate policy.
- Login/register/refresh/session/logout use `X-Session-Request: 1`; production rejects foreign Origin/Sec-Fetch-Site, development also accepts configured frontend origins for Vite proxying. Auth responses with tokens/Cookies are `no-store`; never cache them at the CDN.
- `authenticatedFetch` handles user API and private binary requests, coalesces refresh and retries an application JSON 401 once with the unchanged body/idempotency key. Temporary or HTML errors retain credentials. Account-owned UI watches stable `authState.sessionId`, not the rotating access token.
- Admin access via secret key (`ADMIN_SECRET_KEY` env var), produces a separate JWT with `role=admin` claim
- Frontend routes: `/` (community), `/create`, `/history`, `/gallery`, `/gallery/:username` (shared portfolio), `/favorites`, `/profile`, `/login`, `/admin`
- `/canvas` and `/canvas/:id` are the separate local-first canvas library/editor; `/create` remains available. Read `docs/v0.20.0-release.md` for storage, recovery, cloud quotas and migration details.

### Recharge and Credit Provenance

- ZPAY checkout defaults off. V13 adds packages, recharge orders and credit provenance; V14 stores immutable payment configurations with Fernet-encrypted merchant keys. Admin sets credentials in Recharge Management; only `PAYMENT_CONFIG_ENCRYPTION_KEY` lives in private env. Never return keys/ciphertext, reuse JWT keys, or replace a master key without re-encrypting every revision. Setup: `docs/recharge-center.md`; SDK findings: `docs/zpay-sdk-security-review.md`.
- Only verified ZPAY notifications or active queries grant credits. Use the order's original `config_revision` credentials, check merchant/order/amount/method/trade number, lock user then order, and commit paid state/ledger/lots together. Repeated delivery must credit once. Browser return parameters are never evidence of payment; query credentials/signatures must be redacted from logs.
- All new debits allocate noncash lots first, then paid FIFO. Refund failed reservations to original lots. Existing balances, redemption codes and admin adjustments have zero cash basis. Future commissions use only settled, unreversed paid allocations and the exact rational cash-basis snapshots, never inferred yuan-per-credit values.
- Bounded recharge reconciliation runs in a worker so network delays do not block dispatcher heartbeats. Disabling checkout still permits confirmation of existing paid orders with their original merchant configuration. No cash refund, payout or commission API is enabled in this phase.

### Creation Workspace

- `/create` tracks up to 100 version ancestry links per account in browser localStorage (`easy-painter:creation-versions:<ownerId>`), restoring job details through existing authorized APIs. This is local workspace metadata, not a server-side conversation or a media-retention extension.
- Result edits fetch the selected original, stage it as a new reference without silent eviction, and submit one job. Persist the exact pending request and idempotency key before POST; unknown responses require explicit confirmation with the same request after refresh. Account/session changes invalidate in-flight UI updates.
- Adding a result to a new or existing canvas first saves the authorized image Blob through existing IndexedDB assets/projects, with capacity and revision checks. Append an image, provenance note and connected, unsubmitted generation node; never replay the original job or auto-submit a paid run.

See `docs/creation-workspace.md` for usage and local mock preview.

### Agent / MCP

- MCP uses the official SDK at `/api/mcp`, separate resource-bound opaque OAuth credentials and Flyway V12 additive tables. Empty `MCP_PUBLIC_URL` disables access; production requires the exact canonical HTTPS endpoint. Setup, protocol and local preview: `docs/mcp-integration.md`.
- Lock owner then grant. Agent usage, job, credit reservation and outbox must commit together through `create_generation_job`; enforce per-job caps and available balance, never daily spending limits. The legacy V12 `daily_limit` column only satisfies its storage constraint and is not a budget. Scope idempotency to the grant and preserve exact request parameters before paid calls.
- Never accept website JWTs at MCP or agent credentials at browser APIs. Check grant/password/resource/expiry on every call and result media access. SDK transport auth does not authorize business actions by itself.
- Agent content and Skill ZIP share `backend/app/agent_content/`; browser-local canvases/version graphs are not accessible to remote tools. `scripts/preview-mcp.py` is an isolated development fixture, never an application startup or production seed path.

### Infinite Canvas

- Browser IndexedDB stores account-scoped project JSON and content-hashed image Blobs. Layout undo is separate from paid generation runs; save the idempotency key and exact request before submission. Unknown submission results require confirmation with the same key.
- Local project saves compare revisions to reject cross-tab overwrites. Export/import includes media; only a successfully stored local copy survives original-media expiry. Imports never auto-submit generation requests.
- Optional cloud copies use Flyway V10 `canvas_projects` / `canvas_assets` and the private RustFS media bucket. Only an enabled `vip` group may write; owners retain read/export/delete access after downgrade. Cloud assets are retained until project/account deletion and use the existing deletion queue.
- Lock the user before cloud mutations, enforce byte/project quotas server-side, and compare `expected_version` before document updates. Upload hashes are verified against actual image bytes; downloads authorize before object access.
- Canvas reference/attribution: `THIRD_PARTY_NOTICES.md`. Frontend canvas model tests run with the existing Node test command; explicitly typecheck application code with `npx vue-tsc --noEmit -p tsconfig.app.json`.

### Artwork, Portfolio and Community Logic

- `/history` lists all owned jobs except soft-deleted records, retaining text and billing after media expiry. `/gallery` lists only explicitly joined works; public sharing also requires the user's `is_public` master switch.
- Favorites are viewer-owned references in `favorites`, never permission grants or retention extensions. Curated inspiration targets canonicalize to their source job to prevent duplicate favorites; inaccessible bookmarks expose only tombstones.
- Community publication requires explicit `consent_public_prompt: true`, the owner's public master switch and an unexpired original. Admin approval creates an independent permanent copy; simply joining a portfolio never creates a submission. Master switch off withdraws pending submissions, not approved copies.
- Lock the owner before the job when submitting/reviewing; re-read with `populate_existing` after locking. Recheck expiry after object copy. Pending review never extends retention.
- Ordinary new generated/reference media defaults to 48h, VIP remains 720h. V9 resets still-live non-VIP existing deadlines to migration +48h and preserves expired/deleting/VIP/pricing records. Later group changes still affect future operations only.
- Portfolio/favorite media prefer a live independent community copy; original deletion cannot delete the curated object or its thumbnail.
- Sharing requires live public media: public portfolios share their portfolio URL, while permanent community copies share their independent media URL. Private originals cannot be shared, and share payloads never include owner-only prompts or authenticated media URLs. Frontend sharing/media regression checks: `cd frontend && node --experimental-strip-types --test tests/*.test.mjs`.
- Lists use stored 640px WebP thumbnails; `artwork_media_routes` authorizes before conditional 304/HEAD. Private media use stable URLs and `private, no-cache, must-revalidate`; metadata uses `private, no-store`.
- `ProtectedImage` gates requests on expiry, aborts when invalid, and retries only transient errors once. Its opt-in `preview` uses `ImageViewer` + the existing Naive UI `NImagePreview` for original-image zoom/pan/rotation at artwork, inspiration and admin detail entrances. The viewer receives the authorized Blob URL, never the original private URL; close and release it on expiry/source/account changes or unmount. Toolbar actions and transforms remain library-owned, while named buttons and top-layer Escape handling preserve access and modal behavior. Never fetch from a template/render helper. `useMediaClock` shares the timer. Old gallery components remain for compatibility but are not routed.
- See `docs/v0.19.0-release.md` for rollout, bounded thumbnail warmup, and verification evidence.

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

- `api/artwork_routes.py` — History, portfolio, reference favorites, explicit submissions and review
- `api/artwork_media_routes.py` — Stable authorized original/thumbnail and reference preview streams
- `services/artworks.py` — Central access resolution, permanent-copy precedence and batched list metadata
- `services/thumbnails.py` — Bounded WebP derivatives, failure backoff, skip-locked backfill
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
- `services/storage.py` — RustFS upload/download/delete via the compatible MinIO S3 SDK
- `services/storage_init.py` — Private bucket initialization; failures block service startup
- `services/rate_limit.py` — Redis-based rate limiting; generation uses a shared account burst guard (default 60 new submissions/second), never a minute/day quota. Old `GENERATE_RATE_LIMIT_*` values are ignored.
- `db/init_db.py` — Default user, upstream, and model seed data only; schema changes live in `backend/db/migration/`

### Frontend Structure (`frontend/src/`)

- `App.vue` — Router shell with persistent header
- `router.ts` — Vue Router config
- `pages/CreatePage.vue` — Two-column creation workspace, presets, result selection and version branching. `useCreationVersions.ts` owns account-scoped ancestry and safe edit requests; `CreationVersions.vue` presents results. Accepted jobs retain browser-local batch membership, per-job polling and billing details; the waiting panel is shared per batch.
- `pages/InspirationPage.vue` — Permanent community feed
- `pages/ArtworkLibraryPage.vue` — History, personal/shared portfolio and favorites
- `components/ArtworkModal.vue` — Gallery membership, favorites, explicit community consent and lifecycle actions
- `pages/LoginPage.vue` — Login, registration, and email-code password reset
- `components/AnnouncementBanner.vue` — Audience-filtered system banners
- `components/VersionReleaseDialog.vue` — Build version, changelog timeline, and read-only GitHub Release check
- `pages/admin/sections/AdminCommunitySubmissions.vue` — Explicit user submission review queue
- `pages/admin/AdminPage.vue` — Naive UI admin shell with lazy-loaded overview, upstream, model, user, job, billing, and announcement sections
- `components/AppHeader.vue` — Header with auth-aware navigation
- `lib/auth.ts` — Reactive auth state, login/logout/admin-verify functions
- `lib/api.ts` — API client with auto-injected auth headers
- `lib/types.ts` — TypeScript type definitions

## Key Design Decisions

- Upstream API credentials never reach the frontend — only stored in `.env` and backend container env vars
- Model capabilities live in `model_configs` and are editable in admin; `PUBLIC_MODELS_JSON` is only a seed/fallback. Per-model `max_reference_images` defaults to 5 and is independent of the user-group reference library quota.
- Staged reference uploads deduplicate byte-identical content within the same account using existing `media_hash` (SHA-256). Reuse only live available images before quota/eviction checks; preserve filename, creation time and expiry. New uploads store hashes immediately; matching-size legacy candidates without hashes are read and backfilled under the user/source row locks. Failed legacy reads abort without uploading or evicting. No schema migration is needed.
- Jobs accept ordered `reference_image_ids`, preserve legacy single-image inputs, and snapshot private copies in `generation_jobs.reference_images` (V8). Worker reads snapshots with a legacy-column fallback; cleanup must cover all copies. GPT Image uses repeated `image` multipart fields, while multi-image Seedream uses `image[]`.
- The `api` and `worker` services share the same Docker image (`backend/Dockerfile`)
- Dev mode (`make backend`) rewrites DB/Redis/RustFS connection strings to use localhost ports
- `backend/.env` is a symlink to the project root `.env`
- Admin uses a separate JWT (not a user account) — verified via `ADMIN_SECRET_KEY` env var
- No frontend state management library — auth state is a simple Vue `reactive()` object in `lib/auth.ts`
- Frontend and backend must be released together; the version center only reports updates and does not perform partial upgrades
- Formal tag image builds include a production CD job after all three images succeed; configuration and failure recovery: `docs/continuous-deployment.md`. It deploys only tags whose commits are on main, using production environment SSH Secrets.
- Every production deployment pins a newly created `vX.Y.Z` tag; `main` and `sha-*` images are build/diagnostic artifacts, not steady production releases
- Database schema is managed only by forward-only Flyway SQL migrations; API startup must not run `create_all` or ad-hoc `ALTER TABLE`
