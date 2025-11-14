#!/bin/bash
# Script de migration vers le workflow unifié avec création de PRs
# Pour les repos avec branch protection sur main

set -e

WATERFALL_ROOT="/home/benjamin/projects/waterfall"
LOG_FILE="$WATERFALL_ROOT/migration-prs.log"
PR_LIST="$WATERFALL_ROOT/prs-to-create.md"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

# Initialiser les fichiers
echo "=== Migration started at $(date) ===" > "$LOG_FILE"
cat > "$PR_LIST" << 'EOF'
# Pull Requests à créer pour la migration

## Instructions

Pour chaque repo ci-dessous, créez une PR pour merger la branche de travail vers `main`.

### Avec GitHub CLI (gh)
```bash
# Installer gh si nécessaire : https://cli.github.com/
gh auth login

# Pour chaque PR listée ci-dessous :
cd <chemin-du-repo>
gh pr create --base main --head <branche> --title "<titre>" --body "Migration vers le workflow unifié. Merge de la branche de travail dans main."
```

### Manuellement via l'interface GitHub
Cliquez sur les URLs ci-dessous pour créer les PRs :

---

EOF

log "🚀 Début de la migration avec création de PRs"

# Liste des sous-modules avec leurs branches actuelles
declare -A SUBMODULES=(
    ["services/auth_service"]="fix_issues:bengeek06/auth-api-waterfall"
    ["services/identity_service"]="fix_issues:bengeek06/identity-api-waterfall"
    ["services/guardian_service"]="fix_issues:bengeek06/guardian-api-waterfall"
    ["services/storage_service"]="fix_issues:bengeek06/storage-api-waterfall"
    ["services/basic_io_service"]="fix/issues:bengeek06/basic-io-api-waterfall"
    ["services/project_service"]="feature/integration-tests:bengeek06/project_api_waterfall"
    ["web"]="web_staging:bengeek06/web-waterfall"
    ["tests"]="web_staging:bengeek06/e2e-waterfall"
)

# Étape 1: Créer staging et develop, pousser les branches
log "📋 Étape 1/3: Création et push des branches staging et develop"

for submodule in "${!SUBMODULES[@]}"; do
    IFS=':' read -r current_branch repo_name <<< "${SUBMODULES[$submodule]}"
    
    log "  Processing: $submodule (branch: $current_branch)"
    
    cd "$WATERFALL_ROOT/$submodule"
    
    # Fetch latest
    git fetch origin
    
    # S'assurer d'être sur la bonne branche et à jour
    git checkout "$current_branch"
    git pull origin "$current_branch" || warn "    Could not pull $current_branch"
    
    # Créer et pousser staging
    if git ls-remote --heads origin staging | grep -q staging; then
        warn "    Remote branch staging already exists"
        git checkout staging 2>/dev/null || git checkout -b staging
        git pull origin staging
    else
        git checkout -b staging 2>/dev/null || git checkout staging
        git push origin staging
        log "    ✓ staging created and pushed"
    fi
    
    # Créer et pousser develop
    git checkout "$current_branch"
    if git ls-remote --heads origin develop | grep -q develop; then
        warn "    Remote branch develop already exists"
        git checkout develop 2>/dev/null || git checkout -b develop
        git pull origin develop
    else
        git checkout -b develop 2>/dev/null || git checkout develop
        git push origin develop
        log "    ✓ develop created and pushed"
    fi
    
    # Retour sur la branche de travail
    git checkout "$current_branch"
    
    cd "$WATERFALL_ROOT"
done

log "✓ Étape 1 terminée"
echo ""

# Étape 2: Générer la liste des PRs à créer
log "📋 Étape 2/3: Génération de la liste des PRs"

for submodule in "${!SUBMODULES[@]}"; do
    IFS=':' read -r current_branch repo_name <<< "${SUBMODULES[$submodule]}"
    
    if [ "$current_branch" == "main" ]; then
        continue
    fi
    
    # Encoder le nom de branche pour l'URL
    encoded_branch=$(echo "$current_branch" | sed 's/\//%2F/g')
    
    # Titre de la PR
    pr_title="chore: merge $current_branch into main (migration)"
    
    # URL GitHub pour créer la PR
    pr_url="https://github.com/$repo_name/compare/main...$encoded_branch?expand=1&title=${pr_title// /%20}"
    
    # Ajouter au fichier
    cat >> "$PR_LIST" << EOF
