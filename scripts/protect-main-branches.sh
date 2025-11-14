#!/bin/bash
# Script pour configurer les branch protections sur tous les repos

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[PROTECT]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Liste des repos
declare -a REPOS=(
    "bengeek06/auth-api-waterfall"
    "bengeek06/identity-api-waterfall"
    "bengeek06/guardian-api-waterfall"
    "bengeek06/storage-api-waterfall"
    "bengeek06/basic-io-api-waterfall"
    "bengeek06/project_api_waterfall"
    "bengeek06/web-waterfall"
    "bengeek06/e2e-waterfall"
)

log "🔒 Configuration des branch protections pour main"
echo ""

for repo in "${REPOS[@]}"; do
    log "Protecting main branch in $repo"
    
    # Configuration de protection avec GitHub CLI
    gh api \
        --method PUT \
        -H "Accept: application/vnd.github+json" \
        "/repos/$repo/branches/main/protection" \
        -f required_status_checks='{"strict":true,"contexts":["build","test"]}' \
        -f enforce_admins=false \
        -f required_pull_request_reviews='{"required_approving_review_count":0}' \
        -f restrictions=null \
        -f allow_force_pushes=false \
        -f allow_deletions=false \
        2>&1 && log "  ✓ Protection configurée" || warn "  ⚠ Erreur (peut-être déjà configuré)"
    
    echo ""
done

log "✅ Configuration terminée"
echo ""
log "⚠️  IMPORTANT: Les PRs ne pourront être mergées que si:"
log "   - Les GitHub Actions passent (build + test)"
log "   - Ou vous mergez manuellement en tant qu'admin"
