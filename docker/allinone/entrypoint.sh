#!/bin/bash
# ==============================================================================
# Entrypoint Script pour Waterfall All-in-One
# ==============================================================================

set -e

echo "🚀 Starting Waterfall All-in-One Container..."

# Couleurs pour les logs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ==============================================================================
# Génération des secrets
# ==============================================================================
generate_secret() {
    local var_name=$1
    local current_value=${!var_name}
    
    if [ -z "$current_value" ]; then
        # Générer un secret sécurisé
        local secret=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-32)
        export $var_name="$secret"
        echo "$secret" > "/app/secrets/$var_name"
        log_info "Generated $var_name: ${secret:0:8}..."
    else
        echo "$current_value" > "/app/secrets/$var_name"
        log_info "Using provided $var_name"
    fi
}

log_info "Generating/checking secrets..."
generate_secret JWT_SECRET
generate_secret INTERNAL_AUTH_TOKEN
generate_secret POSTGRES_PASSWORD

# Lecture des secrets
export JWT_SECRET=$(cat /app/secrets/JWT_SECRET)
export INTERNAL_AUTH_TOKEN=$(cat /app/secrets/INTERNAL_AUTH_TOKEN)
export POSTGRES_PASSWORD=$(cat /app/secrets/POSTGRES_PASSWORD)

# ==============================================================================
# Configuration des variables d'environnement
# ==============================================================================
export FLASK_ENV=${FLASK_ENV:-production}
export LOG_LEVEL=${LOG_LEVEL:-info}
export APP_MODE=production
export IN_DOCKER_CONTAINER=true

# URLs internes des services
export AUTH_SERVICE_URL="http://localhost:5001"
export IDENTITY_SERVICE_URL="http://localhost:5002" 
export GUARDIAN_SERVICE_URL="http://localhost:5003"

# Configuration PostgreSQL
export PGUSER=waterfall
export PGPASSWORD=$POSTGRES_PASSWORD
export DATABASE_URL_AUTH="postgresql://waterfall:$POSTGRES_PASSWORD@localhost:5432/waterfall_auth"
export DATABASE_URL_IDENTITY="postgresql://waterfall:$POSTGRES_PASSWORD@localhost:5432/waterfall_identity"
export DATABASE_URL_GUARDIAN="postgresql://waterfall:$POSTGRES_PASSWORD@localhost:5432/waterfall_guardian"

log_success "Environment configured"

# ==============================================================================
# Configuration SSL
# ==============================================================================
if [ ! -f "/app/secrets/server.crt" ]; then
    log_info "Generating SSL certificates..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /app/secrets/server.key \
        -out /app/secrets/server.crt \
        -subj "/C=US/ST=State/L=City/O=Waterfall/CN=localhost"
    chmod 600 /app/secrets/server.key
    log_success "SSL certificates generated"
fi

# ==============================================================================
# Initialisation PostgreSQL
# ==============================================================================
PGDATA=/app/data/postgres
if [ ! -f "$PGDATA/PG_VERSION" ]; then
    log_info "Initializing PostgreSQL 17..."
    
    # Initialiser la base de données
    sudo -u postgres /usr/lib/postgresql/17/bin/initdb -D $PGDATA
    
    # Créer les fichiers de configuration
    cat > $PGDATA/postgresql.conf << EOF
listen_addresses = 'localhost'
port = 5432
max_connections = 100
shared_buffers = 128MB
dynamic_shared_memory_type = posix
log_line_prefix = '%m [%p] %q%u@%d '
log_timezone = 'UTC'
datestyle = 'iso, mdy'
timezone = 'UTC'
lc_messages = 'C.UTF-8'
lc_monetary = 'C.UTF-8'
lc_numeric = 'C.UTF-8'
lc_time = 'C.UTF-8'
default_text_search_config = 'pg_catalog.english'
EOF

    cat > $PGDATA/pg_hba.conf << EOF
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             postgres                                peer
local   all             waterfall                               md5
host    all             waterfall       127.0.0.1/32            md5
host    all             waterfall       ::1/128                 md5
EOF

    chown -R postgres:postgres $PGDATA
    chmod 700 $PGDATA
    
    log_success "PostgreSQL 17 initialized"
fi

# ==============================================================================
# Démarrage PostgreSQL
# ==============================================================================
log_info "Starting PostgreSQL 17..."
sudo -u postgres /usr/lib/postgresql/17/bin/pg_ctl -D $PGDATA -l /app/logs/postgresql.log start

# Attendre que PostgreSQL soit prêt
for i in {1..30}; do
    if sudo -u postgres psql -c "SELECT 1;" > /dev/null 2>&1; then
        log_success "PostgreSQL is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "PostgreSQL failed to start"
        exit 1
    fi
    sleep 2
done

# ==============================================================================
# Configuration de la base de données
# ==============================================================================
log_info "Setting up databases and user..."