## $submodule

**Repo**: \`$repo_name\`  
**Branch**: \`$current_branch\` → \`main\`

### Option 1: GitHub CLI
\`\`\`bash
cd $WATERFALL_ROOT/$submodule
gh pr create --base main --head $current_branch \\
  --title "$pr_title" \\
  --body "Migration automatique vers le workflow unifié (main/staging/develop).

Cette PR merge les changements de \\\`$current_branch\\\` dans \\\`main\\\`.

Changements inclus:
- Documentation CONTRIBUTING.md
- Améliorations et corrections diverses

Fait partie de la migration globale du projet vers un workflow Git standardisé."
\`\`\`

### Option 2: Interface web
[🔗 Créer la PR sur GitHub]($pr_url)

---

EOF

    info "  PR prepared for: $submodule ($current_branch → main)"
done

log "✓ Étape 2 terminée"
echo ""

# Étape 3: Instructions pour après les merges
log "📋 Étape 3/3: Préparation des instructions post-merge"

cat >> "$PR_LIST" << 'EOF'

## Après avoir mergé toutes les PRs

### 1. Mettre à jour staging et develop avec main

Pour chaque repo, une fois la PR mergée :

```bash
cd <chemin-du-repo>

# Mettre à jour staging
git checkout staging
git pull origin staging
git merge origin/main --no-edit
git push origin staging

# Mettre à jour develop
git checkout develop
git pull origin develop
git merge origin/main --no-edit
git push origin develop

# Retour sur main
git checkout main
git pull origin main
```

### 2. Mettre à jour le repo principal waterfall

```bash
cd /home/benjamin/projects/waterfall

# Créer staging et develop pour waterfall si nécessaire
git checkout main
git pull origin main

if ! git ls-remote --heads origin staging | grep -q staging; then
  git checkout -b staging
  git push origin staging
fi

if ! git ls-remote --heads origin develop | grep -q develop; then
  git checkout main
  git checkout -b develop
  git push origin develop
fi

# Mettre à jour les références des sous-modules
git checkout main
git submodule update --remote --merge
git add services/ web/ tests/
git commit -m "chore: update all submodules to main after migration"
git push origin main

# Synchroniser staging et develop
git checkout staging
git merge main --no-edit
git push origin staging

git checkout develop
git merge main --no-edit
git push origin develop

git checkout main
```

### 3. Configurer les branch protections (recommandé)

Pour chaque repo sur GitHub :

1. Settings → Branches → Add branch protection rule
2. Branch name pattern: `main`
   - ✅ Require a pull request before merging
   - ✅ Require approvals (1 minimum recommandé)
   - ✅ Dismiss stale pull request approvals when new commits are pushed
3. Branch name pattern: `staging`
   - ✅ Require a pull request before merging (optionnel)

### 4. Nettoyer les anciennes branches (optionnel)

Une fois que tout est mergé et vérifié :

```bash
# Supprimer localement et sur remote (pour chaque repo)
git branch -d fix_issues
git push origin --delete fix_issues

# Répéter pour : fix/issues, web_staging, feature/integration-tests
```

---

## ✅ Checklist finale

- [ ] Toutes les PRs créées
- [ ] Toutes les PRs mergées
- [ ] staging et develop synchronisés partout
- [ ] Repo principal waterfall mis à jour
- [ ] Branch protections configurées
- [ ] Anciennes branches nettoyées (optionnel)

EOF

log "✓ Étape 3 terminée"
echo ""

# Résumé final
log "🎉 Préparation terminée!"
echo ""
log "📋 Prochaines étapes:"
log "  1. Consulter le fichier: $PR_LIST"
log "  2. Créer toutes les PRs listées (via gh CLI ou interface web)"
log "  3. Faire reviewer et merger les PRs"
log "  4. Suivre les instructions post-merge dans le fichier"
echo ""
info "💡 Astuce: Si vous avez GitHub CLI installé, vous pouvez automatiser avec:"
info "   cd /path/to/repo && gh pr create ..."
echo ""
log "📖 Log complet disponible dans: $LOG_FILE"
log "📝 Instructions détaillées dans: $PR_LIST"
