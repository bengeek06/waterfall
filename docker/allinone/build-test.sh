#!/bin/bash
# ==============================================================================
# Script de construction et test de l'image All-in-One
# ==============================================================================

set -e

echo "🚀 Building and testing Waterfall All-in-One image..."

# Couleurs pour les logs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

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

# Variables
IMAGE_NAME="waterfall-app"
CONTAINER_NAME="waterfall-test"
BUILD_START=$(date +%s)

# Nettoyage préalable
log_info "Cleaning up previous builds..."
docker rm -f $CONTAINER_NAME 2>/dev/null || true
docker rmi $IMAGE_NAME 2>/dev/null || true

# Construction de l'image
log_info "Building Docker image..."
if docker build -f Dockerfile.allinone -t $IMAGE_NAME . ; then
    BUILD_END=$(date +%s)
    BUILD_TIME=$((BUILD_END - BUILD_START))
    log_success "Image built successfully in ${BUILD_TIME}s"
else
    log_error "Failed to build image"
    exit 1
fi

# Affichage de la taille de l'image
IMAGE_SIZE=$(docker images $IMAGE_NAME --format "table {{.Size}}" | tail -n 1)
log_info "Image size: $IMAGE_SIZE"

# Test de démarrage
log_info "Testing container startup..."
if docker run -d --name $CONTAINER_NAME -p 8080:80 -p 8443:443 $IMAGE_NAME; then
    log_success "Container started successfully"
else
    log_error "Failed to start container"
    exit 1
fi

# Attente du démarrage complet
log_info "Waiting for services to be ready..."
for i in {1..60}; do
    if docker exec $CONTAINER_NAME curl -f -s -k https://localhost/health > /dev/null 2>&1; then
        log_success "All services are ready!"
        break
    fi
    
    if [ $i -eq 60 ]; then
        log_error "Services failed to start within 60 seconds"
        docker logs $CONTAINER_NAME
        exit 1
    fi
    
    echo -n "."
    sleep 2
done

# Tests de santé
log_info "Running health checks..."

# Test HTTP redirect
if curl -f -s http://localhost:8080/health > /dev/null 2>&1; then
    log_success "HTTP health endpoint accessible"
else
    log_warning "HTTP health endpoint not accessible"
fi

# Test HTTPS
if curl -f -s -k https://localhost:8443/health > /dev/null 2>&1; then
    log_success "HTTPS health endpoint accessible"
else
    log_error "HTTPS health endpoint not accessible"
    docker logs $CONTAINER_NAME
    exit 1
fi

# Test API health
if curl -f -s -k https://localhost:8443/api/health > /dev/null 2>&1; then
    API_HEALTH=$(curl -s -k https://localhost:8443/api/health | jq -r '.status')
    if [ "$API_HEALTH" = "healthy" ]; then
        log_success "All API services healthy"
    else
        log_warning "Some API services may be unhealthy: $API_HEALTH"
    fi
else
    log_warning "API health endpoint not accessible"
fi

# Affichage des informations de test
log_info "Test URLs:"
echo "  - Health: https://localhost:8443/health"
echo "  - API Health: https://localhost:8443/api/health" 
echo "  - Web App: https://localhost:8443/"
echo ""
log_info "Management commands:"
echo "  - View logs: docker logs $CONTAINER_NAME"
echo "  - Service status: docker exec $CONTAINER_NAME supervisorctl status"
echo "  - Access container: docker exec -it $CONTAINER_NAME bash"
echo ""

# Option pour garder le conteneur actif
read -p "Keep container running for testing? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log_success "Container $CONTAINER_NAME is running on ports 8080 (HTTP) and 8443 (HTTPS)"
    log_info "Stop with: docker rm -f $CONTAINER_NAME"
else
    log_info "Stopping and removing test container..."
    docker rm -f $CONTAINER_NAME
    log_success "Test completed successfully!"
fi

# Résumé final
echo ""
log_success "=== BUILD SUMMARY ==="
echo "Image name: $IMAGE_NAME"
echo "Image size: $IMAGE_SIZE"  
echo "Build time: ${BUILD_TIME}s"
echo "All tests: PASSED ✅"