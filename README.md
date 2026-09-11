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

Cette configuration lance l’API et le frontend directement sur la machine. PostgreSQL et
Garage (stockage objet S3) restent lancés dans Docker ; Redis est facultatif (voir plus bas
`REDIS_URL=memory://`).
Le backend démarre aussi le seed admin en mode `dev`; `WF_ADMIN_PASSWORD` doit donc être défini dans `.env`.

Renseignez au minimum dans `.env` :

```env
SECRET_KEY=<clé-secrète-générée>
WF_ADMIN_PASSWORD=<mot-de-passe-local>
REDIS_PASSWORD=<mot-de-passe-local>
GARAGE_ACCESS_KEY_ID=GK<24-caractères-hexadécimaux>
GARAGE_SECRET_ACCESS_KEY=<64-caractères-hexadécimaux>
GARAGE_RPC_SECRET=<64-caractères-hexadécimaux>
GARAGE_ENDPOINT_URL=http://localhost:3900
PGADMIN_DEFAULT_PASSWORD=<mot-de-passe-local>
GRAFANA_ADMIN_PASSWORD=<mot-de-passe-local>
```

`REDIS_PASSWORD` et les trois variables `GARAGE_*` sont obligatoires même ici, et même si vous
laissez `REDIS_URL` sur `memory://` : les services `redis` et `garage` du compose de base les
exigent sans valeur par défaut, et Compose interpole tout le fichier avant de choisir les
services — sans elles, `make db-up` et `make logs` échouent aussi.

`PGADMIN_DEFAULT_PASSWORD` et `GRAFANA_ADMIN_PASSWORD` sont requis ici pour une autre raison :
non pas parce que pgAdmin et Grafana tournent en Configuration A — ils ne tournent pas —, mais
parce que les cibles d'arrêt et de nettoyage (`make down`, `make stop`, `make clean-docker`,
`make distclean`) passent par le compose **complet**, donc Compose interpole aussi
`docker-compose.full.yml`. Sans ces deux variables, `make db-up` et `make dev` fonctionnent,
puis `make down` échoue sur `db-viewer`, un service jamais démarré.

Garage impose le format de ses identifiants S3 : la clé d'accès est `GK` suivi de 24 caractères
hexadécimaux, la clé secrète en compte exactement 64. Générez un jeu complet avec :

```bash
echo "GARAGE_ACCESS_KEY_ID=GK$(openssl rand -hex 12)"
echo "GARAGE_SECRET_ACCESS_KEY=$(openssl rand -hex 32)"
echo "GARAGE_RPC_SECRET=$(openssl rand -hex 32)"
```

Une clé d'accès n'est jamais réattribuable dans Garage : pour changer la clé secrète, changez
aussi `GARAGE_ACCESS_KEY_ID` (le service d'initialisation refuse de démarrer, avec un message
explicite, si l'identifiant existe déjà avec un autre secret).

L'API refuse toute connexion si le limiteur de tentatives est injoignable (*fail-closed* :
`503`, jamais un login accepté sans vérification). Dès que `REDIS_URL` pointe sur un
`redis://`, Redis doit donc tourner et `REDIS_URL`/`REDIS_PASSWORD` doivent être renseignés,
sinon 100 % des `POST /auth/token` renvoient `503`. Laissez le mot de passe hors de l'URL :
il n'est pas encodé en pourcents.

`REDIS_URL` vaut `memory://` par défaut : le limiteur tourne alors dans le process, sans
serveur, comme `DATABASE_URL` retombe sur SQLite. Les compteurs ne sont ni partagés entre
instances ni conservés au redémarrage — réservez-le au poste de développement et à la suite de
tests, et pointez `REDIS_URL` sur un vrai Redis partout ailleurs (c'est ce que fait
`docker-compose.yml`).

