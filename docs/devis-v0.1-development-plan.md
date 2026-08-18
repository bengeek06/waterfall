# Plan de développement Devis v0.1

## Objectif

Livrer un flux complet : projet -> planning importé -> chiffrage des tâches et coûts globaux -> devis versionné -> analyse -> export Excel et visualisation enrichie dans MS Project.

## Principes d'exécution

- Un commit par capacité métier testable.
- Les modèles, règles de calcul et contrat OpenAPI précèdent chaque écran majeur.
- Les devis validés sont immuables et conservent leurs snapshots financiers.
- L'infrastructure supplémentaire n'est introduite qu'après un flux validé.

## Jalons

### 1. Référentiel financier

Ajouter les types de coût extensibles, les catégories de coût enrichies et les codes comptables ERP.

Livrables : migration, modèles, schémas, API admin, tests et OpenAPI.

Commit cible : `feat(costs): add configurable cost catalog`

### 2. Affectations de main-d'œuvre

Associer plusieurs rôles à une tâche avec quantité, heures et catégorie MO issue du rôle. Exposer le filtre organisationnel par nœud et descendants.

Livrables : modèles, calcul MO de base, API et tests.

Commit cible : `feat(estimate): assign roles to planning tasks`

### 3. Structure de devis versionné

Introduire les devis, statuts, versions et lignes de tâche. Préparer les snapshots de calculs et la référence au budget d'origine.

Livrables : migration, modèles, schémas, API brouillon/version et tests.

Commit cible : `feat(estimate): add versioned estimate structure`

### 4. Coûts hors main-d'œuvre

Ajouter les lignes Fourniture, Frais et Unité d'œuvre, rattachées facultativement à une tâche. Gérer le statut minimal des fournitures.

Livrables : modèles, règles de validation, API et tests.

Commit cible : `feat(estimate): support purchase overhead and work-unit costs`

### 5. Moteur de calcul

Calculer MO, Achat et PRU non chargé. Répartir la MO multiannuelle selon les dates de tâches, taux annuels et inflation. Figer les snapshots à la validation.

Livrables : service de calcul déterministe, tests de référence et agrégats.

Commit cible : `feat(estimate): calculate versioned cost snapshots`

### 6. Contrat et analyses API

Exposer les opérations de devis, validation, duplication et agrégats par tâche, rôle, nœud, type, catégorie et compte comptable.

Livrables : OpenAPI, client TypeScript régénéré, tests d'autorisation et de calcul.

Commit cible : `feat(estimate): expose estimate workflow and analysis API`

### 7. Grille de devis frontend

Créer la grille hiérarchique de tâches et lignes de coût, avec affectations MO multiples, coûts globaux et édition contrôlée des colonnes autorisées.

Commit cible : `feat(frontend): add editable estimate grid`

### 8. Analyse et exports

Ajouter les tableaux d'analyse, graphiques initiaux, export Excel et enrichissement MS Project de visualisation.

Commits cibles :

- `feat(frontend): add estimate cost analysis`
- `feat(export): add estimate Excel and planning enrichment`

### 9. Prévision du reste à faire

Réutiliser la structure de devis pour les versions `forecast_remaining`, avec références aux lignes budget, reste de charge et état des fournitures.

Commit cible : `feat(forecast): add remaining-work estimate workflow`

## Hors périmètre v0.1

- Gantt Waterfall complet.
- Calendriers détaillés et nivellement automatique des capacités.
- Synchronisation bidirectionnelle exhaustive avec MS Project.
- Redis, object storage distribué, workers asynchrones et microservices.
