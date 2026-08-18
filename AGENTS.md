# AGENTS.md

FastAPI + Celery + Vue 3 文生图 monorepo. For deep architecture, auth, gallery, and release detail read `CLAUDE.md`; this file captures only non-obvious operational facts.

## Commands

```bash
make deps       # foreground infra: postgres, redis, minio, migrate, worker, dispatcher (Ctrl+C to stop)
make backend    # migrate + API on :8000; rewrites DB/Redis/MinIO URLs to localhost ports
make frontend   # Vite dev server on :5173, proxies /api -> :8000
make deploy     # full containerized build + up
cd backend && uv run pytest        # all tests
cd backend && uv run pytest tests/test_reference_images.py
cd frontend && npx vue-tsc --noEmit  # typecheck
```

- Backend uses `uv` (not pip/venv). Run tests from `backend/` with `uv run pytest`.
- Backend tests are **pure unit tests** (no conftest; they use `monkeypatch`/fake objects) — no live Postgres/Redis/MinIO needed.
- `frontend` has no test/lint script; `npm run build` = `vue-tsc --noEmit && vite build` (typecheck + build).
- Production backup and disaster recovery use `scripts/backup-production.sh`; read `docs/backup-and-disaster-recovery.md` before changing or running recovery commands.

## Set up before running

- `cp .env.example .env` first — every `make` target fails if `.env` is missing.
- `backend/.env` is a **symlink to the root `.env`** (`make backend` re-creates it). Don't replace it with a real file.
- Upstream URL/key, SMTP creds live only in `.env`; never commit real values or leak to frontend.
- Keep infrastructure addresses, hostnames, usernames, SSH topology, and host fingerprints out of tracked files; repository examples use placeholders only.

## Architecture gotchas

- Backend services under `backend/app/` (api, core, db, models, services). API/worker share one Docker image (`backend/Dockerfile`).
- **DB schema is Flyway forward-only** migrations in `backend/db/migration/`. API startup must never run `create_all` or ad-hoc `ALTER TABLE`; schema changes go in new SQL migration files. `backend/db/init_db.py` only seeds (default user, models) — no schema.
- Never rsync a live `data/postgres` directory. Production backups use a transaction-consistent `pg_dump`; only MinIO uses rsync hard-link incrementals, and Redis is intentionally not restored.
- Job creation atomically writes job + precharge + negative credit tx + outbox event in one DB transaction; charges settle only on successful image delivery, refund fully otherwise.
- Frontend has **no state-management library** — auth is a plain Vue `reactive()` in `lib/auth.ts`. Admin and selected shared components use naive-ui; public UI styling lives in `frontend/src/style.css`.

## Versioning / release

- Root `VERSION` is canonical and holds `vX.Y.Z`; **frontend/backend manifests store the same value WITHOUT the `v` prefix** (frontend/package.json + backend/pyproject.toml).
- Bump with `python3 scripts/version.py set vX.Y.Z` so all manifests stay in sync; validate with `check`, preview release notes with `notes`.
- `CHANGELOG.md` (section format `## vX.Y.Z - YYYY-MM-DD`) is the release-notes source. Pushing a `vX.Y.Z` tag runs `version.py check` and creates the GitHub Release; don't cut a release by hand-editing manifests only.
