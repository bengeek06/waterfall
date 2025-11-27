#!/bin/bash
# Script de migration vers le workflow unifié (main/staging/develop)

set -e  # Arrêter en cas d'erreur

WATERFALL_ROOT="/home/benjamin/projects/waterfall"
LOG_FILE="$WATERFALL_ROOT/migration.log"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

# Initialiser le log
echo "=== Migration started at $(date) ===" > "$LOG_FILE"

log "🚀 Début de la migration vers le workflow unifié"

# Liste des sous-modules avec leurs branches actuelles
declare -A SUBMODULES=(
    ["services/auth_service"]="fix_issues"
    ["services/identity_service"]="fix_issues"
    ["services/guardian_service"]="fix_issues"
    ["services/storage_service"]="fix_issues"
    ["services/basic_io_service"]="fix/issues"
    ["services/project_service"]="feature/integration-tests"
    ["web"]="web_staging"
    ["tests"]="web_staging"
)

# Étape 1: Créer les branches staging et develop dans tous les sous-modules
log "📋 Étape 1/4: Création des branches staging et develop"

for submodule in "${!SUBMODULES[@]}"; do
    current_branch="${SUBMODULES[$submodule]}"
    
    log "  Processing: $submodule (currently on $current_branch)"
    
    cd "$WATERFALL_ROOT/$submodule"
    
    # Fetch latest
    git fetch origin
    
    # Créer staging depuis la branche actuelle
    if git show-ref --verify --quiet refs/heads/staging; then
        warn "    Branch staging already exists, skipping creation"
    else
        log "    Creating staging from $current_branch"
        git checkout "$current_branch"
        git pull origin "$current_branch" || warn "    Could not pull $current_branch"
        git checkout -b staging
        git push origin staging
        log "    ✓ staging created and pushed"
    fi
    
    # Créer develop depuis la branche actuelle
    if git show-ref --verify --quiet refs/heads/develop; then
        warn "    Branch develop already exists, skipping creation"
    else
        log "    Creating develop from $current_branch"
        git checkout "$current_branch"
        git checkout -b develop
        git push origin develop
        log "    ✓ develop created and pushed"
    fi
    
    cd "$WATERFALL_ROOT"
done

log "✓ Étape 1 terminée"
echo ""

# Étape 2: Merger les branches de travail dans main
log "📋 Étape 2/4: Merge des branches de travail vers main"

for submodule in "${!SUBMODULES[@]}"; do
    current_branch="${SUBMODULES[$submodule]}"
    
    log "  Merging: $submodule ($current_branch → main)"
    
    cd "$WATERFALL_ROOT/$submodule"
    
    # Checkout main et pull
    git checkout main
    git pull origin main
    
    # Merger la branche de travail
    if [ "$current_branch" != "main" ]; then
        log "    Merging $current_branch into main..."
        if git merge "$current_branch" --no-edit; then
            log "    ✓ Merge successful"
            git push origin main
            log "    ✓ Pushed to origin/main"
        else
            error "    ✗ Merge conflict detected!"
            error "    Please resolve manually in: $WATERFALL_ROOT/$submodule"
            error "    Then run: git merge --continue && git push origin main"
            exit 1
        fi
    else
        log "    Already on main, skipping merge"
    fi
    
    cd "$WATERFALL_ROOT"
done

log "✓ Étape 2 terminée"
echo ""

# Étape 3: Mettre à jour staging et develop avec main
log "📋 Étape 3/4: Synchronisation staging et develop avec main"

for submodule in "${!SUBMODULES[@]}"; do
    log "  Updating: $submodule"
    
    cd "$WATERFALL_ROOT/$submodule"
    
    # Mettre à jour staging
    git checkout staging
    git merge main --no-edit
    git push origin staging
    log "    ✓ staging updated"
    
    # Mettre à jour develop
    git checkout develop
    git merge main --no-edit
    git push origin develop
    log "    ✓ develop updated"
    
    # Retour sur main
    git checkout main
    
    cd "$WATERFALL_ROOT"
done

log "✓ Étape 3 terminée"
echo ""

# Étape 4: Traiter le repo principal waterfall-development
log "📋 Étape 4/4: Migration du repo principal waterfall-development"

cd "$WATERFALL_ROOT"

# Créer staging et develop pour le repo principal
if ! git show-ref --verify --quiet refs/heads/staging; then
    log "  Creating staging for waterfall repo"
    git checkout main
    git pull origin main
    git checkout -b staging
    git push origin staging
    log "  ✓ staging created"
fi

if ! git show-ref --verify --quiet refs/heads/develop; then
    log "  Creating develop for waterfall repo"
    git checkout main
    git checkout -b develop
    git push origin develop
    log "  ✓ develop created"
fi

# Mettre à jour les références des sous-modules
log "  Updating submodule references to main branch"
git submodule foreach 'git checkout main && git pull origin main'
git add .gitmodules services/ web/ tests/
if git diff --staged --quiet; then
    log "  No submodule reference changes to commit"
else
    git commit -m "chore: update all submodules to main branch after migration"
    git push origin main
    log "  ✓ Submodule references updated"
fi

git checkout main

log "✓ Étape 4 terminée"
echo ""

# Résumé final
log "🎉 Migration terminée avec succès!"
echo ""
log "📊 État final:"
log "  ✓ Toutes les branches staging et develop créées"
log "  ✓ Toutes les branches de travail mergées dans main"
log "  ✓ staging et develop synchronisées avec main"
log "  ✓ Repo principal mis à jour"
echo ""
log "📝 Prochaines étapes recommandées:"
log "  1. Vérifier que tout est OK sur GitHub/GitLab"
log "  2. Configurer les branch protection rules:"
log "     - main: require PR + approvals"
log "     - staging: require PR"
log "  3. Supprimer les anciennes branches de travail (optionnel):"
log "     - fix_issues, fix/issues, web_staging, feature/integration-tests"
echo ""
log "📖 Voir le fichier migration.log pour les détails complets"
