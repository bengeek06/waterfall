#!/bin/bash
# Script pour merger automatiquement toutes les PRs de migration

# Ne pas arrêter le script sur une erreur - on veut merger toutes les PRs possibles
# set -e

WATERFALL_ROOT="/home/benjamin/projects/waterfall"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[MERGE]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Liste des repos avec leurs branches
declare -A REPOS=(
    ["services/auth_service"]="fix_issues"
    ["services/identity_service"]="fix_issues"
    ["services/guardian_service"]="fix_issues"
    ["services/storage_service"]="fix_issues"
    ["services/basic_io_service"]="fix/issues"
    ["services/project_service"]="feature/integration-tests"
    ["web"]="web_staging"
    ["tests"]="web_staging"
)

log "🚀 Merge automatique de toutes les PRs de migration"
echo ""

MERGED=0
FAILED=0

for repo_path in "${!REPOS[@]}"; do
    branch="${REPOS[$repo_path]}"
    
    log "Merging PR in $repo_path"
    
    cd "$WATERFALL_ROOT/$repo_path"
    
    # Trouver le numéro de la PR pour cette branche
    PR_NUMBER=$(gh pr list --head "$branch" --base main --json number --jq '.[0].number' 2>/dev/null)
    
    if [ -z "$PR_NUMBER" ] || [ "$PR_NUMBER" = "null" ]; then
        # Peut-être déjà mergée, vérifier les PRs mergées récentes
        PR_NUMBER=$(gh pr list --state merged --head "$branch" --base main --json number --jq '.[0].number' 2>/dev/null)
        if [ -z "$PR_NUMBER" ] || [ "$PR_NUMBER" = "null" ]; then
            warn "  No PR found for branch $branch (maybe already merged?)"
            cd "$WATERFALL_ROOT"
            continue
        else
            log "  PR #$PR_NUMBER already merged"
            ((MERGED++))
            cd "$WATERFALL_ROOT"
            continue
        fi
    fi
    
    log "  Found PR #$PR_NUMBER"
    
    # Merger la PR
    if gh pr merge "$PR_NUMBER" --merge --delete-branch 2>&1; then
        log "  ✓ PR #$PR_NUMBER merged successfully"
        ((MERGED++))
    else
        error "  ✗ Failed to merge PR #$PR_NUMBER"
        ((FAILED++))
    fi
    
    echo ""
    
    cd "$WATERFALL_ROOT"
done

echo ""
log "📊 Résumé:"
log "  ✓ Merged: $MERGED"
if [ $FAILED -gt 0 ]; then
    warn "  ✗ Failed: $FAILED"
fi

if [ $MERGED -eq ${#REPOS[@]} ]; then
    log "🎉 Toutes les PRs ont été mergées avec succès!"
    echo ""
    log "📋 Prochaines étapes:"
    log "  1. Synchroniser staging et develop"
    log "  2. Mettre à jour le repo principal waterfall"
    log ""
    log "  Lancez: ./scripts/sync-after-merge.sh"
else
    warn "⚠️  Certaines PRs n'ont pas pu être mergées."
    warn "    Vérifiez manuellement sur GitHub"
fi
