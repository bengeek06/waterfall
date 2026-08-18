# Devis v0.1

## Objectif

Permettre, pour un projet Waterfall :

1. d'importer ou de créer un planning ;
2. d'affecter des ressources et des coûts aux tâches ;
3. d'ajouter des coûts globaux au projet ;
4. de calculer, versionner et valider un devis ;
5. d'exporter un classeur Excel et un planning MS Project enrichi pour visualisation ;
6. d'analyser les coûts et charges du devis.

MS Project reste la référence de planification. Waterfall est la référence financière et opérationnelle.

## Principes

- Un projet appartient à un utilisateur ; les devis du projet suivent cette même isolation.
- Un devis est modifiable tant qu'il est en brouillon. Une version validée est immuable.
- Le devis final utilisé pour la commande devient le budget de référence.
- Les lignes de coût conservent un snapshot des codes, libellés, taux et coûts appliqués.
- Une catégorie utilisée ne doit jamais être supprimée physiquement ; elle est désactivée.
- Le planning et le devis peuvent être affichés dans une grille unique, mais une tâche de planning et une ligne financière restent deux objets métier distincts.

## Grille de devis

La grille présente les lignes dans cet ordre :

1. tâches du planning, indentées avec `outline_level` et `outline_number` ;
2. lignes de coûts rattachées à une tâche ;
3. lignes globales du projet pour les frais et unités d'œuvre non rattachés à une tâche.

Les tâches issues du planning sont initialement affichées sans coût. Une tâche peut recevoir plusieurs lignes de main-d'œuvre et plusieurs lignes de fournitures.

Les colonnes cibles sont :

| Colonne | Origine / règle |
| --- | --- |
| Cpt | Code comptable, issu de la catégorie ; non éditable sur une ligne MO |
| Dept | Chemin organisationnel du rôle ; éditable uniquement comme filtre sur une ligne MO |
| Type | Type de coût, éditable |
| Catégorie | Catégorie de coût, éditable et filtrée par type |
| Cat | Code de catégorie, calculé depuis la catégorie |
| Libellé | Nom de tâche ou libellé de coût, éditable selon la nature de ligne |
| Qté | Multiplicateur éditable |
| Heures | Heures éditables pour la MO |
| Taux horaire | Calculé depuis la catégorie de rôle et l'année d'application |
| Débours | Coût unitaire éditable pour les coûts hors MO |
| MO | Calculé |
| Achat | Calculé |
| PRU non chargé | `MO + Achat` |

## Natures de lignes

### Tâche de planning

Une ligne tâche référence `ms_task`. Elle est hiérarchique et est exportable vers MS Project.

Waterfall doit permettre d'ajouter ou supprimer une tâche dans le devis. Une tâche ajoutée est une vraie tâche de planning, exportée vers MS Project. Pour v0.1, ses champs minimaux sont :

- nom ;
- parent de planning ;
- indicateur jalon ;
- position dans l'arborescence.

Les dates, durées et dépendances restent principalement pilotées dans MS Project.

### Ligne de main-d'œuvre

Une ligne MO est toujours rattachée à une tâche.

Le choix suit le filtre :

```text
Direction / département / sous-service -> rôles disponibles
```

Les rôles de tous les descendants du nœud organisationnel sélectionné sont éligibles. La catégorie MO est celle du rôle.

Calcul :

$$MO = Qté \times Heures \times TauxHoraire$$

`Qté` peut représenter un effectif ou une convention de conversion, notamment jours vers heures. Les calendriers préciseront ultérieurement les règles telles que $1\ jour = 7{,}4\ heures$.

Une même tâche peut recevoir plusieurs rôles avec des quantités et heures distinctes.

### Ligne de fourniture

Une fourniture est normalement rattachée à une tâche jalon de commande ou de livraison créée dans le planning. Cette convention facilite la disponibilité matérielle et le cashflow, mais n'est pas une contrainte technique v0.1.

Calcul :

$$Achat = Qté \times Débours$$

### Ligne de frais

Un frais peut être global au projet, sans tâche associée.

Exemples : assurances, déplacements, provisions pour aléas.

### Ligne d'unité d'œuvre

Une unité d'œuvre peut être globale au projet, sans tâche associée.

Exemple : indemnité de déplacement.

