#!/bin/bash
# Script pour créer automatiquement toutes les PRs de migration

set -e

WATERFALL_ROOT="/home/benjamin/projects/waterfall-development"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[PR]${NC} $1"
}

# Liste des repos avec leurs infos
declare -a REPOS=(
    "services/auth_service:fix_issues:chore: merge fix_issues into main (migration)"
    "services/identity_service:fix_issues:chore: merge fix_issues into main (migration)"
    "services/guardian_service:fix_issues:chore: merge fix_issues into main (migration)"
    "services/storage_service:fix_issues:chore: merge fix_issues into main (migration)"
    "services/basic_io_service:fix/issues:chore: merge fix/issues into main (migration)"
    "services/project_service:feature/integration-tests:chore: merge feature/integration-tests into main (migration)"
    "web:web_staging:chore: merge web_staging into main (migration)"
    "tests:web_staging:chore: merge web_staging into main (migration)"
)

PR_BODY="Migration automatique vers le workflow unifié (main/staging/develop).

Changements inclus:
- Documentation CONTRIBUTING.md avec standards pylint
- Améliorations et corrections diverses
- Création des branches staging et develop

Fait partie de la migration globale du projet vers un workflow Git standardisé.

Voir: /home/benjamin/projects/waterfall-development/prs-to-create.md pour plus de détails."

log "🚀 Création automatique de toutes les PRs de migration"
echo ""

for repo_info in "${REPOS[@]}"; do
    IFS=':' read -r path branch title <<< "$repo_info"
    
    log "Creating PR for $path ($branch → main)"
    
    cd "$WATERFALL_ROOT/$path"
    
    # Créer la PR
    if gh pr create --base main --head "$branch" \
        --title "$title" \
        --body "$PR_BODY" 2>&1; then
        log "  ✓ PR créée avec succès"
    else
        log "  ⚠ Erreur ou PR déjà existante"
    fi
    
    echo ""
    
    cd "$WATERFALL_ROOT"
done

log "🎉 Toutes les PRs ont été créées!"
echo ""
log "📋 Prochaines étapes:"
log "  1. Consulter les PRs sur GitHub"
log "  2. Merger les PRs (manuellement ou avec gh pr merge)"
log "  3. Suivre les instructions post-merge dans prs-to-create.md"
