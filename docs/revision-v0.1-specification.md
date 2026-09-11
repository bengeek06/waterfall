# Révision v0.1

## Objectif

Faire porter par une seule structure de données l'arborescence d'un projet, aujourd'hui dupliquée
entre le planning (`ms_task` + `wf_planning_task_snapshot`) et le devis (`wf_estimate_task_row` +
`wf_estimate_grid_node`).

Le modèle repose sur quatre entités :

- `work_item` : l'identité stable d'un élément de travail **à travers les versions** du projet ;
- `ProjectRevision` : une version du projet, qui porte l'arbre **une seule fois** ;
- `node` : une position de l'arbre d'une révision, définie par
  `(révision, work_item, parent, position)` ;
- deux **facettes** accrochées au nœud : la **planification** (durée, dates, prédécesseurs,
  calendrier, avancement) et le **coût** (catégorie, quantité, débours pour le non-MO ; rôle et
  heures pour la MO).

Le couple planning + devis **est** la révision. Supprimer, ajouter, déplacer ou indenter un élément
d'un côté se voit immédiatement de l'autre — non par propagation, mais parce qu'il n'y a qu'un seul
arbre.

Ce document est la référence du modèle. Il prévaut sur la section « Modèle cible » de
`docs/devis-v0.1-specification.md`, qui décrivait `EstimateTaskRow` et
`EstimateCostLine.source_line_id` comme cibles et qui renvoie désormais ici.

