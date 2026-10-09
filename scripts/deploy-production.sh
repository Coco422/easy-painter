#!/usr/bin/env bash
# Run on the existing production host. Credentials remain in its .env.
set -euo pipefail
umask 077
release_tag=${1:?release tag required}
deploy_dir=${2:?deployment directory required}
bundle_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
[[ "$release_tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || exit 2
cd -- "$deploy_dir"
test -f .env && test -f compose.yml
command -v flock >/dev/null
exec 9>.deploy.lock
flock -w 1800 9
previous_tag=$(sed -n 's/^IMAGE_TAG=//p' .env)
[[ "$previous_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Existing deployment must pin a release tag.' >&2; exit 2; }
# Reject stale releases even when builds finish out of order.
if [[ "$release_tag" != "$previous_tag" && "$(printf '%s\n' "$previous_tag" "$release_tag" | sort -V | tail -n 1)" != "$release_tag" ]]; then
  echo 'Skipping an older release.'
  exit 0
fi
compose=(docker compose --env-file .env -f compose.yml)
IMAGE_TAG="$release_tag" docker compose --project-directory "$deploy_dir" --env-file .env -f "$bundle_dir/deploy/compose.yml" pull
snapshot="backups/deploy-$(date -u +%Y%m%dT%H%M%SZ)-$release_tag"
mkdir -p "$snapshot"
cp -p .env "$snapshot/env"
cp -p compose.yml "$snapshot/compose.yml"
# Preflight and backup happen before any service stops or schema changes.
"${compose[@]}" exec -T postgres sh -c 'pg_dump --format=custom --serializable-deferrable -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$snapshot/database.dump"
"${compose[@]}" exec -T postgres pg_restore --file=/dev/null < "$snapshot/database.dump"
sha256sum "$snapshot/database.dump" > "$snapshot/database.dump.sha256"
echo "Saved deployment recovery point: $snapshot"
changed=false
finish() {
  result=$?
  if (( result != 0 )); then
    if [[ "$changed" == true ]]; then
      echo "Deployment failed. Recovery files: $snapshot; previous release: $previous_tag. No automatic schema rollback." >&2
    else
      echo 'Preflight failed; production configuration was not changed.' >&2
    fi
  fi
}
trap finish EXIT
# Gracefully drain the worker before running forward-only migrations.
changed=true
"${compose[@]}" stop -t 30 nginx api dispatcher
"${compose[@]}" stop -t 750 worker
cp "$bundle_dir/deploy/compose.yml" compose.yml
# Persist only IMAGE_TAG; never source or print the production environment.
sed "s/^IMAGE_TAG=.*/IMAGE_TAG=$release_tag/" .env > .env.deploy-tmp
mv .env.deploy-tmp .env
export IMAGE_TAG="$release_tag"
"${compose[@]}" run --rm migrate
"${compose[@]}" up -d --wait --wait-timeout 180
for attempt in $(seq 1 30); do
  if "${compose[@]}" exec -T api python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health/ready", timeout=5)' >/dev/null 2>&1; then
    "${compose[@]}" exec -T worker celery -A app.worker.celery_app inspect ping --timeout 10 >/dev/null
    "${compose[@]}" exec -T nginx wget -q -O /dev/null http://127.0.0.1/api/v1/health/ready
    echo "Production ready: $release_tag"
    exit 0
  fi
  sleep 5
done
echo 'Readiness check timed out.' >&2
exit 1