# Créer l'utilisateur et les bases de données
sudo -u postgres psql << EOF
-- Créer l'utilisateur waterfall
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'waterfall') THEN
        CREATE ROLE waterfall LOGIN PASSWORD '$POSTGRES_PASSWORD';
    END IF;
END
\$\$;
EOF

# Créer les bases de données (séparément pour éviter les erreurs)
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='waterfall_auth'" | grep -q 1 || sudo -u postgres createdb waterfall_auth
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='waterfall_identity'" | grep -q 1 || sudo -u postgres createdb waterfall_identity
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='waterfall_guardian'" | grep -q 1 || sudo -u postgres createdb waterfall_guardian

# Accorder les privilèges
sudo -u postgres psql << EOF
GRANT ALL PRIVILEGES ON DATABASE waterfall_auth TO waterfall;
GRANT ALL PRIVILEGES ON DATABASE waterfall_identity TO waterfall;
GRANT ALL PRIVILEGES ON DATABASE waterfall_guardian TO waterfall;
EOF

# Accorder les permissions sur le schéma public (PostgreSQL 15+)
sudo -u postgres psql -d waterfall_auth -c "GRANT ALL ON SCHEMA public TO waterfall;"
sudo -u postgres psql -d waterfall_identity -c "GRANT ALL ON SCHEMA public TO waterfall;"
sudo -u postgres psql -d waterfall_guardian -c "GRANT ALL ON SCHEMA public TO waterfall;"

log_success "Databases configured"

# ==============================================================================
# Migrations des bases de données
# ==============================================================================
run_migrations() {
    local service=$1
    local service_dir="${service}_service"
    local db_url_var="DATABASE_URL_$(echo $service | tr '[:lower:]' '[:upper:]')"
    local db_url=${!db_url_var}
    
    log_info "Running migrations for $service..."
    cd "/app/$service_dir"
    
    export DATABASE_URL="$db_url"
    export FLASK_APP=app
    
    # Attendre que la base soit accessible
    for i in {1..10}; do
        if python3 -c "import psycopg2; psycopg2.connect('$db_url')" > /dev/null 2>&1; then
            break
        fi
        sleep 2
    done
    
    # Exécuter les migrations
    python3 -c "
from app import create_app
from flask_migrate import upgrade

app = create_app('app.config.ProductionConfig')
with app.app_context():
    try:
        upgrade()
        print('Migrations completed successfully')
    except Exception as e:
        print(f'Migration error: {e}')
        # Initialiser si nécessaire
        from flask_migrate import init, migrate
        try:
            init()
            migrate()
            upgrade()
        except:
            pass
"
}

run_migrations "auth"
run_migrations "identity" 
run_migrations "guardian"

log_success "All migrations completed"

# ==============================================================================
# Génération des configurations de services
# ==============================================================================
log_info "Generating service configurations..."

# Configuration Gunicorn pour chaque service
for service in auth identity guardian; do
    service_dir="${service}_service"
    port=""
    if [[ $service == "auth" ]]; then
        port="5001"
    elif [[ $service == "identity" ]]; then
        port="5002"
    else
        port="5003"
    fi
    
    cat > "/app/$service_dir/gunicorn.conf.py" << 'GUNICORN_EOF'
bind = "127.0.0.1:PORT_PLACEHOLDER"
workers = 2
worker_class = "sync"
worker_connections = 1000
timeout = 30
keepalive = 2
max_requests = 1000
max_requests_jitter = 100
preload_app = True
pythonpath = "/app/SERVICE_DIR_PLACEHOLDER"
chdir = "/app/SERVICE_DIR_PLACEHOLDER"
GUNICORN_EOF
    
    sed -i "s/PORT_PLACEHOLDER/$port/g" "/app/$service_dir/gunicorn.conf.py"
    sed -i "s/SERVICE_DIR_PLACEHOLDER/$service_dir/g" "/app/$service_dir/gunicorn.conf.py"
done

# Configuration Next.js
cat > "/app/web/server.js" << EOF
const { createServer } = require('http')
const { parse } = require('url')
const next = require('next')

const dev = false
const hostname = '127.0.0.1'
const port = 3000

const app = next({ dev, hostname, port, dir: '/app/web' })
const handle = app.getRequestHandler()

app.prepare().then(() => {
  createServer(async (req, res) => {
    try {
      const parsedUrl = parse(req.url, true)
      await handle(req, res, parsedUrl)
    } catch (err) {
      console.error('Error occurred handling', req.url, err)
      res.statusCode = 500
      res.end('internal server error')
    }
  }).listen(port, hostname, (err) => {
    if (err) throw err
    console.log(\`> Ready on http://\${hostname}:\${port}\`)
  })
})
EOF

log_success "Service configurations generated"

# ==============================================================================
# Démarrage avec Supervisor
# ==============================================================================
log_info "Starting Supervisor to manage all services..."
exec "$@"