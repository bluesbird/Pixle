#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 deploy/backups/pixle-YYYYMMDDTHHMMSSZ.dump" >&2
  exit 2
fi

DUMP_PATH="$1"
if [ ! -f "$DUMP_PATH" ]; then
  echo "Backup file not found: $DUMP_PATH" >&2
  exit 2
fi

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

set -a
. "$ROOT_DIR/.env.production"
set +a

cat "$DUMP_PATH" | docker compose exec -T db pg_restore \
  -U "$PIXLE_POSTGRES_USER" \
  -d "$PIXLE_POSTGRES_DB" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges

echo "Restore completed from: $DUMP_PATH"
