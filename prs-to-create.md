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

## services/auth_service

**Repo**: `bengeek06/auth-api-waterfall`  
**Branch**: `fix_issues` → `main`

### Option 1: GitHub CLI
```bash
cd /home/benjamin/projects/waterfall/services/auth_service
gh pr create --base main --head fix_issues \
  --title "chore: merge fix_issues into main (migration)" \
  --body "Migration automatique vers le workflow unifié (main/staging/develop).

Cette PR merge les changements de \`fix_issues\` dans \`main\`.

Changements inclus:
- Documentation CONTRIBUTING.md
- Améliorations et corrections diverses

Fait partie de la migration globale du projet vers un workflow Git standardisé."
```

### Option 2: Interface web
[🔗 Créer la PR sur GitHub](https://github.com/bengeek06/auth-api-waterfall/compare/main...fix_issues?expand=1&title=chore:%20merge%20fix_issues%20into%20main%20(migration))

---

## services/identity_service

**Repo**: `bengeek06/identity-api-waterfall`  
**Branch**: `fix_issues` → `main`

### Option 1: GitHub CLI
```bash
cd /home/benjamin/projects/waterfall/services/identity_service
gh pr create --base main --head fix_issues \
  --title "chore: merge fix_issues into main (migration)" \
  --body "Migration automatique vers le workflow unifié (main/staging/develop).

Cette PR merge les changements de \`fix_issues\` dans \`main\`.

Changements inclus:
- Documentation CONTRIBUTING.md
- Améliorations et corrections diverses

Fait partie de la migration globale du projet vers un workflow Git standardisé."
```

### Option 2: Interface web
[🔗 Créer la PR sur GitHub](https://github.com/bengeek06/identity-api-waterfall/compare/main...fix_issues?expand=1&title=chore:%20merge%20fix_issues%20into%20main%20(migration))

---

## web

**Repo**: `bengeek06/web-waterfall`  
**Branch**: `web_staging` → `main`

### Option 1: GitHub CLI
```bash
cd /home/benjamin/projects/waterfall/web
gh pr create --base main --head web_staging \
  --title "chore: merge web_staging into main (migration)" \
  --body "Migration automatique vers le workflow unifié (main/staging/develop).

Cette PR merge les changements de \`web_staging\` dans \`main\`.

Changements inclus:
- Documentation CONTRIBUTING.md
- Améliorations et corrections diverses

Fait partie de la migration globale du projet vers un workflow Git standardisé."
```

### Option 2: Interface web
[🔗 Créer la PR sur GitHub](https://github.com/bengeek06/web-waterfall/compare/main...web_staging?expand=1&title=chore:%20merge%20web_staging%20into%20main%20(migration))

---

## services/project_service

**Repo**: `bengeek06/project_api_waterfall`  
**Branch**: `feature/integration-tests` → `main`

### Option 1: GitHub CLI
```bash
cd /home/benjamin/projects/waterfall/services/project_service
gh pr create --base main --head feature/integration-tests \
  --title "chore: merge feature/integration-tests into main (migration)" \
  --body "Migration automatique vers le workflow unifié (main/staging/develop).

Cette PR merge les changements de \`feature/integration-tests\` dans \`main\`.

Changements inclus:
- Documentation CONTRIBUTING.md
- Améliorations et corrections diverses

Fait partie de la migration globale du projet vers un workflow Git standardisé."
```

### Option 2: Interface web
[🔗 Créer la PR sur GitHub](https://github.com/bengeek06/project_api_waterfall/compare/main...feature%2Fintegration-tests?expand=1&title=chore:%20merge%20feature/integration-tests%20into%20main%20(migration))

---

## services/storage_service

**Repo**: `bengeek06/storage-api-waterfall`  
**Branch**: `fix_issues` → `main`

### Option 1: GitHub CLI
```bash
cd /home/benjamin/projects/waterfall/services/storage_service
gh pr create --base main --head fix_issues \
  --title "chore: merge fix_issues into main (migration)" \
  --body "Migration automatique vers le workflow unifié (main/staging/develop).

Cette PR merge les changements de \`fix_issues\` dans \`main\`.

Changements inclus:
- Documentation CONTRIBUTING.md
- Améliorations et corrections diverses

Fait partie de la migration globale du projet vers un workflow Git standardisé."
```

### Option 2: Interface web
[🔗 Créer la PR sur GitHub](https://github.com/bengeek06/storage-api-waterfall/compare/main...fix_issues?expand=1&title=chore:%20merge%20fix_issues%20into%20main%20(migration))

---

## services/guardian_service

**Repo**: `bengeek06/guardian-api-waterfall`  
**Branch**: `fix_issues` → `main`

### Option 1: GitHub CLI
```bash
cd /home/benjamin/projects/waterfall/services/guardian_service
gh pr create --base main --head fix_issues \
  --title "chore: merge fix_issues into main (migration)" \
  --body "Migration automatique vers le workflow unifié (main/staging/develop).

Cette PR merge les changements de \`fix_issues\` dans \`main\`.

Changements inclus:
- Documentation CONTRIBUTING.md
- Améliorations et corrections diverses

Fait partie de la migration globale du projet vers un workflow Git standardisé."
```

### Option 2: Interface web
[🔗 Créer la PR sur GitHub](https://github.com/bengeek06/guardian-api-waterfall/compare/main...fix_issues?expand=1&title=chore:%20merge%20fix_issues%20into%20main%20(migration))

---

## services/basic_io_service

**Repo**: `bengeek06/basic-io-api-waterfall`  
**Branch**: `fix/issues` → `main`

### Option 1: GitHub CLI
```bash
cd /home/benjamin/projects/waterfall/services/basic_io_service
gh pr create --base main --head fix/issues \
  --title "chore: merge fix/issues into main (migration)" \
  --body "Migration automatique vers le workflow unifié (main/staging/develop).

Cette PR merge les changements de \`fix/issues\` dans \`main\`.

Changements inclus:
- Documentation CONTRIBUTING.md
- Améliorations et corrections diverses

Fait partie de la migration globale du projet vers un workflow Git standardisé."
```

### Option 2: Interface web
[🔗 Créer la PR sur GitHub](https://github.com/bengeek06/basic-io-api-waterfall/compare/main...fix%2Fissues?expand=1&title=chore:%20merge%20fix/issues%20into%20main%20(migration))

---

## tests

**Repo**: `bengeek06/e2e-waterfall`  
**Branch**: `web_staging` → `main`

### Option 1: GitHub CLI
```bash
cd /home/benjamin/projects/waterfall/tests
gh pr create --base main --head web_staging \
  --title "chore: merge web_staging into main (migration)" \
  --body "Migration automatique vers le workflow unifié (main/staging/develop).

Cette PR merge les changements de \`web_staging\` dans \`main\`.

Changements inclus:
- Documentation CONTRIBUTING.md
- Améliorations et corrections diverses

Fait partie de la migration globale du projet vers un workflow Git standardisé."
```

### Option 2: Interface web
[🔗 Créer la PR sur GitHub](https://github.com/bengeek06/e2e-waterfall/compare/main...web_staging?expand=1&title=chore:%20merge%20web_staging%20into%20main%20(migration))

---


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

