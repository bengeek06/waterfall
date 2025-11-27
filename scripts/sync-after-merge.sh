#!/bin/bash
# Script pour synchroniser staging et develop après le merge des PRs

# Ne pas arrêter sur les erreurs - on veut synchroniser tous les repos possibles
# set -e

WATERFALL_ROOT="/home/benjamin/projects/waterfall-development"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[SYNC]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Liste des repos
REPOS=(
    "services/auth_service"
    "services/identity_service"
    "services/guardian_service"
    "services/storage_service"
    "services/basic_io_service"
    "services/project_service"
    "web"
    "tests"
)

log "🔄 Synchronisation de staging et develop avec main"
echo ""

SUCCESS=0
FAILED=0

for repo_path in "${REPOS[@]}"; do
    log "Syncing $repo_path"
    
    cd "$WATERFALL_ROOT/$repo_path"
    
    # Checkout main et pull
    log "  Updating main branch..."
    if ! git checkout main 2>&1; then
        error "  ✗ Failed to checkout main"
        ((FAILED++))
        cd "$WATERFALL_ROOT"
        continue
    fi
    
    if ! git pull origin main 2>&1; then
        error "  ✗ Failed to pull main"
        ((FAILED++))
        cd "$WATERFALL_ROOT"
        continue
    fi
    
    # Sync staging
    log "  Syncing staging with main..."
    if git checkout staging && git merge main --no-edit && git push origin staging; then
        log "  ✓ staging synced"
    else
        error "  ✗ Failed to sync staging"
        ((FAILED++))
        cd "$WATERFALL_ROOT"
        continue
    fi
    
    # Sync develop
    log "  Syncing develop with main..."
    if git checkout develop && git merge main --no-edit && git push origin develop; then
        log "  ✓ develop synced"
    else
        error "  ✗ Failed to sync develop"
        ((FAILED++))
        cd "$WATERFALL_ROOT"
        continue
    fi
    
    # Back to main
    git checkout main
    log "  ✓ Repository synced"
    ((SUCCESS++))
    
    echo ""
    
    cd "$WATERFALL_ROOT"
done

echo ""
log "📊 Résumé:"
log "  ✓ Success: $SUCCESS"
if [ $FAILED -gt 0 ]; then
    warn "  ✗ Failed: $FAILED"
fi

if [ $SUCCESS -eq ${#REPOS[@]} ]; then
    log "🎉 Tous les repos sont synchronisés!"
    echo ""
    log "📋 Prochaines étapes:"
    log "  1. Mettre à jour les submodules du repo principal:"
    log ""
    log "     cd $WATERFALL_ROOT"
    log "     git submodule update --remote"
    log "     git add services/ web/ tests/"
    log "     git commit -m 'chore: update submodules to main branch'"
    log "     git push origin web_staging"
    log ""
    log "  2. Créer staging et develop dans le repo principal:"
    log ""
    log "     git checkout -b staging"
    log "     git push -u origin staging"
    log "     git checkout -b develop"
    log "     git push -u origin develop"
    log "     git checkout web_staging"
    log ""
    log "  3. Optionnel - Configurer les protections de branches:"
    log "     ./scripts/protect-main-branches.sh"
else
    warn "⚠️  Certains repos n'ont pas pu être synchronisés."
    warn "    Vérifiez manuellement les erreurs ci-dessus"
fi
