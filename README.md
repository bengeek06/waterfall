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
    <img alt="Coverage" src="https://img.shields.io/badge/Coverage-pytest--cov-5C7CFA" />
  </a>
</p>

Waterfall est une plateforme de chiffrage et de pilotage financier de projets, reliée à un planning MS Project. Elle permet d’importer ou de construire un planning, d’y affecter des ressources et des coûts, de versionner et valider des devis, puis d’exporter les résultats pour exploitation.

## Licence

Waterfall est distribué sous la licence GNU Affero General Public License v3.0 uniquement (`AGPL-3.0-only`). Consultez [LICENSE](LICENSE) pour les conditions complètes.

## Vue d’ensemble produit

Le flux métier principal est :

```text
MS Project ou création directe
  -> planning versionné
  -> ressources, rôles et calendriers
  -> devis et coûts
  -> validation et budget de référence
  -> exports Excel et MS Project
```

MS Project reste la référence de planification. Waterfall est la référence financière et opérationnelle du projet.

Le produit couvre notamment :

- gestion des projets et des tâches
- gestion des ressources, rôles et catégories de coûts
- construction d’estimations et de lignes de coût avec agrégation métier

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
- import et export XML MS Project
- suivi des tâches, dépendances et hiérarchie de planification
- description enrichie des tâches
- plannings versionnés avec brouillons, validation, référence et lecture seule
- mutations d’arbre, planification et gestion des conflits de révision

### Gestion des ressources
- nœuds de ressource et hiérarchie
- rôles, capacités et affectations
- catégories de coûts, types de coûts et taux horaires
- capacités et affectations de rôles aux tâches
- calendriers de travail et jours non travaillés
- taux d’inflation et coûts associés

### Estimation et budget
- création d’estimations par projet
- versionnement des estimations
- lignes de coût par tâche et catégorie
- agrégation de coûts, unités, heures et budgets
- validation de l’estimation selon les règles métier
- export Excel structuré avec agrégats

### API et intégration
- API REST documentée via OpenAPI
- authentification, renouvellement de session et gestion des utilisateurs
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
- Base UI primitives et TanStack React Table
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
| Base de données | PostgreSQL pour Docker/dev, SQLite pour les tests isolés |
| Frontend | Next.js 16, React 19 |
| Typage | TypeScript, Pyright |
| Qualité | Ruff, ESLint |
| Tests | pytest, Vitest |
| Couverture | pytest-cov, seuil minimal 80% |
| Contrat API | OpenAPI + client généré |

## Démarrage rapide

