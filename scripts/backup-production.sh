#!/usr/bin/env bash
#
# Run this script on the designated backup environment.
#
# Required source settings are supplied outside the repository:
#   EASY_PAINTER_REMOTE_HOST=operator@source-host
#   EASY_PAINTER_REMOTE_APP_DIR=/absolute/path/to/easy-painter
#
# One-time SSH setup:
#   ssh-keygen -t ed25519 -f "$HOME/.ssh/easy_painter_backup" -N ''
#   ssh-copy-id -i "$HOME/.ssh/easy_painter_backup.pub" operator@source-host
#
# Manual run:
#   ./backup-production.sh
#
# Optional overrides:
#   EASY_PAINTER_BACKUP_ROOT=/data/backups/easy-painter \
#   EASY_PAINTER_KEEP_SNAPSHOTS=30 \
#   ./backup-production.sh

set -Eeuo pipefail
umask 077

readonly REMOTE_HOST="${EASY_PAINTER_REMOTE_HOST:-}"
readonly REMOTE_APP_DIR="${EASY_PAINTER_REMOTE_APP_DIR:-}"
readonly SSH_IDENTITY_FILE="${EASY_PAINTER_SSH_KEY:-${HOME}/.ssh/easy_painter_backup}"
readonly BACKUP_ROOT="${EASY_PAINTER_BACKUP_ROOT:-${HOME}/backups/easy-painter}"
readonly KEEP_SNAPSHOTS="${EASY_PAINTER_KEEP_SNAPSHOTS:-30}"
readonly MIN_FREE_KB="${EASY_PAINTER_MIN_FREE_KB:-2097152}"
readonly SNAPSHOT_ROOT="${BACKUP_ROOT}/snapshots"
readonly LOCK_DIR="${BACKUP_ROOT}/.backup.lock"
readonly SNAPSHOT_ID="$(date -u +%Y-%m-%dT%H%M%SZ)"

STAGING_DIR=""

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$*"
}

cleanup() {
  rmdir "${LOCK_DIR}" >/dev/null 2>&1 || true
}

on_error() {
  local exit_code=$?
  local line_number=${1:-unknown}
  set +e
  log "ERROR: backup failed at line ${line_number} (exit ${exit_code})."
  if [[ -n "${STAGING_DIR}" ]]; then
    log "Partial snapshot kept for diagnosis: ${STAGING_DIR}"
  fi
  exit "${exit_code}"
}

trap 'on_error ${LINENO}' ERR
trap cleanup EXIT

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "ERROR: required command not found: $1"
    exit 1
  fi
}

for command_name in ssh rsync sha256sum find sort sed awk stat df du wc tr readlink; do
  require_command "${command_name}"
done

if [[ -z "${REMOTE_HOST}" ]]; then
  log "ERROR: EASY_PAINTER_REMOTE_HOST is required."
  exit 1
fi

