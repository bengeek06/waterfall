# TODO - Waterfall Project

**Date de création**: 15 novembre 2025  
**Total issues**: 79 (59 ouvertes, 20 fermées)  
**Durée estimée totale**: 9 semaines

---

## 🔴 PHASE 1 : SÉCURITÉ CRITIQUE (Semaine 1)

**Objectif**: Corriger les vulnérabilités de sécurité avant tout autre développement  
**Durée**: 5-7 jours  
**Priorité**: 🔴🔴🔴 BLOQUANT

### Guardian Service
- [ ] **#5** - CRITICAL SECURITY REPORT - MULTI-TENANT ISOLATION
  - Auditer tous les endpoints pour vérification `company_id`
  - Ajouter filtres systématiques sur `company_id` dans toutes les requêtes
  - Créer tests d'isolation entre tenants
  - **Durée**: 2-3 jours
  - **Risque**: Fuite de données entre companies

### Identity Service
- [ ] **#17** - Fix company_id Architecture in Identity Service
  - Réviser l'architecture de gestion `company_id`
  - Documenter les règles d'injection/validation
  - Aligner avec les corrections de Guardian #5
  - **Durée**: 1-2 jours
  - **Dépendance**: Lié à Guardian #5

### Tests
- [ ] **#6** - Security Test Suite
  - Tests d'isolation multi-tenant (CRITICAL)
  - Tests de permissions RBAC
  - Tests d'injection SQL/XSS
  - Tests d'authentification/autorisation
  - **Durée**: 2 jours
  - **Note**: À faire en parallèle de Guardian #5

---

## 🟠 PHASE 2 : STABILITÉ CONFIGURATION (Semaine 2)

**Objectif**: Fail-fast sur mauvaise configuration  
**Durée**: 2-3 jours  
**Priorité**: 🟠🟠 IMPORTANT  
**Note**: Les 12 tickets peuvent être parallélisés par service

### 2.1 Validation Variables d'Environnement (6 services)

**Durée estimée**: 4-6 heures (parallélisable)

- [ ] **auth_service #5** - Add Missing Environment Variable Validation in Config
  - Valider: `JWT_SECRET`, `INTERNAL_AUTH_TOKEN`, `USER_SERVICE_URL`
  - Créer helper `require_env_var()`

- [ ] **identity_service #19** - Add Missing Environment Variable Validation in Config
  - Valider: `JWT_SECRET`, `INTERNAL_AUTH_TOKEN`, `GUARDIAN_SERVICE_URL`, `STORAGE_SERVICE_URL`

- [ ] **guardian_service #13** - Add Missing Environment Variable Validation in Config
  - Valider: `JWT_SECRET`
  - Remplacer `SECRET_KEY` avec default par `JWT_SECRET` requis

- [ ] **basic_io_service #12** - Add Missing Environment Variable Validation in Config
  - Valider: `JWT_SECRET`, `IDENTITY_SERVICE_URL`, `GUARDIAN_SERVICE_URL`

