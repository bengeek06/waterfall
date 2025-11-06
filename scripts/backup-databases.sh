#!/bin/bash
set -e

# Script to backup all Waterfall databases
# Usage: ./backup-databases.sh [backup_directory]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${1:-$PROJECT_ROOT/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Database configuration
DB_CONTAINER="compose-db_service-1"
DB_USER="staging"
DB_PASSWORD="password"
DATABASES=("auth_staging" "identity_staging" "guardian_staging" "basic_io_staging" "storage_staging")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "🗄️  Waterfall Database Backup Tool"
echo "=================================="
echo ""

# Check if Docker Compose is running
if ! docker ps | grep -q "$DB_CONTAINER"; then
    echo -e "${RED}❌ Error: Database container is not running${NC}"
    echo "Please start the backend services first with: ./scripts/run-backend.sh"
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"
BACKUP_SUBDIR="$BACKUP_DIR/backup_$TIMESTAMP"
mkdir -p "$BACKUP_SUBDIR"

echo "📁 Backup directory: $BACKUP_SUBDIR"
echo ""

# Backup each database
success_count=0
failed_count=0

for db in "${DATABASES[@]}"; do
    echo -n "💾 Backing up $db... "
    
    backup_file="$BACKUP_SUBDIR/${db}.sql"
    
    if docker exec -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" \
        pg_dump -U "$DB_USER" -d "$db" -F p -f "/tmp/${db}.sql" 2>/dev/null && \
       docker cp "$DB_CONTAINER:/tmp/${db}.sql" "$backup_file" 2>/dev/null && \
       docker exec "$DB_CONTAINER" rm "/tmp/${db}.sql" 2>/dev/null; then
        
        # Get file size
        size=$(du -h "$backup_file" | cut -f1)
        echo -e "${GREEN}✓ Success${NC} ($size)"
        ((success_count++))
    else
        echo -e "${RED}✗ Failed${NC}"
        ((failed_count++))
    fi
done

echo ""
echo "=================================="
echo "📊 Backup Summary:"
echo "   ✓ Successful: $success_count"
echo "   ✗ Failed: $failed_count"
echo "   📁 Location: $BACKUP_SUBDIR"
echo ""

# Create a manifest file
cat > "$BACKUP_SUBDIR/manifest.txt" << EOF
Waterfall Database Backup
========================
Timestamp: $(date '+%Y-%m-%d %H:%M:%S')
Databases: ${DATABASES[*]}
Successful: $success_count
Failed: $failed_count
EOF

if [ $failed_count -eq 0 ]; then
    echo -e "${GREEN}✅ All databases backed up successfully!${NC}"
    
    # Create a symlink to latest backup
    ln -sfn "backup_$TIMESTAMP" "$BACKUP_DIR/latest"
    echo "🔗 Symlink created: $BACKUP_DIR/latest -> backup_$TIMESTAMP"
    exit 0
else
    echo -e "${YELLOW}⚠️  Backup completed with errors${NC}"
    exit 1
fi
