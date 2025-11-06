# Waterfall Scripts

This directory contains utility scripts for managing the Waterfall application.

## Database Backup & Restore

### Backup Databases

Creates backups of all Waterfall databases (auth, identity, guardian, basic_io, storage).

```bash
# Backup to default location (./backups/)
./scripts/backup-databases.sh

# Backup to custom location
./scripts/backup-databases.sh /path/to/backup/directory
```

**Features:**
- Backs up all 5 databases
- Creates timestamped backup directories
- Generates a manifest file with backup information
- Creates a symlink to the latest backup
- Color-coded output for easy monitoring

**Default backup location:** `./backups/backup_YYYYMMDD_HHMMSS/`

### Restore Databases

Restores all databases from a backup directory.

```bash
# Restore from latest backup
./scripts/restore-databases.sh

# Restore from specific backup
./scripts/restore-databases.sh ./backups/backup_20241106_143022/

# Restore from custom location
./scripts/restore-databases.sh /path/to/backup/directory
```

**Features:**
- Restores all databases from backup
- Shows backup manifest information
- Requires confirmation before proceeding (destructive operation)
- Drops and recreates databases before restore
- Color-coded output for easy monitoring

**⚠️ Warning:** This operation will **DROP** all existing databases and restore from backup. All current data will be lost!

**Note:** After restore, restart backend services to apply any pending migrations:
```bash
docker compose -f compose/docker-compose.backend.yml restart
```

## Service Management

### Run Backend Services

Starts all backend services with development tools.

```bash
./scripts/run-backend.sh
```

**Services started:**
- PostgreSQL Database (port 5432)
- Auth Service (port 5001)
- Identity Service (port 5002)
- Guardian Service (port 5003)
- Basic IO Service (port 5004)
- Storage Service (port 5005)
- MinIO (ports 9000, 9001)
- PgAdmin (port 5050)
- Swagger UI (port 8081)

### Run Tests

Runs the complete test suite with fresh containers.

```bash
./scripts/run-tests.sh
```

**Features:**
- Starts test environment with clean databases
- Runs API and UI tests
- Automatically cleans up after completion
- Exit code reflects test results

### Wait for Services

Utility script that waits for all services to be ready.

```bash
# Used by other scripts, can also be called directly
COMPOSE_FILE=compose/docker-compose.backend.yml ./scripts/wait-for-services.sh
```

## Database Management

### Initialize Databases

Creates all required databases when PostgreSQL container starts.

**Databases created:**
- auth_staging
- identity_staging
- guardian_staging
- basic_io_staging
- storage_staging

This script runs automatically via Docker Compose volume mount.

## Prerequisites

All scripts require:
- Docker and Docker Compose installed
- Backend services running (except for run-backend.sh)
- Sufficient disk space for backups

## Backup Best Practices

1. **Regular backups:** Schedule regular backups using cron
   ```bash
   # Example: Daily backup at 2 AM
   0 2 * * * /path/to/waterfall/scripts/backup-databases.sh
   ```

2. **Backup retention:** Keep multiple backups and implement a retention policy
   ```bash
   # Example: Keep only backups from the last 7 days
   find ./backups -name "backup_*" -type d -mtime +7 -exec rm -rf {} \;
   ```

3. **Off-site backups:** Copy important backups to remote storage
   ```bash
   # Example: Sync to remote server
   rsync -avz ./backups/latest/ user@backup-server:/backups/waterfall/
   ```

4. **Test restores:** Regularly test your restore process to ensure backups are valid

## Troubleshooting

### Database container not running

```
❌ Error: Database container is not running
```

**Solution:** Start the backend services first:
```bash
./scripts/run-backend.sh
```

### Backup directory not found

```
❌ Error: Backup directory does not exist
```

**Solution:** Check available backups:
```bash
ls -la ./backups/
```

### Permission denied

```
Permission denied: ./scripts/backup-databases.sh
```

**Solution:** Make the script executable:
```bash
chmod +x ./scripts/backup-databases.sh
chmod +x ./scripts/restore-databases.sh
```

## Notes

- Backups are stored as plain SQL files for maximum compatibility
- Each database is backed up independently
- The manifest file contains metadata about the backup
- Restore operations require explicit confirmation to prevent accidental data loss
- After restore, services should be restarted to ensure consistency
