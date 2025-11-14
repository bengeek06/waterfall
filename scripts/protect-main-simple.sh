#!/bin/bash
# Script pour configurer les protections de branches (version simplifiée)

# Ne pas arrêter sur les erreurs
# set -e

REPOS=(
    "bengeek06/auth-api-waterfall"
    "bengeek06/identity-api-waterfall"
    "bengeek06/guardian-api-waterfall"
    "bengeek06/storage-api-waterfall"
    "bengeek06/basic-io-api-waterfall"
    "bengeek06/project_api_waterfall"
    "bengeek06/web-waterfall"
    "bengeek06/e2e-waterfall"
)

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[PROTECT]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log "🔒 Configuration des protections de branches"
echo ""

SUCCESS=0
FAILED=0

for repo in "${REPOS[@]}"; do
    repo_name="${repo#*/}"
    log "Protection de main dans $repo_name..."
    
    # Configuration minimale : require PR avant merge
    if gh api \
        --method PUT \
        -H "Accept: application/vnd.github+json" \
        "/repos/$repo/branches/main/protection" \
        --input - <<EOF 2>/dev/null
{
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": true
  },
  "enforce_admins": false,
  "required_status_checks": null,
  "restrictions": null
}
EOF
    then
        log "  ✓ Protégée"
        ((SUCCESS++))
    else
        warn "  ⚠ Erreur (vérifiez manuellement)"
        ((FAILED++))
    fi
    
    echo ""
done

echo ""
log "📊 Résumé:"
log "  ✓ Configurées: $SUCCESS"
if [ $FAILED -gt 0 ]; then
    warn "  ⚠ Erreurs: $FAILED"
fi

echo ""
log "✅ Protection minimale configurée sur toutes les branches main:"
log "   - Require pull request avant merge"
log "   - Les admins peuvent bypass (enforce_admins=false)"
echo ""

info "💡 Pour une protection plus stricte, allez manuellement sur:"
for repo in "${REPOS[@]}"; do
    echo "   https://github.com/$repo/settings/branches"
done