if [[ -z "${REMOTE_APP_DIR}" || "${REMOTE_APP_DIR}" != /* || "${REMOTE_APP_DIR}" == *"'"* ]]; then
  log "ERROR: EASY_PAINTER_REMOTE_APP_DIR must be an absolute path without single quotes."
  exit 1
fi

if [[ ! "${KEEP_SNAPSHOTS}" =~ ^[0-9]+$ ]] || (( KEEP_SNAPSHOTS < 2 )); then
  log "ERROR: EASY_PAINTER_KEEP_SNAPSHOTS must be an integer of at least 2."
  exit 1
fi

if [[ ! "${MIN_FREE_KB}" =~ ^[0-9]+$ ]]; then
  log "ERROR: EASY_PAINTER_MIN_FREE_KB must be a non-negative integer."
  exit 1
fi

if [[ ! -r "${SSH_IDENTITY_FILE}" ]]; then
  log "ERROR: SSH key is missing or unreadable: ${SSH_IDENTITY_FILE}"
  log "Create it with: ssh-keygen -t ed25519 -f '${SSH_IDENTITY_FILE}' -N ''"
  exit 1
fi

mkdir -p "${SNAPSHOT_ROOT}"
chmod 700 "${BACKUP_ROOT}" "${SNAPSHOT_ROOT}"

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  log "Another backup is already running; skipping."
  exit 0
fi

# Only abandoned temporary directories use this prefix. Completed snapshots are
# never touched here.
find "${SNAPSHOT_ROOT}" -mindepth 1 -maxdepth 1 -type d \
  -name '.partial-20*' -mtime +2 -exec rm -rf -- {} +

available_kb=$(df -Pk "${BACKUP_ROOT}" | awk 'NR == 2 { print $4 }')
if [[ ! "${available_kb}" =~ ^[0-9]+$ ]] || (( available_kb < MIN_FREE_KB )); then
  log "ERROR: less than $((MIN_FREE_KB / 1024)) MiB is available under ${BACKUP_ROOT}."
  exit 1
fi

STAGING_DIR="${SNAPSHOT_ROOT}/.partial-${SNAPSHOT_ID}"
FINAL_DIR="${SNAPSHOT_ROOT}/${SNAPSHOT_ID}"
if [[ -e "${STAGING_DIR}" || -e "${FINAL_DIR}" ]]; then
  log "ERROR: snapshot path already exists for ${SNAPSHOT_ID}."
  exit 1
fi

mkdir -m 700 "${STAGING_DIR}"
mkdir -m 700 \
  "${STAGING_DIR}/database" \
  "${STAGING_DIR}/config" \
  "${STAGING_DIR}/minio"

ssh_args=(
  ssh
  -i "${SSH_IDENTITY_FILE}"
  -o IdentitiesOnly=yes
  -o BatchMode=yes
  -o StrictHostKeyChecking=yes
  -o ConnectTimeout=15
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=3
  "${REMOTE_HOST}"
)
printf -v ssh_identity_escaped '%q' "${SSH_IDENTITY_FILE}"
rsync_ssh="ssh -i ${ssh_identity_escaped} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"

log "Checking production services."
"${ssh_args[@]}" \
  "cd '${REMOTE_APP_DIR}' && test -r compose.yml && test -r .env && docker compose -f compose.yml exec -T postgres sh -c 'exec pg_isready -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"' >/dev/null"
"${ssh_args[@]}" \
  "cd '${REMOTE_APP_DIR}' && docker compose -f compose.yml exec -T minio curl -fsS http://127.0.0.1:9000/minio/health/live >/dev/null"

log "Creating a transaction-consistent PostgreSQL dump."
remote_dump_command="cd '${REMOTE_APP_DIR}' && exec docker compose -f compose.yml exec -T postgres sh -c 'exec pg_dump -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --format=custom --compress=9 --no-owner --no-acl --serializable-deferrable'"
"${ssh_args[@]}" "${remote_dump_command}" \
  > "${STAGING_DIR}/database/easy_painter.dump"
test -s "${STAGING_DIR}/database/easy_painter.dump"

# pg_restore writes the archive to /dev/null. This forces it to read and decompress
# the complete dump without changing any production database.
log "Validating the complete PostgreSQL archive."
remote_verify_command="cd '${REMOTE_APP_DIR}' && exec docker compose -f compose.yml exec -T postgres pg_restore --file=/dev/null --no-owner --no-acl"
"${ssh_args[@]}" "${remote_verify_command}" \
  < "${STAGING_DIR}/database/easy_painter.dump"
(
  cd "${STAGING_DIR}/database"
  sha256sum easy_painter.dump > easy_painter.dump.sha256
)

log "Copying deployment configuration."
rsync -pt -e "${rsync_ssh}" \
  "${REMOTE_HOST}:${REMOTE_APP_DIR}/compose.yml" \
  "${STAGING_DIR}/config/"
rsync -pt -e "${rsync_ssh}" \
  "${REMOTE_HOST}:${REMOTE_APP_DIR}/.env" \
  "${STAGING_DIR}/config/"
chmod 600 "${STAGING_DIR}/config/.env" "${STAGING_DIR}/config/compose.yml"

previous_snapshot=""
if [[ -L "${BACKUP_ROOT}/latest" ]]; then
  latest_target=$(readlink "${BACKUP_ROOT}/latest")
  candidate="${BACKUP_ROOT}/${latest_target}"
  if [[ "${candidate}" == "${SNAPSHOT_ROOT}/"* && -d "${candidate}/minio" ]]; then
    previous_snapshot="${candidate}"
  fi
fi

# Database comes first. The application uploads an object before marking a job as
# succeeded in PostgreSQL, so every object referenced by this database snapshot is
# expected to exist by the time this copy begins. MinIO temporary/multipart data is
# excluded; only completed object data is useful for recovery.
log "Creating the MinIO incremental snapshot."
rsync_args=(
  -rlpt
  --delete
  --partial
  --exclude=.minio.sys/tmp/
  --exclude=.minio.sys/multipart/
  -e "${rsync_ssh}"
)
if [[ -n "${previous_snapshot}" ]]; then
  rsync_args+=(--link-dest="${previous_snapshot}/minio")
fi
rsync "${rsync_args[@]}" \
  "${REMOTE_HOST}:${REMOTE_APP_DIR}/data/minio/" \
  "${STAGING_DIR}/minio/"

log "Recording snapshot metadata."
{
  printf 'snapshot_id=%s\n' "${SNAPSHOT_ID}"
  printf 'created_at_utc=%s\n' "$(date -u +%FT%TZ)"
  printf 'database_format=PostgreSQL custom archive\n'
  printf 'database_consistency=single transaction serializable deferrable\n'
  printf 'minio_mode=rsync link-dest incremental snapshot\n'
  printf 'previous_snapshot=%s\n' "${previous_snapshot:-none}"
  printf 'database_bytes=%s\n' "$(stat -c %s "${STAGING_DIR}/database/easy_painter.dump")"
  printf 'minio_files=%s\n' "$(find "${STAGING_DIR}/minio" -type f | wc -l | tr -d ' ')"
  printf 'minio_apparent_kb=%s\n' "$(du -sk --apparent-size "${STAGING_DIR}/minio" | awk '{ print $1 }')"
} > "${STAGING_DIR}/manifest.txt"
chmod 600 "${STAGING_DIR}/manifest.txt"

# A snapshot only becomes visible after every step and validation succeeded.
mv "${STAGING_DIR}" "${FINAL_DIR}"
STAGING_DIR=""
ln -s "snapshots/${SNAPSHOT_ID}" "${BACKUP_ROOT}/.latest-${SNAPSHOT_ID}"
mv -Tf "${BACKUP_ROOT}/.latest-${SNAPSHOT_ID}" "${BACKUP_ROOT}/latest"

# Retain the newest N completed snapshots. Removing an old snapshot does not remove
# data still referenced by hard links in another retained snapshot.
find "${SNAPSHOT_ROOT}" -mindepth 1 -maxdepth 1 -type d \
  -name '20??-??-??T??????Z' -printf '%f\n' \
  | sort -r \
  | sed -n "$((KEEP_SNAPSHOTS + 1)),\$p" \
  | while IFS= read -r old_snapshot_name; do
      [[ "${old_snapshot_name}" == 20??-??-??T??????Z ]] || continue
      rm -rf -- "${SNAPSHOT_ROOT}/${old_snapshot_name}"
    done

log "Backup completed: ${FINAL_DIR} ($(du -sh "${FINAL_DIR}" | awk '{ print $1 }') apparent)."
