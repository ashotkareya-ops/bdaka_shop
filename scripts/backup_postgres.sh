#!/usr/bin/env bash
set -Eeuo pipefail

# Run from the project directory, where docker-compose.yml and .env are located.
BACKUP_DIR="${BACKUP_DIR:-./backups}"
COMPOSE="${COMPOSE:-docker compose}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

STAMP="$(date -u +'%Y%m%dT%H%M%SZ')"
FILE="$BACKUP_DIR/bdaka_postgres_${STAMP}.sql.gz"

$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$FILE"
test -s "$FILE"
chmod 600 "$FILE"
echo "Backup created: $FILE"

# Keep the latest 14 daily backups (adjust retention as needed).
find "$BACKUP_DIR" -type f -name 'bdaka_postgres_*.sql.gz' -mtime +14 -delete
