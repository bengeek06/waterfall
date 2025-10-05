# Waterfall 🚀

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)](https://flask.palletsprojects.com/)
[![Next.js](https://img.shields.io/badge/Next.js-13+-black.svg)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://www.docker.com/)
[![Selenium](https://img.shields.io/badge/Selenium-E2E-orange.svg)](https://selenium.dev/)

A modern project management application built with microservices architecture.

## Overview

Waterfall is a comprehensive project management platform featuring:
- **Authentication & Authorization** - Secure user management
- **Identity Management** - User profiles and roles
- **Guardian Service** - Resource protection and access control
- **Web Interface** - Modern Next.js frontend
- **API Documentation** - Interactive Swagger UI

## Architecture

- **Backend**: Python Flask microservices
- **Frontend**: Next.js React application
- **Database**: PostgreSQL
- **API Documentation**: OpenAPI/Swagger
- **Testing**: Selenium + Pytest for E2E tests

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
```

#### Next.js Frontend (Manual Development)

```bash
cd services/web-waterfall
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
docker-compose up -d --build
```

## Service URLs

Once running, access the following services:

| Service | URL | Description |
|---------|-----|-------------|
| **Web App** | http://localhost:3000 | Main application interface |
| **Auth API** | http://localhost:5001 | Authentication service |
| **Identity API** | http://localhost:5002 | Identity management service |
| **Guardian API** | http://localhost:5003 | Resource protection service |
| **Swagger UI** | http://localhost:8081 | Interactive API documentation |
| **pgAdmin** | http://localhost:5050 | Database administration |

### pgAdmin Access
- **Email**: admin@admin.com
- **Password**: admin

### Database Connection (for pgAdmin)
- **Host**: db_service
- **Port**: 5432
- **Username**: staging
- **Password**: password

## API Documentation

Each service provides OpenAPI documentation accessible through Swagger UI:
- **Auth API**: Available in Swagger UI
- **Identity API**: Available in Swagger UI  
- **Guardian API**: Available in Swagger UI

## Testing

### Setup Test Environment

```bash
./scripts/setup-dev.sh
```

### Run Integration Tests

```bash
./scripts/run-tests.sh
```

This script will:
1. Start all services with Docker Compose
2. Wait for services to be ready
3. Run E2E tests with Selenium + Pytest
4. Stop all services

### Manual Test Execution

```bash
# Start services
docker-compose up -d --build

# Run tests manually
cd tests
source venv/bin/activate
python -m pytest -v --tb=short

# Stop services
docker-compose down
```

## Development Workflow

1. **Feature Development**: Work on individual services using manual setup
2. **Integration Testing**: Use Docker Compose for full stack testing
3. **E2E Testing**: Run Selenium tests against the complete environment

## Project Structure

```
waterfall/
├── services/
│   ├── auth_service/          # Authentication microservice (submodule)
│   ├── identity_service/      # Identity management microservice (submodule)
│   ├── guardian_service/      # Resource protection microservice (submodule)
│   └── web-waterfall/         # Next.js frontend (submodule)
├── tests/                     # E2E tests with Selenium (submodule)
├── scripts/                   # Automation scripts
│   ├── setup-dev.sh
│   ├── run-tests.sh
│   └── wait-for-services.sh
├── docker-compose.yml         # Multi-service orchestration
└── init-db.sh                # Database initialization
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests to ensure everything works
5. Submit a pull request

## License

This project is licensed under the AGPL License.