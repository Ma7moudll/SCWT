#!/usr/bin/env bash
# SCWT dev-database backup.
#   ./scripts/backup_db.sh            -> backups/scwt_YYYYmmdd_HHMMSS.dump
# Restore with:
#   pg_restore -U scwt -d scwt --clean <file>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$ROOT/backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
FILE="$BACKUP_DIR/scwt_$STAMP.dump"

mkdir -p "$BACKUP_DIR"
PGPASSWORD="${POSTGRES_PASSWORD:-scwt}" pg_dump \
  -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" \
  -U "${POSTGRES_USER:-scwt}" -d "${POSTGRES_DB:-scwt}" \
  -Fc -f "$FILE"

echo "Backup written: $FILE"
# Keep the 14 most recent dumps; delete older ones.
ls -1t "$BACKUP_DIR"/scwt_*.dump 2>/dev/null | tail -n +15 | xargs rm -f 2>/dev/null || true
