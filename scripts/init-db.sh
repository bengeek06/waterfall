#!/bin/bash
set -e

echo "Creating additional databases..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE auth_staging;
    CREATE DATABASE identity_staging;
    CREATE DATABASE guardian_staging;
    
    GRANT ALL PRIVILEGES ON DATABASE auth_staging TO $POSTGRES_USER;
    GRANT ALL PRIVILEGES ON DATABASE identity_staging TO $POSTGRES_USER;
    GRANT ALL PRIVILEGES ON DATABASE guardian_staging TO $POSTGRES_USER;
EOSQL

echo "Database initialization completed successfully"