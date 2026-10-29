#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

BACKUP_DIR="$ROOT_DIR/deploy/backups"
mkdir -p "$BACKUP_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$BACKUP_DIR/pixle-$STAMP.dump"

set -a
. "$ROOT_DIR/.env.production"
set +a

docker compose exec -T db pg_dump \
  -U "$PIXLE_POSTGRES_USER" \
  -d "$PIXLE_POSTGRES_DB" \
  --format=custom \
  --no-owner \
  --no-privileges > "$OUT_FILE"

echo "Backup created: $OUT_FILE"