- [ ] **storage_service #5** - Add Missing Environment Variable Validation in Config
  - Valider: `JWT_SECRET`, `IDENTITY_SERVICE_URL`, `GUARDIAN_SERVICE_URL`
  - Valider MinIO: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET_NAME`

- [ ] **project_service #6** - Add Missing Environment Variable Validation in Config
  - Valider: `JWT_SECRET`, `IDENTITY_SERVICE_URL`, `GUARDIAN_SERVICE_URL`

### 2.2 Correction Endpoints /config (6 services)

**Durée estimée**: 3-4 heures (parallélisable)

- [ ] **auth_service #4** - Fix Config Endpoint Environment Variables Mismatch
  - Ajouter indicateurs `JWT_SECRET_SET`, `INTERNAL_AUTH_TOKEN_SET`

- [ ] **identity_service #18** - Fix Config Endpoint Environment Variables Mismatch
  - `DATABASE_URI` → `DATABASE_URL`
  - `JWT_SECRET_KEY` → `JWT_SECRET`
  - `INTERNAL_SECRET_KEY` → `INTERNAL_AUTH_TOKEN`
  - Ajouter `STORAGE_SERVICE_URL`

- [ ] **guardian_service #12** - Fix Config Endpoint Environment Variables Mismatch
  - `DATABASE_URI` → `DATABASE_URL`
  - `SECRET_KEY` → `JWT_SECRET`
  - Supprimer `IDENTITY_SERVICE_URL` (non utilisé)

- [ ] **basic_io_service #11** - Fix Config Endpoint Environment Variables Mismatch
  - `DATABASE_URI` → `DATABASE_URL`
  - `JWT_SECRET_KEY` → `JWT_SECRET`
  - Ajouter `IDENTITY_SERVICE_URL`

- [ ] **storage_service #4** - Fix Config Endpoint Environment Variables Mismatch
  - `DATABASE_URI` → `DATABASE_URL`
  - `JWT_SECRET_KEY` → `JWT_SECRET`
  - Ajouter `IDENTITY_SERVICE_URL` et config MinIO complète

- [ ] **project_service #5** - Fix Config Endpoint Environment Variables Mismatch
  - `DATABASE_URI` → `DATABASE_URL`
  - `JWT_SECRET_KEY` → `JWT_SECRET`
  - Ajouter `IDENTITY_SERVICE_URL`

---

## 🟡 PHASE 3 : BUGS CRITIQUES (Semaine 3)

**Objectif**: Résoudre les bugs bloquants et améliorations rapides  
**Durée**: 4-5 jours  
**Priorité**: 🟡🟡 IMPORTANT

### 3.1 Bugs Frontend (Web)

- [ ] **#30** - ProfileModal Does Not Refresh Dictionary After Language Change
  - Forcer refresh du dictionnaire au changement de langue
  - **Durée**: 2h

- [ ] **#29** - Remove Unused Profile Page and Components
  - Supprimer `/home/profile/page.tsx`
  - Supprimer `components/profile.tsx` si non utilisé ailleurs
  - Supprimer `components/LanguageSwitcher.tsx`
  - **Durée**: 1h

- [ ] **#28** - Remove OperationEnum Prefix Stripping Workarounds
  - Supprimer workarounds une fois Guardian #11 résolu
  - **Durée**: 2h
  - **Dépendance**: Guardian #11

- [ ] **#22** - Login: Error message not displayed on failed authentication
  - Afficher message d'erreur sur échec login
  - **Durée**: 1h
  - **Type**: bug

- [ ] **#17** - Message when delete a position
  - Ajouter message de confirmation
  - **Durée**: 1h

### 3.2 Bugs Backend

- [ ] **guardian_service #15** - Review company_id Auto-Injection Consistency
  - Corriger utilisation inconsistante de `extract_company_id`
  - RoleListResource.get() utilise `extract_company_id=True` inutilement
  - PATCH endpoints utilisent `request.json` au lieu de `g.json_data`
  - **Durée**: 2-3h
  - **Priorité**: BASSE (qualité code)

- [ ] **guardian_service #11** - Fix OperationEnum Standards and Serialization
  - Corriger standards OperationEnum
  - **Durée**: 2h

- [ ] **guardian_service #3** - Return 404 when access_granted=false
  - Retourner 404 au lieu de 200 avec access_granted=false
  - **Durée**: 1h

- [ ] **identity_service #16** - Phone number validation too restrictive (digits only)
  - Accepter format international (+33, espaces, tirets)
  - **Durée**: 1h
  - **Type**: bug

- [ ] **identity_service #3** - Validation error
  - À investiguer et corriger
  - **Durée**: À déterminer

- [ ] **storage_service #2** - Archived File Status Not Updated on New Version Upload
  - Marquer ancienne version comme archivée lors d'upload nouvelle version
  - **Durée**: 2h

- [ ] **project_service #3** - Invalid RBAC Operations
  - Corriger opérations RBAC invalides
  - **Durée**: 2h

- [ ] **basic_io_service #9** - Remove Mermaid import/export from basic-io
  - Supprimer fonctionnalité Mermaid
  - **Durée**: 3h

### 3.3 Auto-injection company_id

- [ ] **identity_service #10** - Auto-inject company_id from JWT Token in Organization Unit Creation
  - Injecter automatiquement company_id depuis JWT
  - **Durée**: 2h

- [ ] **guardian_service #10** - Review company_id Auto-Injection Pattern in Guardian Service
  - Réviser pattern d'auto-injection
  - Documenter les bonnes pratiques
  - **Durée**: 4h
  - **Note**: Guardian #15 est lié mais moins prioritaire (cohérence vs architecture)

### 3.4 Tests

- [ ] **tests #9** - Fix xfail Tests - Basic-IO API Migration
  - Corriger tests marqués xfail
  - **Durée**: 1 jour

---

## 🟢 PHASE 4 : FEATURES UX IMPORTANTES (Semaines 4-5)

**Objectif**: Améliorer l'expérience utilisateur  
**Durée**: 2 semaines  
**Priorité**: 🟢🟢 MOYENNE-HAUTE

### 4.1 Logos & Avatars

**⚠️ ATTENTION**: Respecter l'ordre des dépendances

- [ ] **identity_service #15** - Add has_avatar field to User model
  - Ajouter champ `has_avatar` booléen
  - **Durée**: 2h
  - **BLOQUANT POUR**: Web #25

- [ ] **identity_service #14** - Add Logo Support for Companies
  - Ajouter `logo_url` à Company
  - Intégration avec storage_service
  - **Durée**: 4h

- [ ] **identity_service #13** - Add Logo Support for Customers and Subcontractors
  - Ajouter `logo_url` à Customer et Subcontractor
  - **Durée**: 3h

- [ ] **web #13** - Company edit/create: add company logo
  - UI upload logo company
  - **Durée**: 3h
  - **Dépendance**: Identity #14

- [ ] **web #15** - customer/subcontractor: add logo
  - UI upload logo customer/subcontractor
  - **Durée**: 3h
  - **Dépendance**: Identity #13

- [ ] **web #25** - Use has_avatar field to prevent unnecessary requests
  - Optimiser requêtes avatar avec champ `has_avatar`
  - **Durée**: 2h
  - **DÉPENDANCE**: Identity #15 ⚠️

### 4.2 Authentication & UX

- [ ] **web #24** - Authentication: Improve session management and token refresh strategy
  - Améliorer gestion session
  - Stratégie refresh token
  - **Durée**: 1 jour

- [ ] **web #14** - company edit: add cancel button
  - Ajouter bouton annuler
  - **Durée**: 1h
  - **Quick Win** 🎯

- [ ] **web #12** - Add confirmation on User/Role/Policy delete
  - Dialogues de confirmation suppression
  - **Durée**: 4h

### 4.3 Query & Export

- [ ] **identity_service #9** - Missing Query Parameter Filtering
  - Ajouter filtres query parameters
  - **Durée**: 1 jour

- [ ] **basic_io_service #10** - Improve JSON/CSV export with M2M resolution
  - Résolution M2M dans exports
  - **Durée**: 1 jour
  - **BLOQUANT POUR**: Web #26

- [ ] **web #26** - Use basic-io M2M resolution for exports
  - Utiliser nouvelle API M2M
  - **Durée**: 4h
  - **DÉPENDANCE**: Basic-IO #10 ⚠️

---

## 🟢 PHASE 5 : REFACTORING & OPTIMISATION (Semaines 6-7)

**Objectif**: Améliorer la maintenabilité du code  
**Durée**: 2 semaines  
**Priorité**: 🟢 MOYENNE

### 5.1 Frontend Refactoring

- [ ] **web #21** - Refactor: Create Generic Table Components and Hooks
  - Composants génériques tableaux
  - Hooks réutilisables
  - **Durée**: 2 jours

- [ ] **web #20** - Refactor: Create Reusable TreeActions Component
  - Composant TreeActions réutilisable
  - **Durée**: 1 jour

- [ ] **web #27** - Add loading hooks for import/export in generic tables
  - Hooks loading pour import/export
  - **Durée**: 1 jour

### 5.2 Home & Workspace

- [ ] **web #23** - Home page: Workspace card ordering and color coding
  - Tri et code couleur cards workspace
  - **Durée**: 1 jour

### 5.3 Password Recovery

- [ ] **identity_service #12** - Password Recovery Strategy
  - Backend stratégie récupération mot de passe
  - Tokens temporaires, emails
  - **Durée**: 2-3 jours

- [ ] **web #10** - Add password lost strategy
  - UI récupération mot de passe
  - **Durée**: 1 jour
  - **Dépendance**: Identity #12

### 5.4 Misc

- [ ] **web #16** - Add VERSION file like other services
  - Créer fichier VERSION
  - **Durée**: 30min
  - **Quick Win** 🎯

---

## 🔵 PHASE 6 : TESTS COMPLETS (Semaine 8)

**Objectif**: Couverture de tests complète  
**Durée**: 2 semaines  
**Priorité**: 🔵 MOYENNE

### 6.1 API Tests

- [ ] **tests #12** - Project API Tests - Business Endpoints
  - Tests endpoints métier project_service
  - **Durée**: 2 jours

- [ ] **tests #11** - Basic-IO Service Tests - Missing Coverage
  - Compléter couverture basic_io_service
  - **Durée**: 2 jours

- [ ] **tests #10** - Storage Service Tests - Missing Coverage
  - Compléter couverture storage_service
  - **Durée**: 2 jours

### 6.2 UI Tests

- [ ] **tests #7** - UI Component Tests - Complete web component coverage
  - Tests composants React
  - **Durée**: 3 jours

### 6.3 Performance

- [ ] **tests #8** - Load Test Suite - Performance & Scalability
  - Tests de charge et scalabilité
  - **Durée**: 2-3 jours

---

## ⚪ PHASE 7 : FONCTIONNALITÉS AVANCÉES (Semaine 9+)

**Objectif**: Features commerciales et optimisations avancées  
**Durée**: 2+ semaines  
**Priorité**: ⚪ BASSE

### 7.1 Multi-Tenant Commercial

**⚠️ PRÉREQUIS**: Phase 1 (Sécurité) DOIT être terminée et validée

- [ ] **identity_service #20** - Add Multi-Tenant Hierarchy Support (Commercial License)
  - Ajouter `parent_id` et `is_group` à Company
  - Créer modèle `GroupPermission`
  - Endpoint `/companies/subsidiary` (commercial only)
  - Feature flag `IS_COMMERCIAL`
  - **Durée**: 6-8h

- [ ] **guardian_service #14** - Add Group Permission Support for Multi-Tenant Hierarchy
  - Helper `check_group_access()`
  - Étendre `/check-access` avec support GroupPermission
  - Gestion niveaux permission (read/write/admin)
  - **Durée**: 4-6h
  - **DÉPENDANCE**: Identity #20

### 7.2 Performance

- [ ] **guardian_service #9** - Implement Redis Cache for Authorization Endpoints
  - Cache Redis pour `/check-access`
  - Invalidation cache intelligente
  - **Durée**: 2 jours

### 7.3 RBAC Avancé

- [ ] **guardian_service #8** - Define and Create Realistic RBAC Roles and Policies
  - Définir rôles réalistes (Manager, Employee, Viewer, etc.)
  - Politiques granulaires
  - **Durée**: 2-3 jours

---

## 📊 STATISTIQUES GLOBALES

### Par Module

| Module           | Total | Ouvertes | Fermées | Critiques | Bugs | Enhancements |
|------------------|-------|----------|---------|-----------|------|--------------|
| **Web**          | 25    | 19       | 6       | 0         | 2    | 8            |
| **Tests**        | 9     | 7        | 2       | 1         | 0    | 0            |
| **Identity**     | 14    | 11       | 3       | 1         | 1    | 5            |
| **Guardian**     | 11    | 10       | 1       | 1         | 0    | 2            |
| **Basic-IO**     | 7     | 4        | 3       | 0         | 0    | 1            |
| **Storage**      | 3     | 3        | 0       | 0         | 0    | 0            |
| **Project**      | 3     | 3        | 0       | 0         | 0    | 0            |
| **Auth**         | 2     | 2        | 0       | 0         | 0    | 0            |
| **Waterfall**    | 5     | 0        | 5       | 0         | 0    | 0            |
| **TOTAL**        | **79**| **59**   | **20**  | **3**     | **3**| **16**       |

### Par Phase

| Phase | Nombre d'issues | Durée estimée | Priorité |
|-------|----------------|---------------|----------|
| 1     | 3              | 1 semaine     | 🔴🔴🔴    |
| 2     | 12             | 2-3 jours     | 🟠🟠      |
| 3     | 16             | 4-5 jours     | 🟡🟡      |
| 4     | 11             | 2 semaines    | 🟢🟢      |
| 5     | 6              | 2 semaines    | 🟢       |
| 6     | 5              | 2 semaines    | 🔵       |
| 7     | 6              | 2+ semaines   | ⚪       |

---

## ⚠️ DÉPENDANCES CRITIQUES

```
Identity #15 (has_avatar)
    ↓
