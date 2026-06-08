# Database Backup & Recovery (Sprint 83, GATE-83)

## Overview

Automated daily PostgreSQL backup via `pg_dump -Fc` (compressed custom format).
Backups stored at `/backups/` inside the agents container, bind-mounted to `./backups/`
on the host (repo root).

**Security note:** Backups contain PII (owner names, registration numbers, transaction
amounts). The host-side `./backups/` directory should be encrypted at rest. On Linux,
use `eCryptfs` or `LUKS`. On Windows, use BitLocker. Backups are **not encrypted**
by pg_dump itself — add `pg_dump --encrypt` (PG16+) or pipe through GPG for
production environments containing sensitive data.

## Schedule

| Time (IST) | Job ID | Description |
|------------|--------|-------------|
| 04:00 daily | `db_backup` | pg_dump → verify → prune old (7-day retention) |
| 11:30 daily | `backup_staleness_check` | Alert via Discord if backup >26h old |

## Recovery

### Prerequisites

- PostgreSQL container running (`docker compose up -d postgres`)
- Target database exists (it will be dropped and recreated if using `-c`)

### Full restore (recommended: restore to a test DB first)

**⚠ WARNING:** The `-c` flag (clean) **drops** existing database objects before
restoring. This will delete all current data in the target DB. Always test
restore in a separate database first.

```bash
# Restore to a test database (safe):
docker compose exec postgres createdb -U re_os_user re_os_restore_test
docker compose exec postgres pg_restore \
  -h localhost \
  -U re_os_user \
  -d re_os_restore_test \
  /backups/re_os_YYYYMMDD_HHMMSS.dump

# Verify row counts:
docker compose exec postgres psql -U re_os_user -d re_os_restore_test \
  -c "SELECT COUNT(*) FROM rera_projects;"

# Once verified, restore to production (destructive — drops existing data):
docker compose exec postgres pg_restore \
  -h localhost \
  -U re_os_user \
  -d re_os \
  -c \
  /backups/re_os_YYYYMMDD_HHMMSS.dump
```

### Restore from host (if container is not running)

```bash
pg_restore -h localhost -U re_os_user -d re_os -c \
  < ./backups/re_os_YYYYMMDD_HHMMSS.dump
```

### Verify without restoring

```bash
docker compose exec agents pg_restore --list /backups/re_os_YYYYMMDD_HHMMSS.dump | head -25
```

### List available backups

```bash
ls -lah backups/re_os_*.dump
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `pg_dump: not found` | `postgresql-client` not installed in agents container | `docker compose exec agents apt-get install -y postgresql-client` |
| `connection refused` | DB hostname/port wrong in `DATABASE_URL` | Verify `docker compose ps` shows `re_os_db` healthy; check `DATABASE_URL` env |
| `disk full` | Backup directory out of space | Run `enforce_retention()` manually: `docker compose exec agents python -c "from utils.backup import enforce_retention; print(f'Pruned {enforce_retention(7)}')"` |
| `permission denied` | Backup file owned by different user | `docker compose exec agents chown -R $(id -u):$(id -g) /backups` |
| Verification fails | Corrupted dump file (disk full during write, network error) | Corrupt file is auto-deleted by `DBBackup.run()`. Check logs and re-run. |

## Architecture

### Component map

| Layer | File | Responsibility |
|-------|------|----------------|
| Utility | `utils/backup.py` | `DBBackup.run()` — pg_dump wrapper, no SQLAlchemy |
| Integrity | `utils/backup.py:verify_backup()` | `pg_restore --list` post-backup validation |
| Staleness | `utils/backup.py:check_backup_staleness()` | Check backup age, alert Discord if >26h |
| Retention | `utils/backup.py:enforce_retention(7)` | Keep 7 most recent dumps |
| Scheduling | `config/scheduler.py` | `db_backup` @ 04:00 IST, `backup_staleness_check` @ 11:30 IST |
| Alerting | `utils/discord_notifier.py:send_ops_alert()` | Discord OPS channel — failure, corruption, staleness |
| Health | `dashboard/app_fastapi.py:/api/health` | `backup_status` field — stale flag + age + timestamp |
| Volume | `docker-compose.yml` | `./backups:/backups` bind mount (host-visible) |

### Data flow

```
Cron (04:00 IST) → scheduler.run_db_backup() → DBBackup.run()
  → pg_dump -Fc → /backups/re_os_TIMESTAMP.dump
  → verify_backup() → pg_restore --list (validates TOC)
  → enforce_retention(7) → deletes files beyond 7
  → agent_runs table: status='success' + metadata
  → On failure: send_ops_alert('DB_BACKUP_FAILED', ...)

Cron (11:30 IST) → scheduler.run_backup_staleness_check()
  → check_backup_staleness()
  → if >26h old → send_ops_alert('DB_BACKUP_STALE', ...)
```

### Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | — | PostgreSQL connection string |
| `DB_PASSWORD` | — | Fallback password if not in DATABASE_URL |
| `RE_OS_BACKUP_DIR` | `/backups` | Backup directory (configurable for tests) |
