#!/bin/bash
# Script pour vérifier que les tests et pylint passent sur toutes les branches

set +e  # Ne pas arrêter sur erreur

WATERFALL_ROOT="/home/benjamin/projects/waterfall"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[CHECK]${NC} $1"
}

error() {
    echo -e "${RED}[FAIL]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Liste des services Python avec leurs branches
declare -A PYTHON_SERVICES=(
    ["services/auth_service"]="fix_issues"
    ["services/identity_service"]="fix_issues"
    ["services/guardian_service"]="fix_issues"
    ["services/storage_service"]="fix_issues"
    ["services/basic_io_service"]="fix/issues"
    ["services/project_service"]="feature/integration-tests"
)

FAILED_SERVICES=()

log "🔍 Vérification de la qualité du code sur toutes les branches"
echo ""

for service in "${!PYTHON_SERVICES[@]}"; do
    branch="${PYTHON_SERVICES[$service]}"
    
    log "Checking $service (branch: $branch)"
    
    cd "$WATERFALL_ROOT/$service"
    
    # S'assurer d'être sur la bonne branche
    git checkout "$branch" > /dev/null 2>&1
    
    # Vérifier si requirements-dev.txt existe
    if [ ! -f "requirements-dev.txt" ]; then
        warn "  No requirements-dev.txt found, skipping"
        cd "$WATERFALL_ROOT"
        continue
    fi
    
    # Utiliser l'environnement virtuel existant
    if [ -d "venv" ]; then
        log "  Using existing venv..."
        source venv/bin/activate
    else
        warn "  No venv found, creating temporary one..."
        python3 -m venv .venv_check > /dev/null 2>&1
        source .venv_check/bin/activate
        pip install -q -r requirements.txt > /dev/null 2>&1
        pip install -q -r requirements-dev.txt > /dev/null 2>&1
    fi
    
    # S'assurer que pylint est installé
    pip install -q pylint > /dev/null 2>&1 || true
    
    # Lancer pylint (rapide - juste vérifier les erreurs)
    log "  Running pylint on app/..."
    PYLINT_OUTPUT=$(pylint app/ --errors-only 2>&1)
    PYLINT_EXIT=$?
    if [ $PYLINT_EXIT -eq 0 ]; then
        log "  ✓ Pylint: no errors"
    else
        error "  ✗ Pylint: errors found"
        echo "$PYLINT_OUTPUT" | head -20
        FAILED_SERVICES+=("$service:pylint")
    fi
    
    echo ""
    
    # Lancer les tests (rapide)
    log "  Running tests..."
    if pytest tests/ -x --tb=short -q 2>&1 | tail -20; then
        log "  ✓ Tests passed"
    else
        error "  ✗ Tests failed"
        FAILED_SERVICES+=("$service:tests")
    fi
    
    deactivate
    
    # Nettoyer seulement si on a créé un venv temporaire
    if [ -d ".venv_check" ]; then
        rm -rf .venv_check
    fi
    
    echo ""
    echo "---"
    echo ""
    
    cd "$WATERFALL_ROOT"
done

# Résumé
echo ""
if [ ${#FAILED_SERVICES[@]} -eq 0 ]; then
    log "✅ Tous les services sont OK! Vous pouvez merger les PRs en toute sécurité."
else
    error "❌ Certains services ont des problèmes:"
    for failure in "${FAILED_SERVICES[@]}"; do
        error "  - $failure"
    done
    echo ""
    warn "⚠️  Recommandation: Corriger les problèmes avant de merger les PRs"
    warn "    Ou merger quand même et corriger après (en créant de nouvelles PRs)"
fi
