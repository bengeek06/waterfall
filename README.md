# Waterfall 🚀

[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1+-green.svg)](https://flask.palletsprojects.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16+-black.svg)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://www.docker.com/)
[![MinIO](https://img.shields.io/badge/MinIO-S3-red.svg)](https://min.io/)
[![Selenium](https://img.shields.io/badge/Selenium-E2E-orange.svg)](https://selenium.dev/)

A modern project management application built with microservices architecture.

## Overview

Waterfall is a comprehensive project management platform featuring:
- **Authentication & Authorization** - Secure user management with JWT
- **Identity Management** - User profiles, companies, and organizational units
- **Guardian Service** - Role-based access control (RBAC) with policies and permissions
- **Basic IO Service** - Core business operations and data management
- **Storage Service** - File storage with S3-compatible MinIO backend
- **Web Interface** - Modern Next.js 16 frontend with Turbopack
- **API Documentation** - Interactive Swagger UI for all services

## Architecture

- **Backend**: Python 3.13 Flask microservices
- **Frontend**: Next.js 16 with Turbopack
- **Database**: PostgreSQL 16
- **Storage**: MinIO (S3-compatible object storage)
- **API Documentation**: OpenAPI 3.0/Swagger
- **Testing**: Selenium + Pytest for E2E tests
- **Container Orchestration**: Docker Compose

## Getting Started

### 1. Clone the Repository

```bash
git clone git@github.com:bengeek06/waterfall.git
cd waterfall
```

### 2. Initialize Submodules

```bash
git submodule update --init --recursive
```

### 3. Development Setup

#### Quick Start (Recommended)

Use the provided scripts to start all backend services:

```bash
# Start all backend services (recommended for development)
./scripts/run-backend.sh
```

This will start:
- PostgreSQL database with all 5 databases
- All microservices (Auth, Identity, Guardian, Basic IO, Storage)
- MinIO object storage
- PgAdmin for database management
- Swagger UI for API documentation

#### Python Services (Manual Development)

Each service can be run independently for development:

```bash
# Auth Service
cd services/auth_service
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask run --port=5001

# Identity Service
cd services/identity_service
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask run --port=5002

# Guardian Service
cd services/guardian_service
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask run --port=5003

# Basic IO Service
cd services/basic_io_service
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask run --port=5004

# Storage Service
cd services/storage_service
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask run --port=5005
```

#### Next.js Frontend (Manual Development)

```bash
cd web
npm install
npm run dev
# Access at http://localhost:3000
```

#### E2E Tests Environment

```bash
cd tests
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Docker Compose Setup

Launch all services with Docker Compose:

```bash
# Backend services only (recommended)
docker compose -f compose/docker-compose.backend.yml up -d --build

# Or use the script
./scripts/run-backend.sh
```

## Service URLs

Once running, access the following services:

| Service | URL | Description |
|---------|-----|-------------|
| **Web App** | http://localhost:3000 | Main application interface |
| **Auth API** | http://localhost:5001 | Authentication service |
| **Identity API** | http://localhost:5002 | Identity management service |
| **Guardian API** | http://localhost:5003 | Resource protection service |
| **Basic IO API** | http://localhost:5004 | Core business operations |
| **Storage API** | http://localhost:5005 | File storage service |
| **Swagger UI** | http://localhost:8081 | Interactive API documentation |
| **pgAdmin** | http://localhost:5050 | Database administration |
| **MinIO Console** | http://localhost:9001 | Object storage admin |
| **MinIO API** | http://localhost:9000 | S3-compatible API |

### pgAdmin Access
- **Email**: admin@admin.com
- **Password**: admin

### Database Connection (for pgAdmin)
- **Host**: db_service
- **Port**: 5432
- **Username**: staging
- **Password**: password
- **Databases**: auth_staging, identity_staging, guardian_staging, basic_io_staging, storage_staging

### MinIO Access
- **Username**: minioadmin
- **Password**: minioadmin

## API Documentation

Each service provides OpenAPI 3.0 documentation accessible through Swagger UI at http://localhost:8081:
- **Auth API**: Authentication and token management
- **Identity API**: Users, companies, customers, and organizational units
- **Guardian API**: Roles, policies, permissions, and access control
- **Basic IO API**: Core business operations
- **Storage API**: File upload, download, and management

## Testing

### Run Complete Test Suite

```bash
./scripts/run-tests.sh
```

This script will:
1. Clean up any existing test containers
2. Build fresh Docker images
3. Start all services (PostgreSQL, all microservices, MinIO, Web UI)
4. Wait for services to be ready
5. Initialize the application
6. Run 95 API tests + 6 UI tests
7. Display detailed results
8. Clean up containers

### Test Coverage

- **API Tests** (95 tests):
  - Auth Service: 16 tests (login, tokens, JWT validation)
  - Identity Service: 49 tests (users, companies, positions, etc.)
  - Guardian Service: 30 tests (roles, policies, permissions, access control)
  
- **UI Tests** (6 tests):
  - Login flow and authentication
  - Session management
  - Protected routes

### Manual Test Execution

```bash
# Start services
docker compose -f compose/docker-compose.test.yml up -d --build

# Run tests manually
cd tests
source venv/bin/activate
python -m pytest -v --tb=short api/
python -m pytest -v --tb=short ui/

# Stop services
docker compose -f compose/docker-compose.test.yml down
```

## Database Management

### Backup All Databases

```bash
# Backup to default location (./backups/)
./scripts/backup-databases.sh

# Backup to custom location
./scripts/backup-databases.sh /path/to/backup/directory
```

Creates timestamped backups of all 5 databases with a manifest file.

### Restore Databases

```bash
# Restore from latest backup
./scripts/restore-databases.sh

# Restore from specific backup
./scripts/restore-databases.sh ./backups/backup_20241106_143022/
```

⚠️ **Warning**: This will DROP all existing databases and restore from backup!

## Development Workflow

1. **Feature Development**: 
   - Work on individual services using manual setup or Docker Compose
   - Use `./scripts/run-backend.sh` for quick backend environment setup
   
2. **Database Management**:
   - Regular backups with `./scripts/backup-databases.sh`
   - Quick restore with `./scripts/restore-databases.sh`
   
3. **Testing**: 
   - Run full test suite with `./scripts/run-tests.sh`
   - Tests include API integration and UI end-to-end tests
   
4. **API Development**:
   - Access Swagger UI at http://localhost:8081 for interactive API testing
   - Each service has complete OpenAPI 3.0 documentation

## Key Features

### Authentication Service
- JWT-based authentication
- Token refresh and validation
- Secure password hashing
- Session management

### Identity Service
- User management
- Company and customer profiles
- Organizational units and hierarchy
- Position management
- Subcontractor tracking

### Guardian Service
- Role-Based Access Control (RBAC)
- Custom policies and permissions
- Fine-grained access rules
- User-role assignments

### Basic IO Service
- Core business data operations
- Data import/export in JSON and CSV formats
- CRUD operations for entities
- Business logic processing
- Batch data processing

### Storage Service
- S3-compatible file storage via MinIO
- File upload and download
- Metadata management
- Access control integration

## Project Structure

```
waterfall/
├── services/
│   ├── auth_service/          # Authentication microservice (submodule)
│   ├── identity_service/      # Identity management microservice (submodule)
│   ├── guardian_service/      # RBAC and access control microservice (submodule)
│   ├── basic_io_service/      # Core business operations (submodule)
│   └── storage_service/       # File storage microservice (submodule)
├── web/                       # Next.js 16 frontend (submodule)
├── tests/                     # E2E tests with Selenium (submodule)
├── scripts/                   # Automation scripts
│   ├── run-backend.sh         # Start all backend services
│   ├── run-tests.sh           # Run complete test suite
│   ├── backup-databases.sh    # Backup all databases
│   ├── restore-databases.sh   # Restore databases from backup
│   ├── wait-for-services.sh   # Wait for services to be ready
│   └── init-db.sh             # Database initialization
├── compose/                   # Docker Compose configurations
│   ├── docker-compose.yml         # Main configuration
│   ├── docker-compose.backend.yml # Backend services only
│   └── docker-compose.test.yml    # Test environment
└── backups/                   # Database backups (gitignored)
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests to ensure everything works
5. Submit a pull request

## License

This project is licensed under the AGPL License.