Les sources MS Project importées sont stockées dans Garage, plus sur disque : `POST
/imports/v1/batches/{id}/xml`, `.../run` et `.../diff` renvoient `503` tant que le stockage
objet est injoignable (le batch reste `pending`, l'import est rejouable tel quel).

```bash
make db-up                  # Postgres dans Docker, pour le dev natif
# Redis (facultatif : sans lui, REDIS_URL=memory://) et Garage (requis par les imports).
# `garage-init`
# crée le layout, la clé et le bucket ; il est idempotent et se relance sans risque.
docker compose --env-file .env -f infra/docker/docker-compose.yml up -d redis garage garage-init
make migrate-up             # applique les migrations Alembic sur la base de dev
make dev                    # backend (uvicorn) + frontend (next dev) — Ctrl-C arrête les deux
```

Si une base de développement a été créée avant cette étape par l'ancien démarrage
automatique, lancez `make migrate-up` une fois. La commande détecte les anciens schémas
créés par `create_all`, restaure les invariants de données portés par les migrations
initiales (calendrier `STANDARD`, jours ouvrés, calendrier par défaut et, si
`STANDARD` est actif, rôles existants sans calendrier propre),
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
Elle combine [docker-compose.yml](infra/docker/docker-compose.yml), qui définit l'API, PostgreSQL,
Redis et Garage (`garage` + `garage-init`), et
[docker-compose.full.yml](infra/docker/docker-compose.full.yml), qui ajoute frontend et observabilité.

Depuis la racine du dépôt, renseignez au minimum dans `.env` :

```env
CORS_ALLOW_ORIGINS=http://<IP_VM>:3000
NEXT_PUBLIC_API_BASE_URL=http://<IP_VM>:8000
SECRET_KEY=<clé-secrète-générée>
WF_ADMIN_PASSWORD=<mot-de-passe-local>
REDIS_PASSWORD=<mot-de-passe-local>
GARAGE_ACCESS_KEY_ID=GK<24-caractères-hexadécimaux>
GARAGE_SECRET_ACCESS_KEY=<64-caractères-hexadécimaux>
GARAGE_RPC_SECRET=<64-caractères-hexadécimaux>
PGADMIN_DEFAULT_PASSWORD=<mot-de-passe-local>
GRAFANA_ADMIN_PASSWORD=<mot-de-passe-local>
# ADMIN_BIND_ADDRESS=127.0.0.1
```

Ces sept variables sont toutes obligatoires, mais pas au même titre. `REDIS_PASSWORD` et les
trois variables `GARAGE_*` sont exigées par le compose de **base** : elles conditionnent aussi
`make db-up` et `make logs`, qui ne lancent pourtant ni Redis ni Garage.
`PGADMIN_DEFAULT_PASSWORD` et `GRAFANA_ADMIN_PASSWORD` ne sont lues que par le compose complet,
donc par `make up-full` — mais aussi par `make down`, `make stop`, `make clean-docker` et
`make distclean`, qui passent tous par ce même fichier. Aucune des sept n'est donc limitée aux
services qu'elle configure : Compose interpole le fichier entier avant de choisir les services.
Le compose transmet le
mot de passe Redis à l'API via `REDIS_PASSWORD` (et non dans `REDIS_URL`), pour qu'un caractère
`/`, `+` ou `@` issu d'un `openssl rand -base64 24` ne soit pas interprété comme un séparateur
d'URL ; les identifiants S3 sont transmis de la même façon, hors de `GARAGE_ENDPOINT_URL`.

En Docker, l'API attend que le service `garage-init` se termine avec succès : il applique le
layout du nœud Garage, importe la clé d'accès telle qu'elle figure dans `.env` (`garage key
import`, et non `key create` qui générerait des identifiants aléatoires) et crée le bucket
`waterfall-imports`. Chaque étape est idempotente : relancer `make up` sur une stack déjà
initialisée ne change rien et sort en succès. Les données vivent dans les volumes
`garage_meta` (métadonnées) et `garage_data` (objets) — `make clean-docker` les supprime, ce
qui efface les sources d'import déjà téléversées.

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

Grafana arrive provisionné : la source de données Prometheus et deux dashboards du dossier
`Waterfall` sont créés au démarrage depuis
[infra/docker/grafana/provisioning](infra/docker/grafana/provisioning), monté en lecture seule.

- **Waterfall — API & devis** (`/d/waterfall-api-estimates`) : débit et latence HTTP par route,
  durée des calculs de devis.
- **Waterfall — Dépendances** (`/d/waterfall-dependencies`) : état de PostgreSQL, Redis et Garage
  tel que publié par `GET /health/ready`.

Ces dashboards ne se modifient pas depuis l'interface (`allowUiUpdates: false` : Grafana refuse
l'enregistrement) mais en éditant les JSON du dépôt. C'est ce qui garantit que supprimer le volume
`grafana_data` et relancer `make up-full` les restaure à l'identique. Les panneaux restent vides
tant que la métrique correspondante n'a pas été produite : le débit HTTP démarre à la première
requête **applicative** servie, les durées de calcul au premier devis validé ou agrégé, et l'état
des dépendances au premier appel de `/health/ready` (que le healthcheck du conteneur `api`
déclenche toutes les 15 s).

Les panneaux HTTP **agrégés** excluent les chemins de sonde (`path!~"/metrics|/health(/ready)?"`).
La stack `up-full` s'appelle elle-même en permanence — scrape Prometheus toutes les 15 s,
healthcheck Docker toutes les 15 s, soit un plancher d'environ 0,133 req/s — et une dépendance
tombée ferait répondre `/health/ready` en 503 toutes les 15 s : sans ce filtre, le débit 5xx et la
latence p95 passeraient au rouge pendant une panne que le dashboard « Dépendances » diagnostique
déjà correctement. Les panneaux **par route** ne sont pas filtrés, c'est là qu'on lit le trafic de
sonde.

`docker-compose.yml` utilisé seul ne lance ni le frontend ni l’observabilité. Il fournit l’API,
PostgreSQL, Redis et Garage (`garage` + `garage-init`).
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

#### Complexité (ESLint `complexity` / backend Ruff C90)

Le frontend applique la règle native ESLint `complexity` (même métrique McCabe
que Ruff C90 côté backend, voir `apps/backend/README.md`) avec un seuil de
complexité cyclomatique fixé à 15 (`apps/frontend/eslint.config.mjs`). C'est la
seule métrique de complexité retenue pour ce frontend, symétrique à la décision
backend : ce même seuil s'applique en local et en CI (job `frontend-quality`),
puisqu'ils lisent tous la configuration ESLint partagée.

Si une fonction dépasse légitimement ce seuil (cas résiduel documenté), la
suppression du diagnostic avec `// eslint-disable-next-line complexity` doit
obligatoirement s'accompagner d'un commentaire renvoyant vers l'issue de suivi
qui trace sa décomposition.

```bash
npx eslint --rule '{"complexity": ["error", 15]}' apps/frontend/src
```

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
