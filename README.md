# Waterfall

<p align="center">
  <img src="apps/frontend/public/waterfall_logo.svg" alt="Waterfall logo" width="320" />
</p>

<p align="center">
  <a href="https://www.python.org/">
    <img alt="Python 3.13" src="https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white" />
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.116-009688?logo=fastapi&logoColor=white" />
  </a>
  <a href="https://nextjs.org/">
    <img alt="Next.js 16" src="https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white" />
  </a>
  <a href="https://react.dev/">
    <img alt="React 19" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" />
  </a>
  <a href="https://www.sqlalchemy.org/">
    <img alt="SQLAlchemy" src="https://img.shields.io/badge/SQLAlchemy-2.x-CC2927?logo=sqlalchemy&logoColor=white" />
  </a>
  <a href="https://www.openapis.org/">
    <img alt="OpenAPI" src="https://img.shields.io/badge/OpenAPI-3.x-6BA539?logo=openapiinitiative&logoColor=white" />
  </a>
  <a href="https://pytest.org/">
    <img alt="Pytest" src="https://img.shields.io/badge/Pytest-8.x-0A9EDC?logo=pytest&logoColor=white" />
  </a>
  <a href="https://github.com/pytest-dev/pytest-cov">
    <img alt="Coverage 86.94%" src="https://img.shields.io/badge/Coverage-86.94%25-5C7CFA" />
  </a>
</p>

Waterfall est une plateforme de pilotage de projets, de ressources et d’estimations. Elle aide à structurer un plan de travail, gérer les ressources, établir des coûts et valider des estimations dans un flux cohérent, depuis la création du projet jusqu’à l’exploitation de l’estimation finale.

## Vue d’ensemble produit

Waterfall s’adresse à un besoin très concret : transformer un projet en plan exploitable, analyser les charges, gérer les rôles et les coûts, puis produire une estimation fiable et exportable. Le produit couvre trois grands axes :

- gestion des projets et des tâches
- gestion des ressources, rôles et catégories de coûts
- construction d’estimations et de lignes de coût avec aggregation métier

Le cœur fonctionnel repose sur une logique de planning et de coût qui reste cohérente entre :

- le projet
- les tâches et sous-tâches
- les rôles affectés
- les types de coûts
- les catégories de dépenses
- les estimations et leurs validations

## Fonctionnalités clés

### Gestion de projet
- création de projets avec code, description, devise
- suivi des tâches et hiérarchie de planification
- description enrichie des tâches
- export/import de structures de projet et de planning

### Gestion des ressources
- nœuds de ressource et hiérarchie
- rôles, capacités et affectations
- catégories de coûts, types de coûts et taux horaires
- gestion des taux d’inflation et des coûts associés

### Estimation et budget
- création d’estimations par projet
- versionnement des estimations
- lignes de coût par tâche et catégorie
- agrégation de coûts, unités, heures et budgets
- validation de l’estimation selon les règles métier

### API et intégration
- API REST documentée via OpenAPI
- schémas de validation stricts en Pydantic
- contrat API stable et versionné par code
- génération de client TypeScript à partir du contrat OpenAPI

## Architecture technique

### Monorepo

```text
.
├── apps/
│   ├── backend/      # API FastAPI + modèles SQLAlchemy + tests
│   └── frontend/     # application web Next.js + interface utilisateur
├── packages/
│   └── api-client-ts # client TypeScript généré
├── openapi/          # spécification OpenAPI (spec/ = source éclatée, waterfall_v1.yaml = bundle généré)
├── docs/             # documentation métier
├── infra/            # infrastructure / déploiement
├── package.json      # scripts racine du workspace
├── README.md         # documentation principale
└── Makefile          # tâches de dev et d’intégration
```

### Backend
Le backend est construit sur :

- Python 3.13
- FastAPI pour les routes API et la documentation interactive
- SQLAlchemy 2.x pour le modèle ORM
- Pydantic v2 pour validation et schémas
- Alembic pour les migrations
- pytest + pytest-cov pour validation et couverture
- ruff + pyright pour qualité et typage

### Frontend
Le frontend est construit sur :

- Next.js 16
- React 19
- TypeScript
- Radix UI primitives
- Vitest + Testing Library pour les tests UI

### API et contrat
Le projet est pensé comme une application de type API-first :

- le backend expose une API REST stricte
- le contrat est documenté et vérifié par OpenAPI
- le client TypeScript est généré à partir de cette spécification
- les validations métier sont centralisées dans les schémas Pydantic

