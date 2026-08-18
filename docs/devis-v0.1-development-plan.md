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

### 6A. Fondations frontend

Mettre en place le socle visuel et technique de l'application avant l'intégration des fonctionnalités métier. Cette étape doit rendre l'application navigable, cohérente et responsive, sans encore implémenter les grilles de planning ou de devis.

Livrables :
- mise à jour du `package.json` et installation des primitives UI retenues ;
- validation des styles globaux, tokens de couleur, typographie, espacements et états de focus ;
- layout applicatif responsive avec sidebar, zone de contenu et en-tête utilisateur ;
- navigation de base vers Projets, Ressources et Utilisateurs ;
- page de connexion sobre, états de chargement et d'erreur ;
- restauration de session, redirection des routes protégées et déconnexion ;
- composants partagés pour boutons, champs, panneaux, badges et états vides ;
- validation lint, typecheck et build du frontend.

Choix techniques :
- Radix UI + shadcn/ui pour les primitives accessibles ;
- Tailwind CSS ou styles CSS locaux selon la compatibilité avec le socle Next.js existant ;
- Lucide pour les icônes d'interface ;
- polices et palette conservant une direction sobre, neutre et entreprise.

Commit cible : `feat(frontend): establish application shell`

### 6B. Contrat et analyses API

Exposer les opérations de devis, validation, duplication et agrégats par tâche, rôle, nœud, type, catégorie et compte comptable. Préparer la base de données métier et les schémas réponse nécessaires au front pour les écrans de projets, de planification et de devis.

Livrables :
- endpoints API de création / lecture / validation / duplication de devis ;
- endpoints de lecture des lignes de coût et des tâches associées ;
- agrégats financiers par catégorie, type, rôle, année et nœud ;
- schémas de réponse stricts et cohérents avec les écrans de gestion ;
- OpenAPI et client TypeScript régénéré ;
- tests d'autorisation, de validité et de calcul.

Impacts front :
- page de connexion et écran de liste des projets ;
- page détail projet avec onglets Planning / Devis / Reste à engager / Analytique ;
- menu utilisateur avec préférences, déconnexion et accès admin ;
- données de tables éditables pour la hiérarchie de tâches et les lignes de devis ;
- autorisations d'accès et isolation propriétaire projet.

Commit cible : `feat(estimate): expose estimate workflow and analysis API`

### 7. Grille de devis frontend

Créer l'interface de gestion du projet avec une séparation claire entre planification et devis. La planification reste une vue de dates / hiérarchie / dépendances, tandis que le devis est une structure de coût distincte des tâches, même si elle peut leur être rattachée.

Livrables front :
- page de login sobre, sans visuel trop marketing ;
- page liste des projets en table avec recherche, sélection multiple, pagination et menu utilisateur en haut à droite ;
- page détail projet avec onglets distincts pour Planning, Devis, Reste à engager et Analytique ;
- écran Planning : table éditable des tâches, hiérarchie, durée, dépendances et statut ;
- vue Gantt en lecture seule sous la table pour valider visuellement la planification ;
- écran Devis : table éditable des lignes de coût, type de coût, catégorie, quantité, unité, budget, affectation à des tâches ;
- ajout de ressource ou de ligne de coût via action contextuelle ou panneau latéral, sans surcharge dans le gantt ;
- export Excel du devis depuis l'en-tête du projet ;
- mise en forme sobre pro/enterprise, sans visuel trop “grand public”.

Structure UX cible :
- Planning = édition de la structure de projet et ses dates ;
- Devis = édition du coût et des postes de dépenses ;
- Gantt = visualisation objective, pas source d'édition ;
- table = source principale de saisie ;
- menu utilisateur = préférences, déconnexion, admin users, configuration.

Commit cible : `feat(frontend): add editable estimate grid`

### 8. Analyse et exports

Ajouter les écrans d'analyse et d'export avec un niveau de sophistication cohérent avec le produit v0.1 : graphiques lisibles, KPIs et export Excel, sans hypothéquer les étapes ultérieures de pointage réel ou de prévision avancée.

Livrables front :
- onglet Reste à engager : liste des postes de coût, budget et montant à engager, saisie minimale et affichage du solde ;
- onglet Analytique : KPI et tableaux de synthèse ;
- courbes, histogrammes et camemberts pour coûts, années, catégories et répartition ;
- écran de synthèse des écarts budget / coût / engagement / restant ;
- option d'export Excel du devis et des différents états synthétiques ;
- enrichissement visuel du planning dans MS Project uniquement en lecture / visualisation, sans édition de valeurs dans le diagramme.

Choix techniques recommandés :
- composants UI : Radix + shadcn/ui ;
- tableaux complexes : TanStack Table ;
- graphiques : ECharts ;
- gantt de visualisation : Frappe Gantt ou vis-timeline ;
- style : sobre, neutre, entreprise, très lisible.

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