Web #25 (use has_avatar)

Basic-IO #10 (M2M exports)
    ↓
Web #26 (use M2M in UI)

Guardian #11 (OperationEnum)
    ↓
Web #28 (remove workarounds)

Identity #12 (password recovery backend)
    ↓
Web #10 (password recovery UI)

Identity #14 (company logo backend)
    ↓
Web #13 (company logo UI)

Identity #13 (customer/subcontractor logo backend)
    ↓
Web #15 (customer/subcontractor logo UI)

Identity #20 (multi-tenant hierarchy)
    ↓
Guardian #14 (group permissions)

Phase 1 (Sécurité) COMPLÈTE
    ↓
Phase 7 (Multi-tenant commercial)
```

---

## 🎯 QUICK WINS (< 2h)

Ces tickets peuvent être faits rapidement pour des résultats visibles :

- [ ] **web #14** - Cancel button (1h)
- [ ] **web #16** - VERSION file (30min)
- [ ] **web #17** - Delete position message (1h)
- [ ] **guardian #3** - Return 404 (1h)
- [ ] **identity #16** - Phone validation (1h)
- [ ] **web #22** - Login error message (1h)

**Total Quick Wins** : ~6h pour 6 améliorations visibles

---

## 🚨 RÈGLES D'OR

1. **NE JAMAIS commencer Phase 7 avant validation complète Phase 1**
   - Multi-tenant nécessite sécurité irréprochable

2. **Respecter les dépendances**
   - Voir section "Dépendances Critiques"

3. **Tester au fur et à mesure**
   - Ne pas attendre Phase 6 pour créer des tests

4. **Phase 2 = Parallélisable**
   - Les 12 tickets config sont indépendants

5. **Guardian #5 = BLOQUANT pour tout le reste**
   - C'est THE priorité absolue

---

## 📅 JALONS CLÉS

- **Fin Semaine 1** : Sécurité validée ✅
- **Fin Semaine 2** : Configuration stable ✅
- **Fin Semaine 3** : Bugs critiques résolus ✅
- **Fin Semaine 5** : UX améliorée ✅
- **Fin Semaine 7** : Code refactoré ✅
- **Fin Semaine 8** : Tests complets ✅
- **Semaine 9+** : Features avancées 🚀

---

**Dernière mise à jour** : 15 novembre 2025  
**Prochaine révision** : Fin de chaque phase