## Référentiel de coûts

Les types de coût sont configurables et extensibles. v0.1 initialise :

- `MO` : Main d'œuvre ;
- `FOURNITURE` ;
- `FRAIS` ;
- `UO` : Unité d'œuvre.

Chaque `CostCategory` appartient à un type de coût et définit :

- code de catégorie (`Cat`) ;
- libellé ;
- code comptable (`Cpt`) ;
- statut actif/inactif ;
- règles de coût applicables.

Pour la MO, la catégorie est portée par le rôle et le taux horaire est défini par année. Pour les autres types, le débours est saisissable et pourra ultérieurement être prérempli par catégorie.

Le code comptable est un paramétrage ERP. Il servira notamment aux analyses de volume d'achat et aux règles de marge futures.

## Modèle cible

```text
CostType
  id, code, name, is_active

CostCategory
  id, cost_type_id, code, accounting_code, name, is_active

Estimate
  id, project_id, version_number, kind, status, currency_code
  created_at, validated_at, reference_estimate_id, note

EstimateTaskRow
  id, estimate_id, task_id, parent_task_id, position
  snapshot_task_name, snapshot_outline_number, snapshot_outline_level

EstimateCostLine
  id, estimate_id, task_id nullable, cost_type_id, cost_category_id nullable
  role_id nullable, accounting_code, category_code, label
  quantity, hours nullable, hourly_rate nullable, unit_cost nullable
  labor_cost, purchase_cost, unburdened_unit_cost
  source_line_id nullable, status nullable
```

Une ligne MO impose `task_id`, `role_id`, `hours` et `hourly_rate`. Les lignes fourniture, frais et UO imposent un type, une catégorie et un débours. Les contraintes de base doivent empêcher les combinaisons incohérentes.

## Versions de devis

Les versions utilisent les natures suivantes :

- `initial` : devis de chiffrage ;
- `contract_reference` : devis validé servant de budget de référence ;
- `forecast_remaining` : estimation périodique du reste à engager.

Les statuts sont :

- `draft` : modifiable ;
- `validated` : immuable ;
- `superseded` : remplacé par une version plus récente ;
- `archived` : conservé sans usage opérationnel.

Le reste à faire utilise la même structure de lignes que le devis initial. Chaque ligne de prévision peut référencer la ligne budgétaire source afin de comparer :

```text
budget de référence / engagé / reste à engager / prévision à terminaison
```

Les fournitures recevront un état minimal : `planned`, `ordered`, `received`, `cancelled`.

## Calcul temporel

Pour une ligne MO couvrant plusieurs années, Waterfall répartit les heures selon les dates de la tâche et applique les taux annuels ainsi que les coefficients d'inflation applicables.

En l'absence de calendrier détaillé, v0.1 répartit les heures uniformément sur la période de la tâche. Cette règle devra rester explicite dans les résultats de calcul.

## Export

### Excel

Le classeur exporté doit contenir au minimum :

- la grille du devis ;
- les sous-totaux MO, Achat et PRU non chargé ;
- les agrégats par type, catégorie, code comptable et département ;
- la version, le statut et la date du devis.

### MS Project

L'export MS Project vise la visualisation, pas une synchronisation bidirectionnelle parfaite.

- Les tâches ajoutées dans Waterfall deviennent de vraies tâches MS Project.
- Les coûts, rôles et charges peuvent être synthétisés dans les notes ou champs personnalisés.
- Le détail financier complet et l'historique des devis restent la responsabilité de Waterfall.

## Analyse v0.1

Les premières analyses doivent couvrir :

- répartition des coûts par type, catégorie, code comptable et département ;
- charge MO par rôle et nœud organisationnel ;
- budget de référence contre reste à engager ;
- synthèse des achats et frais.

Les graphiques et plans de charge reposent sur ces agrégats. Le Gantt reste une évolution ultérieure, après définition des calendriers et de la capacité.

## Séquence de réalisation

1. référentiel `CostType` / `CostCategory` / code comptable ;
2. modèles de devis versionné et lignes de coût ;
3. affectations MO rôle-tâche ;
4. API et calculs déterministes ;
5. grille de devis frontend ;
6. export Excel ;
7. enrichissement MS Project de visualisation ;
8. analyses et graphiques.