Le livrable central de ce document est la [liste numérotée des invariants](#invariants). Chaque
invariant est énoncé comme une assertion vraie ou fausse sur un état de révision, de façon à être
transposé directement en test par le banc d'essai de domaine pur (E14-02).

## Entités du modèle

### `work_item` — identité stable d'un élément de travail

Un `work_item` est l'identité d'un élément de travail dans un projet, indépendamment de toute
version. C'est le seul lien d'identité entre deux révisions : comparer un reste à engager à son
budget de référence, ou retrouver dans une révision ce qui correspond à un nœud d'une autre, se fait
par `work_item` et par rien d'autre.

| Attribut | Sémantique |
| --- | --- |
| `id` | identité technique, stable pour toute la vie du projet |
| `project_id` | projet propriétaire ; un `work_item` n'est jamais partagé entre deux projets |
| `kind` | `task` ou `cost` : la nature de l'élément, invariable d'une révision à l'autre |
| `description` | texte libre documentaire, commun à toutes les révisions (reprend la sémantique actuelle de `wf_task_enrichment`, déjà porté au niveau projet) |
| `external_uid` | uid MS Project, identifiant **externe** de la couche import/export (voir [Ce que le modèle n'est pas](#ce-que-le-modèle-nest-pas)) ; nul pour un `work_item` de nature `cost`, nul également pour tout élément créé dans Waterfall et jamais exporté |
| `created_at`, `updated_at` | horodatages techniques |

Le `work_item` **ne porte pas de libellé**. Le nom d'une tâche et le libellé d'une ligne de coût
appartiennent à la facette, donc à une révision donnée : renommer une tâche dans un brouillon ne
doit jamais modifier ce que montre une révision validée.

`description` est délibérément hors du champ de l'immuabilité d'une révision : c'est un attribut
documentaire de projet, pas un élément du document financier. Tout ce qui doit rester figé dans une
révision validée est recopié au moment de la validation dans les
[lignes figées](#lignes-figées-dun-devis-validé).

### `ProjectRevision` — une version du projet

Une révision est une version complète du projet : son arbre, sa planification et son chiffrage.
Table `wf_revision`.

| Attribut | Sémantique |
| --- | --- |
| `id` | identité technique |
| `project_id` | projet propriétaire |
| `version_number` | numéro de version, unique par projet, strictement positif |
| `kind` | `initial`, `contract_reference` ou `forecast_remaining` (reste à engager) |
| `status` | `draft`, `validated` ou `superseded` |
| `source_revision_id` | révision dont celle-ci est issue par copie, nul pour une révision créée de zéro |
| `currency_code` | devise du chiffrage |
| `lock_version` | compteur de verrou optimiste, incrémenté à chaque écriture sur un brouillon ; ce n'est **pas** un numéro de version (il remplace `WfPlanning.revision` et `Estimate.revision`, dont le nom entretenait la confusion) |
| `note` | commentaire libre |
| `created_at`, `validated_at` | horodatages |

Le statut `archived` de `docs/devis-v0.1-specification.md` n'est pas repris : une révision remplacée
est `superseded`, ce qui couvre le même besoin sans quatrième état.

Le projet porte un pointeur unique vers la révision de référence et affichée, qui remplace
`MsProject.planning_reference_id`, `MsProject.displayed_planning_id` et
`MsProject.reference_estimate_id`, ainsi que `Estimate.planning_id` — un devis ne peut plus désigner
un planning différent de celui de sa propre version, puisqu'il n'y a plus de planning séparé du
devis.

### `node` — une position dans l'arbre d'une révision

Table `wf_revision_node`.

| Attribut | Sémantique |
| --- | --- |
| `id` | identité technique du nœud, propre à une révision |
| `revision_id` | révision à laquelle appartient ce nœud |
| `work_item_id` | élément de travail occupant cette position |
| `parent_id` | nœud parent, nul pour un nœud racine |
| `position` | rang dans la fratrie, entier ≥ 1 |

Un nœud ne porte aucune donnée métier : il porte une position et une identité. Toute donnée métier
appartient à l'une de ses deux facettes. Un nœud porte **exactement une** facette (voir
[INV-11](#inv-11)).

`outline_level` et `outline_number` ne sont pas stockés : ils se calculent depuis `parent_id` et
`position`. C'est ce qui supprime la dérive de libellés et de positions que
`EstimateTaskRow`/`resolve_live_task_display` corrigeaient à la lecture.

### Facette planification

Accrochée à un nœud, elle en fait une **tâche**. Table `wf_revision_plan_facet`, une ligne au plus
par nœud.

| Attribut | Sémantique |
| --- | --- |
| `node_id` | nœud porteur, unique |
| `name` | nom de la tâche, propre à cette révision |
| `is_milestone` | jalon |
| `duration_minutes`, `duration_format` | durée et son format d'affichage (round-trip MS Project) |
| `start_at`, `finish_at` | dates de début et de fin |
| `work_minutes` | charge issue du fichier MS Project, conservée pour le round-trip |
| `percent_complete` | avancement, 0 à 100 |
| `is_manual` | mode de planification manuel MS Project |
| `calendar_id` | calendrier de travail applicable, **toujours renseigné** (voir la [règle de calendrier](#règle-1--origine-du-calendrier-dune-tâche)) |
| `calendar_source` | provenance du calendrier : `project`, `role` ou `manual` |

Les prédécesseurs sont des liens **nœud → nœud** au sein d'une même révision, table
`wf_revision_node_link` : `node_id`, `predecessor_node_id`, `link_type` (0 à 3), `lag_tenth_minute`,
`lag_format`. Ils remplacent `ms_task_link` et `wf_planning_link_snapshot`, qui référençaient une
tâche par clé naturelle `(propriétaire, uid)`.

Les dates et durées d'un nœud récapitulatif (un nœud de planification ayant des enfants de
planification) sont **recalculées** depuis ses enfants par le moteur de planification. C'est une
propriété calculée, pas un invariant : le banc d'essai ne doit pas la vérifier comme telle.

### Facette coût

Accrochée à un nœud, elle en fait une **ligne de coût**. Table `wf_revision_cost_facet`, une ligne
au plus par nœud.

| Attribut | Sémantique |
| --- | --- |
| `node_id` | nœud porteur, unique |
| `nature` | `labor` (MO) ou `non_labor` (fourniture, frais, unité d'œuvre) |
| `label` | libellé de la ligne, propre à cette révision |
| `quantity` | multiplicateur, strictement positif, sur les deux natures |
| `role_id` | rôle affecté — MO uniquement |
| `hours` | heures — MO uniquement |
| `cost_type_id`, `cost_category_id` | type et catégorie de coût — non-MO uniquement (pour la MO, la catégorie est celle du rôle) |
| `unit_cost` | débours unitaire — non-MO uniquement |
| `supply_status` | `planned`, `ordered`, `received`, `cancelled` — fournitures |
| `planned_date` | date prévisionnelle de décaissement, indépendante des dates de la tâche porteuse |
| `cost_code_id` | code d'imputation projet (`wf_project_cost_code`) |
| `comment` | commentaire libre |

Les montants dérivés — MO, Achat, PRU non chargé — sont **calculés** par le moteur de calcul à
partir de ces attributs, des taux annuels et des coefficients d'inflation. Ils ne sont pas des
attributs de la facette et ne sont figés qu'au moment de la validation, dans les lignes figées.

La saisie d'un reste à engager n'utilise aucun attribut supplémentaire : c'est la même facette coût,
sur une révision de nature `forecast_remaining`. Le modèle accueille donc le RAE sans changement de
schéma, même si aucune API de saisie n'est livrée par l'EPIC E14.

### Lignes figées d'un devis validé

Au moment de la validation, le chiffrage est matérialisé en lignes figées (table
`wf_revision_frozen_line`, qui remplace `wf_estimate_line`) : un document financier immuable,
indépendant de toute structure mutable.

| Attribut | Sémantique |
| --- | --- |
| `revision_id` | révision validée dont cette ligne fait partie |
| `work_item_id` | identité de l'élément de travail chiffré — le seul lien conservé |
| `bearing_work_item_id` | identité de la tâche porteuse, nulle pour un coût global |
| `label`, `bearing_task_name`, `role_name`, `accounting_code`, `category_code` | libellés recopiés |
| `year`, `quantity`, `hours`, `hourly_rate`, `inflation_coefficient`, `amount` | montants recopiés |

Une ligne figée ne référence **aucun nœud et aucune facette**. C'est exactement ce qui remplace
`EstimateCostLine.source_line_id` : la comparaison budget de référence ↔ engagé ↔ reste à engager se
fait par `work_item_id`, une identité que le modèle fournit nativement, et non par une chaîne de
pointeurs inter-versions reconstruite à la main. `source_line_id`, prévu par
`docs/devis-v0.1-specification.md` et jamais implémenté, ne sera pas créé.

## Cycle de vie d'une révision

| Transition | Déclencheur | Effet |
| --- | --- | --- |
| ∅ → `draft` | création vide, import MS Project, ou copie d'une révision existante | une nouvelle révision modifiable |
| `draft` → `validated` | validation | lignes figées produites, révision immuable |
| `validated` → `superseded` | validation d'une révision plus récente de même nature dans le même projet | révision conservée, toujours immuable |
| `validated` ou `superseded` → `draft` | copie | une **nouvelle** révision ; la source n'est pas modifiée |

Aucune transition ne ramène une révision `validated` ou `superseded` vers `draft` : on n'en obtient
qu'une copie.

- **Création** : une révision naît toujours en `draft`, soit vide, soit par import MS Project, soit
  par copie d'une révision existante (quel que soit le statut de la source). La copie reproduit
  l'arbre et les deux facettes ; chaque nouveau nœud désigne le **même** `work_item` que son
  homologue ([INV-07](#inv-07)).
- **Brouillon** : tout est permis — ajouter, supprimer, déplacer, indenter, réimporter intégralement
  le planning. Aucune garde ne restreint un brouillon, et plusieurs brouillons d'un même projet
  peuvent coexister : une variante de chiffrage est une **variante complète de révision**, donc deux
  arbres distincts.
- **Validation** : la révision passe en `validated`, `validated_at` est horodaté, les lignes figées
  sont produites, et la révision précédemment validée **de même nature** dans le même projet passe
  en `superseded`. Les autres brouillons du projet ne sont pas affectés.
- **Immuabilité** : une révision `validated` ou `superseded` refuse **toute** écriture, sur les deux
  facettes, avec la même erreur. Pour modifier quoi que ce soit, il faut en créer une copie en
  brouillon.

L'immuabilité d'une révision validée est la **seule** garde de protection du travail chiffré. Il
n'existe aucune garde inter-version : rien n'interdit de supprimer dans un brouillon un nœud dont
l'homologue est chiffré dans une autre révision, puisque cette autre révision porte ses propres
nœuds et ses propres facettes et n'est pas touchée. Le service `services/task_references.py`
(`is_task_referenced`, `find_referenced_task_uids`) et le conflit 409 `IMPORT_CONFLICT` qu'il
alimente disparaissent : ils protégeaient le brouillon, c'est-à-dire précisément l'endroit où
l'utilisateur doit avoir tous les droits.

## Règles tranchées

### Règle 1 — Origine du calendrier d'une tâche

Le calendrier est un **attribut de la facette planification**. Il est initialisé au calendrier du
projet à la création du nœud et alimenté depuis le rôle lors d'une affectation. Il n'est **jamais**
dérivé en lecture depuis les rôles.

*Motif* : le flux réel est « planning d'abord, chiffrage ensuite » — import MS Project, puis
construction du devis. Une dérivation en lecture rendrait les dates incalculables sur toute tâche
non encore chiffrée. La facette planification ne doit pas dépendre de la facette coût pour son
calcul.

Le « calendrier du projet » désigne le calendrier de travail applicable par défaut à toutes les
tâches du projet. Tant que le projet ne porte pas de calendrier explicite, c'est le calendrier de
l'organisation marqué `wf_calendar.is_default` — le référentiel actuel n'expose pas d'autre notion de
calendrier de projet (`MsProject.calendar_uid` est un uid MS Project, donc un identifiant externe,
et non une référence à `wf_calendar`). Un calendrier de projet explicite, s'il est ajouté plus tard,
s'insère à cette place sans changer la règle de précédence ci-dessous.

**Règle de précédence.** `calendar_source` enregistre la provenance de la valeur courante et
détermine seul ce qui peut l'écraser, selon l'ordre `manual` > `role` > `project` :

| `calendar_source` | Signification | Peut être réécrit automatiquement |
| --- | --- | --- |
| `project` | valeur héritée par défaut du calendrier du projet | oui |
| `role` | valeur reprise d'une affectation de rôle | oui |
| `manual` | valeur fixée explicitement par l'utilisateur sur la facette | non |

À chaque changement de l'ensemble des affectations MO portées par le sous-arbre d'une tâche —
**affectation ajoutée, modifiée ou retirée** — le calendrier de cette tâche est resynchronisé si et
seulement si `calendar_source` vaut `project` ou `role`. La resynchronisation prend le calendrier du
rôle de la première facette MO, dans l'ordre depth-first du sous-arbre, dont le rôle porte un
calendrier, et positionne `calendar_source` à `role`. S'il n'existe plus aucune facette MO dont le
rôle porte un calendrier, la valeur retombe au calendrier du projet et `calendar_source` repasse à
`project`.

Les trois cas demandés se lisent donc ainsi :

1. **Un rôle est affecté** après que le calendrier a été fixé : si le calendrier était `manual`, il
   est conservé tel quel et l'affectation n'a aucun effet sur lui ; sinon il prend le calendrier
   issu de la resynchronisation ci-dessus.
2. **Une affectation est modifiée** (changement de rôle, donc potentiellement de calendrier) : même
   règle — `manual` est conservé, `project` et `role` sont resynchronisés. Une affectation qui n'est
   pas la première dans l'ordre depth-first peut donc ne produire aucun changement, ce qui est
   voulu : la règle est déterministe et ne dépend pas de l'ordre chronologique des saisies.
3. **Une affectation est retirée** : même règle. Retirer la dernière affectation MO dont le rôle
   portait un calendrier ramène la tâche au calendrier du projet, et non à une absence de
   calendrier — une tâche non chiffrée reste datable ([INV-15](#inv-15)).

Un utilisateur revient au comportement automatique en effaçant son choix explicite : `calendar_source`
repasse alors à `project` ou `role` par application de la même resynchronisation.

Le recalcul des durées et des dates consécutif à un changement de calendrier relève du moteur de
planification et n'est pas un invariant de ce document. Ce qui est invariant, c'est que le
calendrier applicable est toujours lisible sur la facette, sans consulter aucun rôle.

### Règle 2 — Rattachement des lignes figées d'un devis validé

Une ligne figée porte l'identité `work_item` de l'élément de travail chiffré, celle de sa tâche
porteuse, plus des libellés et des montants recopiés. Elle ne référence **aucune structure mutable** :
ni nœud, ni facette, ni ligne d'une autre révision.

*Motif* : un devis validé est un document financier figé, mais la comparaison RAE ↔ budget de
référence doit rester possible **par identité**. C'est précisément ce qui remplace `source_line_id`,
que le modèle rend inutile. Une ligne figée reste lisible et comparable même si toutes les révisions
brouillon du projet ont été supprimées entre-temps.

### Règle 3 — Réimport MS Project dans un brouillon, tâche disparue du fichier

Le nœud disparaît, **ses deux facettes avec lui**, et son sous-arbre entier avec elles. Pas de
remontée à la racine, pas de refus d'import, pas d'arbitrage différé.

*Motif* : c'est la lecture la plus cohérente du principe « un seul arbre, deux facettes ». Le
réimport est une action délibérée sur un brouillon que l'utilisateur maîtrise, et aucune révision
validée n'est affectée.

**Garde-fou obligatoire : la suppression ne doit jamais être silencieuse.** Le diff d'import, déjà
présenté avant confirmation, doit **nommer explicitement** chaque nœud porteur de coût qui sera
supprimé — la tâche disparue elle-même si elle porte du chiffrage dans son sous-arbre, et chacune
des lignes de coût concernées avec son libellé, sa nature MO ou non-MO et son montant courant. Une
suppression de nœud sans chiffrage se signale comme aujourd'hui, par un simple item de diff
`removed`. La sémantique de l'import ne change pas ; seule l'absence d'avertissement est corrigée.

## Invariants

Chaque invariant porte un identifiant stable, un énoncé vérifiable, une **portée** et une manière
canonique de le violer. Deux portées existent :

- **état** : l'assertion se vérifie sur un état de révision isolé, à tout instant ;
- **opération** : l'assertion est une post-condition d'une opération nommée ; elle se vérifie en
  comparant l'état avant et après.

La fonction de vérification d'invariants du banc d'essai (E14-02) évalue les invariants de portée
« état » sur un état de révision et nomme chaque invariant violé.

### Invariants fondateurs

Les huit invariants imposés par la spécification de l'issue #327, dans leur ordre d'origine.

#### INV-01

**La tâche porteuse d'un nœud de coût est son premier ancêtre strict portant une facette de
planification ; elle est indéfinie — coût global — si la racine est atteinte sans en rencontrer.**
La résolution remonte `parent_id` en excluant le nœud lui-même et s'arrête au premier ancêtre
porteur d'une facette de planification. La tâche porteuse n'est jamais stockée.
*Portée : état. Violation : mémoriser sur une ligne de coût une tâche porteuse qui n'est pas son
premier ancêtre de planification, par exemple en la laissant inchangée après un déplacement.*

#### INV-02

**Supprimer un nœud supprime son sous-arbre entier et les deux facettes de chacun des nœuds
supprimés.** Après suppression, aucun nœud descendant, aucune facette de planification, aucune
facette de coût et aucun lien de précédence n'y fait plus référence, et les positions de la fratrie
du nœud supprimé sont renumérotées conformément à [INV-05](#inv-05).
*Portée : opération. Violation : détacher un nœud en remontant ses enfants à son parent, ou laisser
subsister la facette de coût d'un descendant supprimé.*

#### INV-03

**Une révision `validated` ou `superseded` est immuable sur ses deux facettes à la fois : aucune
écriture n'est possible sur l'une sans l'autre.** Toute tentative d'écriture — arbre, facette
planification, facette coût, liens de précédence, lignes figées — est refusée avec la même erreur, et
l'état de la révision est rigoureusement identique avant et après la tentative, `lock_version`
compris.
*Portée : opération. Violation : accepter la modification des heures d'une ligne MO d'une révision
validée, ou accepter un déplacement de nœud au motif qu'il ne touche « que » la planification.*

#### INV-04

**Un `work_item` apparaît au plus une fois dans une révision donnée.** Pour toute révision, la
projection `node → work_item_id` est injective.
*Portée : état. Violation : créer deux nœuds de la même révision désignant le même `work_item`.*

#### INV-05

**Les positions d'une fratrie sont des entiers contigus commençant à 1.** Pour tout parent d'une
révision — y compris la fratrie des nœuds racine, ceux dont `parent_id` est nul — l'ensemble des
`position` des enfants est exactement `{1, 2, …, n}`, où `n` est le nombre d'enfants.
*Portée : état. Violation : supprimer un enfant du milieu sans renuméroter ses frères, ou donner la
même position à deux frères.*

#### INV-06

**Le graphe parent est acyclique : un nœud n'est jamais son propre ancêtre.** En remontant
`parent_id` depuis n'importe quel nœud, on atteint un nœud racine en un nombre fini d'étapes.
*Portée : état. Violation : déplacer un nœud sous l'un de ses propres descendants.*

#### INV-07

**Créer une révision depuis une révision existante reproduit l'arbre et les deux facettes, chaque
nouveau nœud désignant le même `work_item` que son homologue.** La copie a le même nombre de nœuds,
le même ordre depth-first et les mêmes valeurs de facettes ; ses liens de précédence relient les
nœuds de la copie. Aucun nœud de la copie ne partage d'identité de nœud avec la source, et modifier
la copie ne modifie jamais la source.
*Portée : opération. Violation : recopier les facettes en réutilisant les identifiants de nœuds de
la source, ou créer de nouveaux `work_item` pour la copie.*

#### INV-08

**Un prédécesseur désigne un nœud de la même révision.** Pour tout lien de précédence,
`node.revision_id == predecessor.revision_id`.
*Portée : état. Violation : copier une révision en recopiant ses liens sans les retraduire vers les
nœuds de la copie.*

### Invariants complémentaires

Ceux que le modèle implique réellement et que l'énumération d'origine ne couvrait pas. Ils sont
numérotés à la suite et regroupés par thème.

#### Structure de l'arbre

##### INV-09

**Un nœud et son parent appartiennent à la même révision.** Pour tout nœud dont `parent_id` n'est
pas nul, `parent.revision_id == node.revision_id`.
*Portée : état. Violation : rattacher un nœud au parent d'une autre révision.*

##### INV-10

**Le `work_item` désigné par un nœud appartient au même projet que la révision.** Pour tout nœud,
`work_item.project_id == revision.project_id`.
*Portée : état. Violation : insérer dans la révision d'un projet un nœud désignant le `work_item`
d'un autre projet.*

#### Facettes

##### INV-11

**Un nœud porte exactement une facette : planification ou coût, jamais les deux, jamais aucune.**
*Portée : état. Violation : accrocher une facette de coût à un nœud portant déjà une facette de
planification, ou créer un nœud sans lui accrocher de facette.*

##### INV-12

**Aucune facette n'est orpheline.** Toute facette de planification et toute facette de coût
référence un nœud existant de la révision.
*Portée : état. Violation : supprimer un nœud en laissant sa facette en place.*

##### INV-13

**La nature de la facette portée par un nœud est celle de son `work_item`.** Un nœud dont le
`work_item` est de nature `task` porte une facette de planification ; un nœud dont le `work_item`
est de nature `cost` porte une facette de coût. Un `work_item` a donc la même nature dans toutes les
révisions où il apparaît.
*Portée : état. Violation : accrocher une facette de coût à un nœud dont le `work_item` est de
nature `task`.*

##### INV-14

**L'ensemble des nœuds de planification est fermé vers le haut.** Le parent d'un nœud portant une
facette de planification est soit la racine (`parent_id` nul), soit un nœud portant lui aussi une
facette de planification. Un nœud de coût n'a donc jamais de tâche dans son sous-arbre.
*Portée : état. Violation : indenter une tâche sous une ligne de coût.*

#### Facette planification

##### INV-15

**Une facette de planification porte toujours un calendrier.** `calendar_id` n'est jamais nul, et
`calendar_source` vaut `project`, `role` ou `manual`.
*Portée : état. Violation : créer une tâche non chiffrée sans lui donner le calendrier du projet, ou
retirer sa dernière affectation MO sans la ramener au calendrier du projet.*

##### INV-16

**Un nœud n'est jamais son propre prédécesseur.** Aucun lien de précédence n'a
`node_id == predecessor_node_id`.
*Portée : état. Violation : créer un lien d'un nœud vers lui-même.*

##### INV-17

**Les deux extrémités d'un lien de précédence portent une facette de planification.** La précédence
est une notion de la facette planification : une ligne de coût n'a ni prédécesseur ni successeur.
*Portée : état. Violation : créer un lien de précédence depuis ou vers un nœud de coût.*

##### INV-18

**Le graphe de précédence est acyclique.** En suivant les liens de précédence, on ne revient jamais
sur un nœud déjà visité.
*Portée : état. Violation : créer les liens A → B et B → A.*

#### Facette coût

##### INV-19

**Une facette de coût de nature `labor` porte un rôle et un nombre d'heures, et ne porte ni catégorie
de coût propre ni débours.** `role_id` et `hours` sont renseignés ; `cost_type_id`,
`cost_category_id` et `unit_cost` sont nuls — la catégorie d'une ligne MO est celle de son rôle.
*Portée : état. Violation : saisir un débours sur une ligne MO, ou créer une ligne MO sans rôle.*

##### INV-20

**Une facette de coût de nature `non_labor` porte un type de coût, une catégorie et un débours, et ne
porte ni rôle ni heures.** `cost_type_id`, `cost_category_id` et `unit_cost` sont renseignés ;
`role_id` et `hours` sont nuls.
*Portée : état. Violation : saisir des heures sur une ligne de fourniture.*

#### Cycle de vie de la révision

##### INV-21

**Deux révisions d'un même projet n'ont jamais le même `version_number`, et tout `version_number` est
strictement positif.**
*Portée : état. Violation : créer une seconde variante brouillon en réutilisant le numéro de la
première.*

##### INV-22

**Au plus une révision est en statut `validated` par couple (projet, nature).** Les révisions
validées antérieures de la même nature sont en `superseded`.
*Portée : état. Violation : valider une seconde révision `contract_reference` sans basculer la
précédente en `superseded`.*

#### Lignes figées

##### INV-23

**Une ligne figée ne référence aucune structure mutable.** Elle porte un `work_item_id`, un
`bearing_work_item_id` éventuellement nul, des libellés et des montants recopiés — et aucun
identifiant de nœud, de facette ou de ligne d'une autre révision.
*Portée : état. Violation : conserver sur une ligne figée l'identifiant du nœud dont elle est issue.*

##### INV-24

**Les lignes figées n'existent que pour une révision `validated` ou `superseded`.** Un brouillon n'en
porte aucune ; une révision validée en porte une par facette de coût existante au moment de la
validation.
*Portée : état. Violation : produire les lignes figées à la création du brouillon plutôt qu'à la
validation.*

#### Identité externe

##### INV-25

**L'`external_uid` est nul sur un `work_item` de nature `cost`, et unique par projet lorsqu'il est
renseigné.** Plusieurs `work_item` d'un même projet peuvent avoir un `external_uid` nul — ceux créés
dans Waterfall et jamais exportés.
*Portée : état. Violation : attribuer le même uid MS Project à deux `work_item` d'un même projet lors
d'un réimport.*

### Propriétés délibérément non érigées en invariants

Ces propriétés sont vraies en régime normal mais sont **calculées** : elles ne doivent pas être
vérifiées par la fonction de contrôle d'invariants, sous peine de rendre le banc d'essai dépendant
du moteur de calcul.

- les dates et la durée d'un nœud récapitulatif, recalculées depuis ses enfants ;
- `outline_level` et `outline_number`, dérivés de `parent_id` et `position` ;
- les montants MO, Achat et PRU non chargé, dérivés des quantités, heures, taux et coefficients ;
- les domaines numériques (`quantity > 0`, `hours >= 0`, `percent_complete` entre 0 et 100, durées
  non négatives), qui relèvent des contraintes de colonne de la base et non du modèle d'arbre.

## Cas limites

### Un nœud de coût placé à la racine, sans tâche porteuse

**Autorisé.** Sa tâche porteuse est indéfinie et la ligne est un **coût global de projet** — frais
d'assurance, provisions pour aléas, indemnités de déplacement. C'est la branche « racine atteinte
sans rencontrer de facette de planification » de [INV-01](#inv-01), et la ligne figée
correspondante a un `bearing_work_item_id` nul.

### Une tâche sans aucune facette de coût

**Autorisé, et c'est l'état normal après un import.** Une tâche non chiffrée reste entièrement
planifiable : elle a des dates, une durée, des prédécesseurs et un calendrier — celui du projet,
garanti par [INV-15](#inv-15). C'est la raison même pour laquelle le calendrier n'est pas dérivé en
lecture depuis les rôles (voir [Règle 1](#règle-1--origine-du-calendrier-dune-tâche)).

### Une réindentation qui change la tâche porteuse d'une ligne de coût

**Autorisé, et la tâche porteuse change effectivement.** Elle n'est jamais mémorisée : elle se
résout à la lecture par [INV-01](#inv-01). Le montant, le rôle, les heures, la quantité, le débours
et le code d'imputation de la ligne sont inchangés par le déplacement — seule sa position dans
l'arbre change. Réciproquement, déplacer ou indenter une tâche emporte ses lignes de coût, avec
leurs affectations et leurs montants, parce que ce sont ses descendants dans le seul arbre existant.

### Un nœud portant simultanément les deux facettes

**Interdit** ([INV-11](#inv-11)). Trois raisons :

1. **Canonicité.** Une tâche porte couramment plusieurs lignes MO et plusieurs lignes de fourniture.
   Autoriser une facette de coût sur le nœud de la tâche ferait de l'une d'elles une ligne
   privilégiée, représentée autrement que ses sœurs : le même fait métier — « cette tâche coûte
   X » — aurait deux écritures possibles, et toute agrégation, tout export et tout diff d'import
   devraient gérer les deux.
2. **Lisibilité de [INV-01](#inv-01).** La tâche porteuse est définie comme le premier ancêtre
   **strict**. Un nœud mixte poserait la question de savoir s'il est sa propre tâche porteuse, à
   laquelle il n'existe pas de réponse qui reste vraie après un déplacement.
3. **Suppression.** Supprimer une tâche mixte supprimerait simultanément une position d'arbre et une
   ligne financière portées par le même enregistrement, ce qui rend le diff d'import de la
   [Règle 3](#règle-3--réimport-ms-project-dans-un-brouillon-tâche-disparue-du-fichier) impossible à
   énoncer clairement.

Cet arbitrage ne vide pas [INV-01](#inv-01) de son sens : un nœud de coût peut avoir un nœud de coût
pour parent — par exemple une ligne de fourniture regroupée sous une autre — et la remontée vers le
premier ancêtre de planification traverse alors plusieurs niveaux. C'est exactement le cas que la
formulation « premier ancêtre » couvre.

### Un nœud de planification enfant d'un nœud ne portant qu'une facette de coût

**Interdit** ([INV-14](#inv-14)). Une tâche doit rester exportable comme une tâche MS Project et
planifiable par le moteur de dates. Or une ligne de coût n'a ni date, ni durée, ni image dans le
fichier MS Project : une tâche placée sous elle n'aurait pas de parent exportable, et l'export
devrait la remonter silencieusement au premier ancêtre de planification — donc afficher dans
Waterfall une arborescence que le fichier exporté contredit. Le recalcul récapitulatif des dates
devrait par ailleurs traverser un nœud dépourvu de dates.

Conséquence formelle : les nœuds de planification forment la couche supérieure de l'arbre, fermée
vers le haut, et les nœuds de coût ne peuvent apparaître qu'à partir du niveau où l'on quitte
définitivement la planification. Un déplacement dont le parent cible est un nœud de coût est donc
refusé dès lors que le nœud déplacé porte une facette de planification — et comme un nœud de coût
n'a jamais de tâche dans son sous-arbre, il suffit de le vérifier sur le nœud déplacé lui-même.

### La facette coût d'une tâche disparue du fichier lors d'un réimport dans un brouillon

**Supprimée avec le nœud**, ainsi que tout le sous-arbre de la tâche disparue (voir
[Règle 3](#règle-3--réimport-ms-project-dans-un-brouillon-tâche-disparue-du-fichier) et
[INV-02](#inv-02)). Aucune remontée à la racine, aucun refus d'import, aucun 409.

La contrepartie est le garde-fou : le diff d'import présenté avant confirmation **nomme
explicitement** chaque nœud porteur de coût qui sera supprimé, avec son libellé, sa nature MO ou
non-MO et son montant courant. L'utilisateur qui confirme sait exactement quel chiffrage il perd ; le
chiffrage des révisions validées, lui, n'est pas concerné, puisque le réimport ne s'applique qu'à un
brouillon.

## Ce que le modèle n'est pas

### L'`uid` MS Project n'est jamais une clé du domaine

L'`uid` MS Project est un **identifiant externe**, relevant de la seule couche d'import/export,
conservé pour la stabilité du round-trip avec le fichier. Il est stocké sur le `work_item`
(`external_uid`) et n'est utilisé que par l'import et l'export pour reconnaître une tâche d'un
fichier à l'autre.

Aucune opération de domaine ne résout un nœud, une facette ou une ligne par son uid : l'arbre se
parcourt par `parent_id`, l'identité inter-version se lit sur `work_item_id`, et les prédécesseurs
sont des liens nœud → nœud. Disparaissent par conséquent :

- les clés naturelles `(project_id, uid)` de `ms_task` et `(planning_id, uid)` de
  `wf_planning_task_snapshot`, ainsi que les auto-références `parent_uid` correspondantes ;
- la dérive entre les deux espaces d'uid (le flux Lotissement allouant à partir de 1, l'import XML
  reprenant ceux de MS Project) ;
- l'artifice de l'uid négatif de `wf_estimate_grid_node`, dont le `parent_uid` mélangeait trois
  espaces d'identité — positif pour `ms_task.id`, négatif pour son propre compteur, nul pour la
  racine. Un nœud a désormais une identité unique.

### Aucune garde inter-version ne subsiste

L'immuabilité d'une révision validée est la **seule** garde de protection du travail chiffré.

Il n'existe aucune garde du type « cette tâche est référencée ailleurs, donc on ne peut pas la
supprimer ». `services/task_references.py` — `is_task_referenced` et `find_referenced_task_uids` —
est supprimé, pas réécrit, et le 409 `IMPORT_CONFLICT` qu'il alimentait disparaît avec lui. Il se
déclenchait sur un **brouillon**, c'est-à-dire précisément là où l'utilisateur doit avoir tous les
droits, et protégeait donc la mauvaise chose : depuis que tout projet doté d'un devis, fût-il vide,
possédait des références, aucun réimport ne pouvait plus retirer aucune tâche.

`wf_charge_line`, qui n'existait plus que comme source de référence pour cette garde et qu'aucun code
de production n'écrit, est supprimée.

### Un devis n'est pas une variante d'un planning

Il n'y a pas « un planning, plusieurs devis ». Sous la règle de propagation forte, deux variantes de
chiffrage déplacent des lignes de coût, donc des tâches, donc produisent deux arbres. Une variante
de devis **est** une variante complète de révision.

Ceci remplace — et ne contourne pas — le critère d'acceptation livré d'E12 (#272) : « deux brouillons
de devis coexistants du même projet peuvent porter des affectations de rôle différentes pour la même
tâche ». Le besoin reste servi : deux brouillons de **révision** coexistent, chacun avec ses propres
nœuds et ses propres facettes, et éditer l'un ne modifie jamais l'autre. C'est l'unicité du planning
sous-jacent qui est abandonnée, délibérément.

## Correspondance avec le modèle actuel

| Existant | Devient |
| --- | --- |
| `ms_task`, `wf_planning_task_snapshot` | `wf_revision_node` + facette planification |
| `ms_task_link`, `wf_planning_link_snapshot` | `wf_revision_node_link` |
| `wf_planning`, `wf_estimate` | `wf_revision` |
| `wf_estimate_task_row` | `wf_revision_node` (position et libellés calculés, plus recopiés) |
| `wf_estimate_grid_node` | `wf_revision_node` (identité unique, plus d'uid négatif) |
| `wf_estimate_cost_line` | facette coût de nature `non_labor` |
| `wf_estimate_role_assignment`, `wf_task_role_assignment` | facette coût de nature `labor` |
| `wf_estimate_line` | `wf_revision_frozen_line` |
| `wf_task_enrichment` | `work_item.description` |
| `wf_charge_line` | supprimée |
| `EstimateCostLine.source_line_id` (jamais créé) | identité `work_item` |
| `MsProject.planning_reference_id`, `displayed_planning_id`, `reference_estimate_id`, `Estimate.planning_id` | pointeur unique de révision |
| `WfPlanning.revision`, `Estimate.revision` | `ProjectRevision.lock_version` |
| `services/task_references.py` | supprimé, remplacé par l'immuabilité d'une révision validée |

La création de ces tables est strictement additive (E14-03, #329) : les anciennes restent en place
jusqu'à ce que tous leurs consommateurs soient migrés (E14-12, #339).
