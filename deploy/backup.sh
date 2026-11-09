#!/usr/bin/env bash
# Nightly PostgreSQL backup (server-setup.sh installs the cron entry).
#   ./deploy/backup.sh
# Keeps BACKUP_KEEP_DAYS days of compressed dumps in backups/.
#
# Restore one (replaces the current data):
#   ./deploy/compose.sh exec -T db sh -c \
#     'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' \
#     < backups/rag-<timestamp>.dump
set -euo pipefail
cd "$(dirname "$0")/.."

keep_days=${BACKUP_KEEP_DAYS:-7}
mkdir -p backups
chmod 700 backups

out="backups/rag-$(date -u +%Y%m%dT%H%M%SZ).dump"
# Custom format is compressed and lets pg_restore pick tables later.
./deploy/compose.sh exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$out.partial"
mv "$out.partial" "$out"

find backups -name 'rag-*.dump' -mtime +"$keep_days" -delete
echo "Backup written: $out ($(du -h "$out" | cut -f1))"