Toutes les tâches courantes passent par le `Makefile` (`make help` liste l'ensemble des cibles).

### 1) Prérequis
- Python 3.13+
- Node.js 20.19+ (20.x) ou 22.12+
- npm 10+
- Docker (base de données et stack complet)

### 2) Installation

```bash
make venv                   # crée l'environnement Python à la racine du dépôt
source .venv/bin/activate
make install                # backend (editable + dev) + workspaces npm + hooks git
```

`make install` installe les hooks Git `pre-commit` et `pre-push` quand il est lancé
depuis un checkout Git. Pour les réinstaller seuls, utilisez `make hooks`.

### 3) Configuration A : développement natif

Cette configuration lance l’API et le frontend directement sur la machine. PostgreSQL reste lancé dans Docker.
Le backend démarre aussi le seed admin en mode `dev`; `WF_ADMIN_PASSWORD` doit donc être défini dans `.env`.

```bash
make db-up                  # Postgres dans Docker, pour le dev natif
make migrate-up             # applique les migrations Alembic sur la base de dev
make dev                    # backend (uvicorn) + frontend (next dev) — Ctrl-C arrête les deux
```

Si une base de développement a été créée avant cette étape par l'ancien démarrage
automatique, lancez `make migrate-up` une fois. La commande détecte les anciens schémas
créés par `create_all`, restaure les invariants de données portés par les migrations
initiales (calendrier `STANDARD`, jours ouvrés, calendrier par défaut, rôles existants),
puis renseigne `alembic_version` avant d'appliquer les migrations restantes.

```bash
make migrate-up
```

Au démarrage, l'API vérifie que la révision Alembic courante correspond à la tête
attendue. En cas d'écart, elle refuse de démarrer avec un message explicite demandant
d'exécuter `make migrate-up`, afin d'éviter une erreur SQL tardive dans un parcours
utilisateur.

Adresses par défaut :

- frontend : `http://localhost:3000`
- API : `http://localhost:8000`
- documentation API : `http://localhost:8000/docs`

Pour lancer les processus séparément : `make run-backend`, puis `make run-frontend`.
Pour un accès depuis une VM, configurez dans `.env` :

```env
NEXT_PUBLIC_API_BASE_URL=http://<IP_VM>:8000
CORS_ALLOW_ORIGINS=http://<IP_VM>:3000
NEXT_ALLOWED_DEV_ORIGINS=<IP_VM>,localhost,127.0.0.1
SECRET_KEY=<clé-secrète-générée>
```

En local, remplacez `<IP_VM>` par `localhost` et utilisez les ports indiqués ci-dessus.

### 4) Configuration B : stack Docker complet

Cette configuration lance l’API, PostgreSQL, le frontend et les outils d’observabilité dans Docker.
Elle combine [docker-compose.yml](infra/docker/docker-compose.yml), qui définit API + PostgreSQL,
et [docker-compose.full.yml](infra/docker/docker-compose.full.yml), qui ajoute frontend et observabilité.

Depuis la racine du dépôt, renseignez au minimum dans `.env` :

```env
CORS_ALLOW_ORIGINS=http://<IP_VM>:3000
NEXT_PUBLIC_API_BASE_URL=http://<IP_VM>:8000
SECRET_KEY=<clé-secrète-générée>
WF_ADMIN_PASSWORD=<mot-de-passe-local>
PGADMIN_DEFAULT_PASSWORD=<mot-de-passe-local>
GRAFANA_ADMIN_PASSWORD=<mot-de-passe-local>
# ADMIN_BIND_ADDRESS=127.0.0.1
```

La clé secrète et les mots de passe sont obligatoires et ne doivent jamais être commités. Générez
une valeur aléatoire pour `SECRET_KEY`. Pour une VM, utilisez l’adresse IP réellement accessible
depuis le navigateur, pas le nom Docker `api`.

```bash
make up-full                # API + DB + frontend + observabilité
make down                   # arrêt (volumes conservés) — alias : make stop
make logs                   # suivre les logs
```

Le conteneur API applique `alembic upgrade head` avant de démarrer Uvicorn. Un volume
PostgreSQL neuf est donc initialisé par Alembic, et un échec de migration arrête le
démarrage de l'API au lieu de servir une application sur un schéma incomplet.

Si Compose ne charge pas automatiquement le `.env` de la racine, utilisez explicitement :

```bash
docker compose --env-file .env \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.full.yml up --build -d
```

Adresses par défaut :

- frontend : `http://<IP_VM>:3000`
- API : `http://<IP_VM>:8000`
- documentation API : `http://<IP_VM>:8000/docs`
- Grafana : `http://127.0.0.1:3001`
- Prometheus : `http://127.0.0.1:9090`
- pgAdmin : `http://127.0.0.1:5050`

`docker-compose.yml` utilisé seul ne lance pas le frontend. Il fournit uniquement l’API et PostgreSQL.
PostgreSQL et les outils d’observabilité sont limités à la VM par défaut. Utilisez un tunnel SSH
ou définissez `ADMIN_BIND_ADDRESS` uniquement si ces interfaces doivent être accessibles à distance,
avec un filtrage réseau adapté.

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

Le backend est couvert par une suite de tests automatisés. La couverture publiée doit être
mise à jour depuis le dernier rapport de test ; le seuil configuré est de 80%.

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

Le dépôt inclut les éléments nécessaires au développement et à un déploiement de test :

- conteneurisation backend
- conteneurisation frontend
- PostgreSQL et stockage persistant des imports
- Prometheus, Grafana et pgAdmin dans la stack complète
- configuration CORS et URL publique du frontend par variables d’environnement
- script de seed admin idempotent

## État du projet

### Livré

- authentification et gestion des utilisateurs
- projets, tâches et structures de planning
- import/export XML MS Project
- ressources, rôles, capacités, coûts et calendriers
- estimations versionnées, validation et export Excel
- cycle de vie des plannings, lecture seule, mutations et robustesse E4
- contrat OpenAPI et client TypeScript généré
- tests backend et frontend, contrôles lint et typage

### Suite prévue

Les travaux restant à planifier ou à finaliser sont suivis dans les issues GitHub, notamment :

- E6 : enrichissement du devis, codes d’imputation, avertissements de couverture et round-trip Excel
- dette technique du rôle pouvant appartenir à plusieurs services
- tests E2E navigateur, différés jusqu’à stabilisation complète de l’interface planning

E4 est considéré comme livré. Les tests E2E navigateur associés restent un chantier séparé et différé.

## Documentation métier

La spécification [docs/devis-v0.1-specification.md](docs/devis-v0.1-specification.md) décrit les règles
de devis, les types de lignes, les calculs, les versions et les exports. Elle peut contenir des
évolutions prévues : les fonctionnalités disponibles doivent être vérifiées dans la section
« État du projet » et dans l’interface/API courante.

## Statut du dépôt

Waterfall est un projet applicatif en développement orienté vers la structuration de plannings,
le chiffrage et le suivi budgétaire, la gestion des ressources et capacités, ainsi que l’analyse
et l’export des données de projet.

Pour les commandes et contrôles spécifiques au backend, consultez
[apps/backend/README.md](apps/backend/README.md).