## Stack produit

| Domaine | Technologie |
| --- | --- |
| Backend | FastAPI, Python 3.13 |
| ORM | SQLAlchemy 2.x |
| Validation | Pydantic v2 |
| Base de données | SQLite dev, compatible PostgreSQL/enterprise |
| Frontend | Next.js 16, React 19 |
| Typage | TypeScript, Pyright |
| Qualité | Ruff, ESLint |
| Tests | pytest, Vitest |
| Couverture | pytest-cov |
| Contrat API | OpenAPI + client généré |

## Démarrage rapide

Toutes les tâches courantes passent par le `Makefile` (`make help` liste l'ensemble des cibles).

### 1) Prérequis
- Python 3.13+
- Node.js 20+
- npm
- Docker (base de données et stack complet)

### 2) Installation

```bash
source .venv/bin/activate   # environnement Python à la racine du dépôt
make install                # backend (editable + dev) + workspaces npm
make hooks                  # installe les hooks git (pre-commit + pre-push)
```

### 3) Développement local (natif)

```bash
make db-up                  # Postgres dans Docker, pour le dev natif
make dev                    # backend (uvicorn) + frontend (next dev) — Ctrl-C arrête les deux
```

Ou séparément : `make run-backend`, `make run-frontend`.

### 4) Stack complet en conteneurs

```bash
make up-full                # api + db + frontend + observabilité
make down                   # arrêt (volumes conservés) — alias : make stop
make logs                   # suivre les logs
```

### 5) Vérifications

```bash
make lint                   # ruff (backend) + eslint (frontend)
make typecheck              # pyright (backend) + tsc --noEmit (frontend)
make test                   # pytest (backend) + vitest (frontend)
```

Chaque cible existe aussi en version ciblée : `make lint-backend`, `make test-frontend`, etc.

### 6) Nettoyage

```bash
make clean                  # caches Python/Next + sorties de build
make clean-docker           # arrêt du stack + suppression des volumes (données DB perdues)
make distclean              # + node_modules et .venv
```

## Qualité et couverture

Le backend est couverte par une suite de tests automatisés. La couverture actuelle mesurée est de :

- 86.49% de couverture globale
- validation de la qualité via ruff et pyright
- couverture minimale de 80% configurée dans pytest

## Points de conception importants

Le projet est structuré pour rester lisible et évolutif :

- validation métier au niveau des schémas
- séparation nette entre API, modèles, services et UI
- logique de calcul et règles métier distinctes de la couche de présentation
- contrat API stable pour éviter les dérives de données entre backend et frontend

### Cycle de vie des plannings

Un projet conserve des versions indépendantes de planning. Chaque version est créée en
`draft`, peut être `validated`, puis devenir `superseded` lorsqu'une nouvelle référence
est définie; l'historique reste consultable. Une référence ne peut être définie qu'après
validation, et une version validée est immuable.

Le projet persiste aussi la version affichée. L'interface charge les métadonnées des
versions, puis le détail de la version sélectionnée; les lectures de tâches et d'arbre
respectent cette sélection. La création initiale d'une structure initialise le projet.
La réouverture crée un nouveau brouillon à partir de la référence validée, ou réutilise
le brouillon existant.

Les imports MS Project restent des brouillons jusqu'à validation explicite. La validation
rend le brouillon courant `validated`; elle ne crée pas de nouvelle version. Lorsqu'un
brouillon existe déjà, l'import avertit puis le remplace dans ce brouillon, sans modifier
les versions validées.

## Déploiement et environnement

Le dépôt inclut des éléments d’environnement de développement et d’exploitation :

- conteneurisation backend
- configuration d’outils de monitoring et observabilité
- environnement de dev local avec services annexes
- scripts de setup et de seed admin

## Rôles du projet

Waterfall vise à devenir une base solide pour :

- piloter des projets de planification
- calculer les coûts et budgets
- gérer les ressources et affectations
- centraliser les données de devis et d’estimation
- exporter les données vers des formats de travail standardisés

## Licence et statut

Ce dépôt est un projet de développement interne / applicatif orienté produit. Le code et la structure sont pensés pour évoluer vers une solution de gestion de planification et de budget en environnement professionnel.

---

Pour une documentation plus orientée métier, consultez :
- [docs/push-ready-checklist.md](docs/push-ready-checklist.md)
- [apps/backend/README.md](apps/backend/README.md)
