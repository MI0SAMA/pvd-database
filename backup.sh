#!/bin/bash
# PVD Database Backup Script
# Run: /home/pvd_db/backup.sh
# Cron: 0 3 * * * /home/pvd_db/backup.sh >> /home/pvd_db/backup/backup.log 2>&1

set -e
BACKUP_DIR=/home/pvd_db/backup
DATE=$(date +%Y%m%d_%H%M)
LOG_FILE=$BACKUP_DIR/backup.log
NAS_SRC=/home/pvd_db/nas_data

echo "=== Backup started: $DATE ==="

# 1. Database dump (single copy, overwrite)
echo "[$(date)] Dumping database..."
docker exec pvd_postgres pg_dump -U yao pvd_db > $BACKUP_DIR/pvd_db_latest.sql
echo "[$(date)] DB dump: $(wc -c < $BACKUP_DIR/pvd_db_latest.sql) bytes"

# 2. NAS data sync (copy FROM remote mount to local backup)
echo "[$(date)] Syncing NAS data..."
mkdir -p $BACKUP_DIR/nas_data
rsync -a --delete $NAS_SRC/parameter/ $BACKUP_DIR/nas_data/parameter/ 2>/dev/null || echo "[$(date)] WARNING: NAS rsync had errors (may be OK for read-only mount)"
echo "[$(date)] NAS sync done"

# 3. Code snapshot
echo "[$(date)] Archiving code..."
tar -czf $BACKUP_DIR/code_latest.tar.gz \
    -C /home/pvd_db \
    dashboard/ processor/ docker-compose.yml .env.example ARCHITECTURE.md 2>/dev/null
echo "[$(date)] Code archive: $(wc -c < $BACKUP_DIR/code_latest.tar.gz) bytes"

echo "[$(date)] Backup complete"
