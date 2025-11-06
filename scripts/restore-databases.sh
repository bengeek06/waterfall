#!/bin/bash
set -e

# Script to restore all Waterfall databases
# Usage: ./restore-databases.sh [backup_directory]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEFAULT_BACKUP_DIR="$PROJECT_ROOT/backups/latest"

# Database configuration
DB_CONTAINER="compose-db_service-1"
DB_USER="staging"
DB_PASSWORD="password"
DATABASES=("auth_staging" "identity_staging" "guardian_staging" "basic_io_staging" "storage_staging")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "🔄 Waterfall Database Restore Tool"
echo "==================================="
echo ""

# Check if Docker Compose is running
if ! docker ps | grep -q "$DB_CONTAINER"; then
    echo -e "${RED}❌ Error: Database container is not running${NC}"
    echo "Please start the backend services first with: ./scripts/run-backend.sh"
    exit 1
fi

# Determine backup directory
if [ -z "$1" ]; then
    BACKUP_DIR="$DEFAULT_BACKUP_DIR"
    echo -e "${BLUE}ℹ️  No backup directory specified, using latest backup${NC}"
else
    BACKUP_DIR="$1"
fi

# Check if backup directory exists
if [ ! -d "$BACKUP_DIR" ]; then
    echo -e "${RED}❌ Error: Backup directory does not exist: $BACKUP_DIR${NC}"
    echo ""
    echo "Available backups:"
    if [ -d "$PROJECT_ROOT/backups" ]; then
        ls -1dt "$PROJECT_ROOT/backups"/backup_* 2>/dev/null || echo "  No backups found"
    else
        echo "  No backups directory found"
    fi
    exit 1
fi

echo "📁 Restore from: $BACKUP_DIR"
echo ""

# Check manifest if exists
if [ -f "$BACKUP_DIR/manifest.txt" ]; then
    echo -e "${BLUE}📄 Backup Information:${NC}"
    cat "$BACKUP_DIR/manifest.txt" | grep -E "Timestamp|Databases|Successful"
    echo ""
fi

# Confirmation prompt
echo -e "${YELLOW}⚠️  WARNING: This will DROP and recreate all databases!${NC}"
echo -e "${YELLOW}   All current data will be lost!${NC}"
echo ""
read -p "Are you sure you want to continue? (yes/no): " -r
echo ""

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Restore cancelled."
    exit 0
fi

# Restore each database
success_count=0
failed_count=0

for db in "${DATABASES[@]}"; do
    backup_file="$BACKUP_DIR/${db}.sql"
    
    if [ ! -f "$backup_file" ]; then
        echo -e "${YELLOW}⚠️  Skipping $db (backup file not found)${NC}"
        ((failed_count++))
        continue
    fi
    
    echo -n "🔄 Restoring $db... "
    
    # Drop and recreate database
    if docker exec -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" \
        psql -U "$DB_USER" -d staging -c "DROP DATABASE IF EXISTS $db;" 2>/dev/null && \
       docker exec -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" \
        psql -U "$DB_USER" -d staging -c "CREATE DATABASE $db;" 2>/dev/null && \
       docker exec -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" \
        psql -U "$DB_USER" -d staging -c "GRANT ALL PRIVILEGES ON DATABASE $db TO $DB_USER;" 2>/dev/null; then
        
        # Copy backup file to container and restore
        if docker cp "$backup_file" "$DB_CONTAINER:/tmp/${db}.sql" 2>/dev/null && \
           docker exec -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" \
            psql -U "$DB_USER" -d "$db" -f "/tmp/${db}.sql" >/dev/null 2>&1 && \
           docker exec "$DB_CONTAINER" rm "/tmp/${db}.sql" 2>/dev/null; then
            
            echo -e "${GREEN}✓ Success${NC}"
            ((success_count++))
        else
            echo -e "${RED}✗ Failed (restore)${NC}"
            ((failed_count++))
        fi
    else
        echo -e "${RED}✗ Failed (recreate)${NC}"
        ((failed_count++))
    fi
done

echo ""
echo "==================================="
echo "📊 Restore Summary:"
echo "   ✓ Successful: $success_count"
echo "   ✗ Failed: $failed_count"
echo ""

if [ $failed_count -eq 0 ]; then
    echo -e "${GREEN}✅ All databases restored successfully!${NC}"
    echo ""
    echo -e "${YELLOW}⚠️  Important: Please restart the backend services to apply migrations:${NC}"
    echo "   docker compose -f compose/docker-compose.backend.yml restart"
    exit 0
else
    echo -e "${YELLOW}⚠️  Restore completed with errors${NC}"
    exit 1
fi
