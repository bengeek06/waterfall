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
| `breakdown_entry_id` | **PROVISOIRE — dépend de la [Règle 4](#règle-4--le-lotissement-vit-hors-de-la-révision-provisoire), ne rien construire dessus** : entrée de lotissement dont la tâche est issue ; c'est par elle qu'une regénération retombe sur la même identité ([Règle 4 d](#règle-4--le-lotissement-vit-hors-de-la-révision-provisoire)). En pratique la génération de squelette en est le seul rédacteur, mais ce n'est **pas** un invariant : ce qui est garanti est une **garde de création** — refusée sur un `work_item` de nature `cost`, et unique par projet, faute de quoi la seconde identité serait inatteignable dès sa création. Contrairement à l'`external_uid` ([INV-25](#inv-25)), aucune assertion d'état ne la contrôle, la Règle 4 étant provisoire |
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

> **État au terme d'E14-06 (#332).** Le 409 `IMPORT_CONFLICT` **est supprimé** : plus aucun chemin
> d'import ne consulte de garde de référence, et un réimport retire une tâche chiffrée d'un
> brouillon sans erreur (#325). Le module `services/task_references.py` subsiste en revanche, encore
> appelé par `planning_structure.py` et `planning_tree.py`, c'est-à-dire par l'ancien socle : il
> disparaît avec eux, à E14-12 (#339).

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

La resynchronisation prend le calendrier du rôle de la **première** facette MO, **dans l'ordre
depth-first du sous-arbre**, dont le rôle porte un calendrier, et positionne `calendar_source` à
`role`. S'il n'existe plus aucune facette MO dont le rôle porte un calendrier, la valeur retombe au
calendrier du projet et `calendar_source` repasse à `project`.

Le calendrier d'une tâche est resynchronisé — si et seulement si `calendar_source` vaut `project` ou
`role` — à chaque changement de ce que cette résolution *lit*, c'est-à-dire :

- à chaque changement de l'**ensemble** des affectations MO portées par son sous-arbre —
  **affectation ajoutée, modifiée, retirée ou déplacée** ;
- et à chaque changement de l'**ordre** de ce sous-arbre — **réordonnancement d'une fratrie**, même
  à ensemble d'affectations rigoureusement constant.

Le second cas n'est pas une précaution théorique : la résolution porte sur la *première* facette MO
rencontrée, donc l'ordre des frères est une **entrée** de la règle au même titre que les
affectations elles-mêmes. Permuter deux frères dont les sous-arbres portent des rôles à calendriers
différents change la bonne réponse sans qu'aucune affectation n'ait bougé. C'est exactement ce que
produit un réimport MS Project qui ne change *rien* : il replace les tâches du fichier avant les
lignes de coût et avant les tâches locales de la même fratrie (voir
[Règle 3](#règle-3--réimport-ms-project-dans-un-brouillon-tâche-disparue-du-fichier)). Un
réimport resynchronise donc les parents touchés **inconditionnellement**, et **après** avoir
réordonné les fratries ; conditionner la resynchronisation au déplacement d'une affectation laisse
un calendrier périmé qu'aucun invariant d'état ne détecte, [INV-15](#inv-15) ne contrôlant que la
présence d'un calendrier, pas sa fraîcheur.

Les cas se lisent donc ainsi :

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
4. **Une affectation est déplacée** — déplacement direct d'une ligne MO, ou déplacement d'une tâche
   qui en porte, y compris le reparentage opéré par un réimport
   ([Règle 3](#règle-3--réimport-ms-project-dans-un-brouillon-tâche-disparue-du-fichier)) : un
   déplacement change l'ensemble des affectations de **deux** sous-arbres, celui de l'ancien
   ancêtre et celui du nouveau. **Les deux extrémités sont resynchronisées**, chacune selon la même
   règle de précédence. C'est le seul cas où une opération resynchronise plus d'une tâche racine ;
   l'omettre laisse un calendrier périmé qu'aucun invariant d'état ne détecte, [INV-15](#inv-15)
   ne contrôlant que la présence d'un calendrier, pas sa fraîcheur.
5. **Une fratrie est réordonnée**, sans qu'aucune affectation ne soit ajoutée, modifiée, retirée ni
   déplacée : monter ou descendre un frère, et surtout le réordonnancement systématique qu'opère un
   réimport. L'ensemble des affectations du sous-arbre est inchangé, mais la **première** dans
   l'ordre depth-first peut ne plus être la même : les ancêtres du sous-arbre réordonné sont donc
   resynchronisés comme dans les cas précédents. C'est le cas le plus facile à oublier, parce qu'il
   se déclenche sur un réimport dont le diff est vide — l'utilisateur n'a rien modifié, il a
   réimporté son fichier.

Un utilisateur revient au comportement automatique en effaçant son choix explicite : `calendar_source`
repasse alors à `project` ou `role` par application de la même resynchronisation.

**Départage : la Règle 1 est la seule vérité sur le chemin de révision.** Acté par E14-06 (#332),
la divergence étant jusqu'ici documentée et pinnée sans être tranchée. L'ancien chemin
(`services/calendar_schedule.resolve_task_calendar_ids`) départage deux affectations concurrentes en
gardant le **plus petit `role_id`** ; la Règle 1 garde la **première facette MO dans l'ordre
depth-first**. Les deux réponses diffèrent dès que la tâche porte plusieurs rôles à calendriers
distincts. À partir de cette issue, **aucun code du chemin de révision n'appelle
`resolve_task_calendar_ids`** : l'import initialise le calendrier au calendrier du projet et le
resynchronise selon la règle ci-dessus, et l'export d'une révision lit le calendrier **sur la
facette**, jamais depuis les rôles. L'ancien départage survit uniquement sur l'ancien socle, jusqu'à
sa suppression par E14-12 (#339).

Corollaire, assumé lui aussi : le `<CalendarUID>` que MS Project porte par tâche n'est **pas**
honoré sur le chemin de révision. C'est un identifiant de calendrier MS Project, donc un identifiant
externe, sans correspondance dans `wf_calendar` — il reste enregistré tel quel sur les tables de
l'ancien socle, que l'import alimente encore. Lui donner un sens supposerait une table de
correspondance que le modèle ne porte pas.

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

Le garde-fou n'a de valeur que si l'appliqué est **exactement** le diff confirmé. Trois précisions
en découlent, à implémenter telles quelles (E14-06, #332) :

**a. Un nœud de planification sans `external_uid` n'est jamais signalé comme supprimé.** Un nœud
dont le `work_item` n'a pas d'`external_uid` a été créé dans Waterfall et jamais exporté : son
absence du fichier ne porte **aucune information**, puisqu'il n'y a jamais été. Il n'est ni
supprimé, ni remonté, ni listé dans le diff. Seuls les nœuds que le fichier a connus — ceux dont le
`work_item` porte un `external_uid` — peuvent être déclarés disparus. Corollaire pour le calcul du
diff : le déplacement d'une tâche doit se comparer sur le **nœud parent attendu**, jamais sur une
paire d'uid, un parent local n'en ayant pas ; sinon « à la racine » et « sous un parent local » sont
indiscernables et le diff sous-déclare un déplacement que l'application effectue pourtant.

Un tel nœud conserve son parent, mais **pas nécessairement son rang** : le fichier ne porte aucune
position pour lui. Les tâches locales sont donc replacées **après** les tâches importées de la même
fratrie, dans leur ordre relatif d'avant l'import, exactement comme les lignes de coût (voir
« Position des lignes de coût au réimport » ci-dessous). Descendre en fin de fratrie n'est pas une
suppression et ne fait pas l'objet d'un item de diff.

*Contrepartie assumée, explicitée par la revue d'E14-06 (#332).* « Jamais signalé comme supprimé »
n'est pas « jamais supprimé ». Un nœud local situé **dans le sous-arbre** d'une tâche que le fichier
fait disparaître est détruit avec elle, et il ne figure dans aucun item de diff : il n'a pas
d'`external_uid`, donc pas d'item `removed` (règle a), et s'il ne porte pas de facette coût il ne
produit pas non plus de `CostLoss`. L'utilisateur qui avait ajouté une sous-tâche à la main sous une
tâche importée la perd donc sans confirmation nominative. C'est **voulu** et non un trou : le nœud
local n'a jamais eu d'identité que le fichier puisse nommer, et son sort suit celui de son parent
comme n'importe quel descendant — la même collatéralité structurelle que le garde-fou couvre déjà
pour l'argent, puisque la ligne de coût portée par ce nœud local, elle, est bien annoncée. Le
garde-fou porte sur le **chiffrage**, pas sur la structure ; ce qui coûte est toujours nommé.

**b. Un récapitulatif qui disparaît alors que le fichier conserve ses enfants ailleurs.** Les
enfants que le fichier liste encore, sous un autre parent, sont **reparentés** ; seul le reste du
sous-arbre est détruit, et le garde-fou n'annonce que le chiffrage réellement perdu. L'ordre
d'application est donc : créer les tâches ajoutées, reparenter toutes celles que le fichier porte
encore, **puis** supprimer les disparues. L'ordre naïf — supprimer d'abord le sous-arbre disparu —
recréait les enfants survivants avec de **nouveaux `work_item`**, perdant l'identité inter-version
sur laquelle repose tout le modèle.

**c. Un fichier qui nomme un parent qu'il ne liste pas lui-même est refusé.** Si un
`parent_external_uid` désigne un nœud que la révision possède mais que le fichier ne liste pas, ce
parent est précisément l'un de ceux que le réimport supprime : appliquer le fichier reparenterait un
survivant dans un sous-arbre condamné, puis le détruirait avec lui — une perte de chiffrage que le
diff confirmé n'annonçait pas. Le réimport est **refusé en bloc**, avant toute mutation, et non
réparé en aval. Sont refusées de la même façon, et au même moment, une chaîne de parenté qui boucle
(elle produirait un cycle, [INV-06](#inv-06)), un enfant listé **avant** son parent — MS Project
écrit un fichier depth-first, l'ordre inverse signale une source malformée et n'est pas réordonné
silencieusement —, un parent que ni le fichier ni la révision ne connaissent, et — ajout d'E14-06,
issue #345 — un fichier qui **liste deux fois le même `external_uid`**. Un export MSPDI valide ne
produit aucune de ces cinq formes.

Le doublon d'`external_uid` est refusé pour la raison même qui fonde le garde-fou : le réimport
indexe le fichier par uid, donc sans refus la dernière occurrence l'emporterait silencieusement et
la tâche précédente disparaîtrait de l'arbre importé sans aucun item de diff — exactement la
suppression silencieuse que la Règle 3 proscrit. C'est une erreur de structure et non une entité
absente : tout ce que le fichier nomme existe, il le nomme deux fois.

Les quatre premières sont des **erreurs de structure du fichier** : tout ce qu'elles nomment est
connu, c'est l'agencement qui est inapplicable. Seule la dernière — un parent inconnu du fichier
comme de la révision — est une **entité absente**. La distinction est normative, car elle détermine
la réponse de la couche transport (E14-05, E14-06) : une structure inapplicable et une entité
absente ne se répondent jamais pareil.

> **Amendement E14-05 (#331), repris tel quel par E14-06 (#332).** La rédaction initiale fixait 422
> pour une structure inapplicable. La couche transport livrée répond **400**
> (`REVISION_IMPORT_STRUCTURE_INVALID`) et non 422, et **404** (`REVISION_NODE_NOT_FOUND`) pour
> l'entité absente. Motif : 422 est réservé, dans tout ce dépôt, au seul cas « le corps de la requête
> n'a pas parsé », que FastAPI produit lui-même ; peindre en 422 un refus métier obligerait un client
> à distinguer deux 422 de nature opposée. Ce qui était normatif — les deux familles ne se répondent
> pas de la même façon — est tenu ; le code retenu pour la première a changé. Voir
> `apps/backend/src/waterfall/api/revision_errors.py`, qui est la table de traduction unique.

Le réimport valide donc **l'intégralité** de la structure du fichier avant d'écrire quoi que ce
soit : une révision est soit entièrement réimportée, soit rigoureusement intacte, `lock_version`
compris. Il n'existe pas d'état intermédiaire dans lequel un import refusé aurait déjà créé des
nœuds.

**d. Un fichier dont les liens de précédence forment un cycle est refusé en bloc.** Tranché par
E14-06 (#332), la question étant restée ouverte par les revues précédentes : [INV-18](#inv-18)
(acyclicité de la précédence) est un invariant *nouveau*, qu'aucune des deux tables jumelles ne
vérifiait. Le choix est le **refus global**, jamais le rejet du seul lien fautif avec signalement
dans le diff, pour trois raisons :

1. c'est la seule réponse cohérente avec le garde-fou : l'appliqué doit être **exactement** le diff
   confirmé, et écarter un lien que le diff n'énumère pas — le diff porte sur des nœuds, pas sur des
   liens pris un à un — produirait un planning dont l'ordonnancement diffère du fichier que
   l'utilisateur croit avoir importé ;
2. un fichier MSPDI valide n'en contient pas : MS Project refuse lui-même de créer un cycle de
   précédence. Un cycle relève donc de la source malformée, au même titre que les quatre formes
   ci-dessus, et se traite comme elles ;
3. le dépôt le fait déjà : le parseur MSPDI signale `DEPENDENCY_CYCLE` et fait échouer l'import
   entier avant toute écriture. La décision consiste donc à **conserver** ce comportement et à
   l'étendre au graphe *résultant* — les liens du fichier fusionnés avec ceux que le fichier ne
   connaît pas — vérifié en une seule passe avant la moindre mutation.

Corollaire sur le périmètre du remplacement : le fichier fait autorité sur les prédécesseurs des
**tâches qu'il liste** et ne dit rien des autres. Un lien entre deux nœuds créés dans Waterfall
survit donc au réimport, exactement comme le nœud sans `external_uid` de la Règle 3 a ; un lien
arrivant sur une tâche du fichier est remplacé par ce que le fichier dit, ce qui est ce qui fait
qu'une dépendance retirée du fichier disparaît réellement.

**Position des lignes de coût au réimport.** Le fichier ne dit rien de la place d'une ligne de coût
dans une fratrie — elle n'y a pas d'image. Les enfants de coût d'un parent sont donc conservés
**après** ses enfants de planification, dans leur ordre relatif d'avant l'import, ce qui préserve la
contiguïté exigée par [INV-05](#inv-05) sans inventer d'ordre que le fichier ne porte pas.

**Identité de projet, pas de révision.** Le réimport s'accroche à l'identité du **projet** :
l'`external_uid` est unique par projet ([INV-25](#inv-25)) et le `work_item` est le seul lien entre
deux révisions. Réimporter le même fichier dans une seconde révision du même projet doit donc
retrouver les **mêmes** `work_item` et n'en créer que pour les uid que le projet ne connaît pas
encore. Créer de nouveaux `work_item` casserait le rapprochement RAE ↔ budget de référence, qui ne
joint que par `work_item_id`.

### Règle 4 — Le lotissement vit hors de la révision (provisoire)

> **Statut : provisoire. Ne rien construire sur cette règle.** Contrairement aux règles 1 à 3, celle-ci
> n'est pas tranchée. Elle est issue d'un **lot de maquettage encore en cours**, qui produira sa propre
> spécification puis ses propres EPIC et issues, et qui peut la faire évoluer d'ici sa passe de
> cohérence. Elle est reprise ici **pour être éprouvée par le banc d'essai d'E14-02**, tant que rien
> n'est écrit en base et que la remettre en cause ne coûte qu'une réécriture de test.
>
> Concrètement : le banc d'essai la transcrit et la vérifie, mais **aucune table, aucune migration et
> aucune API de l'EPIC E14 ne doit être conçue en s'appuyant dessus**. Le périmètre définitif du
> lotissement — son modèle, ses écrans, ses routes — relèvera du lot de maquettage, pas de la présente
> spécification.

Le **lotissement** — postes, lots, livrables — est une donnée de **projet**. Il n'est pas versionné,
il n'a pas d'historique, et une révision validée ne le fige pas ([INV-26](#inv-26-provisoire)).

*Motif* : si le lotissement était porté par la révision, une révision validée en interdirait la
modification. Or il doit rester éditable à tout moment, ne serait-ce que pour corriger une coquille.
Les deux propriétés sont incompatibles, et c'est l'immuabilité qui est la bonne : c'est le même
raisonnement que celui appliqué à `wf_task_enrichment`, qui se résorbe dans `work_item` parce qu'il
survit aux versions.

Quatre conséquences, à implémenter telles quelles :

**a. Modifier le lotissement ne propage rien au planning.** Aucun nœud n'est créé, modifié ni
supprimé par l'enregistrement d'un lotissement, quelle que soit la révision et quel que soit son
statut. Il n'existe aucune règle de propagation lotissement → arbre.

**b. Le squelette n'est qu'une aide au démarrage.** Un planning se démarre de **trois** façons —
génération d'un squelette depuis le lotissement, feuille blanche, import MS Project — toutes
équivalentes et toutes facultatives. Le squelette généré est un arbre de tâches ordinaires : ses
`work_item` ne portent pas d'`external_uid`, n'ayant jamais figuré dans un fichier, de sorte qu'un
import ultérieur ne les lit pas comme disparus ([Règle 3 a](#règle-3--réimport-ms-project-dans-un-brouillon-tâche-disparue-du-fichier)).

**c. La regénération n'est proposée que sur un squelette non retouché.** Le marqueur est une
**empreinte portée par la révision**, calculée au moment de la génération sur le lotissement **et**
sur l'arbre généré. « Non retouché » signifie : l'arbre courant a la même empreinte d'arbre que
celle enregistrée.

L'empreinte d'arbre porte sur **tout ce que l'utilisateur peut avoir mis dans l'arbre**, et jamais
sur des identifiants — une copie de révision ([INV-07](#inv-07)) reproduit le même arbre sous de
nouveaux identifiants et reste un squelette non retouché. Elle couvre :

- la **forme** de l'arbre (chemins de positions) et les **libellés**, lignes de coût comprises ;
- les **valeurs de planification** saisies sur une tâche : jalon, durée et format de durée, dates de
  début et de fin, charge, avancement, planification manuelle ;
- le **calendrier épinglé à la main** (`calendar_source = manual` et son `calendar_id`), et lui
  seul : les sources `project` et `role` sont *dérivées* de la [Règle 1](#règle-1--origine-du-calendrier-dune-tâche),
  les surveiller ferait passer pour retouché un squelette que personne n'a touché ;
- les **liens d'antériorité**, retraduits en chemins de positions de leurs deux extrémités — ils
  vivent hors de l'arbre, et les oublier rendrait regénérable un planning déjà ordonnancé.

D'une ligne de coût, seul le libellé est retenu : un squelette généré est un arbre de **tâches**,
donc la seule présence d'un nœud de coût distingue déjà l'empreinte de celle enregistrée.

Ce n'est **ni** un horodatage comparé aux `updated_at`, **ni** un marqueur porté par les nœuds : les
deux variantes ont été examinées et écartées.

Les **deux moitiés de l'empreinte sont des condensés non réversibles** (SHA-256 d'une forme
canonique) : une empreinte se compare, elle ne se relit pas, et une révision ne doit conserver ni le
contenu du lotissement ni les libellés qui en sont issus ([INV-26](#inv-26-provisoire)).

**Portée d'une empreinte, et ce qu'une non-correspondance signifie.** La forme canonique condensée
est un rendu de structures Python : une empreinte n'a de sens **qu'à l'intérieur d'une version de
code**, et rien ne garantit qu'une montée de version du langage ou une évolution du modèle produise
le même condensé pour le même arbre. Ce qui rend ce risque acceptable est le **sens du refus** :
une empreinte qui ne correspond plus fait conclure « squelette retouché », donc **refuse** la
regénération — elle n'autorise jamais un écrasement à tort. La dégradation retire un bouton, elle ne
détruit pas de travail. En conséquence, le jour où l'empreinte sera **persistée**, elle devra être
étiquetée d'une **version de format** : une empreinte d'une version antérieure se lit comme absente
(regénération non proposée), jamais comme une comparaison valide.

La moitié « lotissement » n'est jamais comparée pour autoriser ou refuser une regénération — un
lotissement modifié depuis la génération est la raison normale de regénérer, pas un motif de refus. Elle
enregistre ce dont le squelette est issu, et sert uniquement à *signaler* que le lotissement a changé
depuis la génération.

**d. Une regénération vise nécessairement un brouillon.** Elle écrit, donc
[INV-03](#inv-03) s'applique sans aménagement : sur une révision validée elle est refusée comme
n'importe quelle autre écriture, et l'utilisateur passe par une copie brouillon. Il n'y a pas de
contradiction avec la présente règle — la modification du lotissement est acceptée *parce qu'elle ne
touche pas la révision*, et la regénération est refusée *parce qu'elle la touche*.

**Les tâches reconstruites conservent le `work_item` de l'entrée de lotissement dont elles sont
issues.** La génération s'accroche à l'identité de **projet** par entrée de lotissement, exactement
comme le réimport s'y accroche par `external_uid` ([Règle 3 c](#règle-3--réimport-ms-project-dans-un-brouillon-tâche-disparue-du-fichier)) :
générer le squelette du même lot deux fois — dans une seconde révision, ou de nouveau après une
regénération — retombe sur le même `work_item`. En réallouer de nouveaux serait faux, car l'empreinte
compare un **état**, pas un **historique** : annuler une retouche (supprimer l'unique ligne de coût
qui avait été accrochée sous une tâche du squelette) rend la regénération de nouveau disponible sur
un arbre dont une révision validée a déjà figé les identités. Ses `frozen_lines`, et le rapprochement
qui ne joint que par `work_item_id`, n'auraient alors plus rien à joindre.

**Transition de statut du projet.** L'enregistrement du lotissement fait passer le projet de `cree` à
`initialise`, et c'est le **seul** déclencheur de cette transition.

**Ce que cette règle rend inutile.** `ms_task.structure_key` et `ms_task.structure_kind` n'ont pas à
être relogés dans le nouveau modèle. Leur seule raison d'être est le mécanisme de propriété de la
génération — savoir quel nœud provient de quel élément de lotissement, pour décider ce qu'une
regénération a le droit d'écraser. L'empreinte répond à la même question sans marquer les nœuds, et
la réponse qu'elle donne est « tout ou rien », qui est la seule que la règle c autorise.

### Règle 5 — La désindentation préserve l'ordre des lignes affichées

**Désindenter une sélection ne change que son niveau : la suite des lignes affichées est exactement
celle que l'utilisateur avait sous les yeux avant la commande.** C'est la sémantique MS Project.

```
avant : P > [X, Y, Z]        lignes affichées : P, X, Y, Z
outdent(Y)
après : P > [X] , Y > [Z]    lignes affichées : P, X, Y, Z
```

*Motif* : les utilisateurs de ce produit viennent de MS Project. Une désindentation qui réordonne
des lignes qu'ils n'ont pas sélectionnées — ici `P, X, Z, Y` — y serait perçue comme un bug, et non
comme une variante défendable.

**Le rattachement des frères suivants est une conséquence, pas une règle.** La sélection désindentée
se place immédiatement après son ancien parent ; les frères qui la suivaient ne peuvent alors
conserver leur rang qu'en devenant les enfants du **dernier** nœud désindenté. C'est la propriété
d'ordre qui est énoncée et qui se vérifie ; le rattachement s'en déduit.

**Sélection multiple.** La commande porte sur un **bloc contigu** de frères — une sélection à trou
est refusée, comme pour l'indentation et les décalages haut/bas, parce qu'elle ferait franchir à un
nœud non sélectionné les lignes qui l'entourent. Le bloc conserve son ordre relatif, et c'est son
dernier nœud qui reçoit les frères suivants ; les nœuds précédents du bloc n'en reçoivent aucun.
Les trois fratries réécrites — celle de l'ancien parent, celle du grand-parent, et celle des enfants
du dernier nœud désindenté où les frères suivants sont appendus — sont renumérotées contiguës
([INV-05](#inv-05)).

**Conséquence sur le chiffrage.** Il n'y a qu'un seul arbre et deux facettes : les frères suivants
qui deviennent enfants emportent **toute leur facette coût**, puisque c'est le même nœud qui se
déplace. Une désindentation déplace donc des lignes de coût que l'utilisateur n'a pas sélectionnées.
Leur montant, leur rôle, leurs heures et leur imputation sont inchangés ; seule leur **tâche
porteuse** change, et elle n'est jamais mémorisée ([INV-01](#inv-01), et le cas limite
[« Une réindentation qui change la tâche porteuse d'une ligne de coût »](#une-réindentation-qui-change-la-tâche-porteuse-dune-ligne-de-coût)).
C'est voulu, et c'est ce que l'interface devra rendre lisible avant de proposer l'opération.

**Ce que la règle fait porter aux gardes de placement.** Le nœud désindenté devient un **parent** :
la commande est donc refusée, avant toute mutation, lorsque le rattachement des frères suivants
violerait une règle de placement — un jalon qui ne porte aucun enfant ([INV-27](#inv-27)), une ligne
de coût qui ne peut pas contenir une tâche ([INV-14](#inv-14)). Ces refus ne sont pas des cas
particuliers de la désindentation : elle réutilise le déplacement, donc ses gardes.

**Portée : opération.** C'est une post-condition, qui se vérifie en comparant l'état avant et après,
et non une assertion sur un état isolé. Être une post-condition ne suffirait pas à l'exclure des
invariants — INV-02, INV-03 et INV-07 en sont, et la fonction de contrôle ne les évalue
délibérément pas. Ce qui la place ici est qu'elle est, comme les règles 1 à 3, un arbitrage produit
assorti de son motif.

**L'indentation est le symétrique, et elle est déjà conforme.** Indenter un bloc contigu le place
sous le frère qui le **précède**, en dernière position parmi les enfants de celui-ci : là encore
l'ordre des lignes est préservé et seul le niveau du bloc change. Le premier enfant d'un parent n'a
aucun frère précédent et ne peut donc pas être indenté. Contrairement à la désindentation,
l'indentation ne touche pas aux frères suivants : ils restent au même niveau, derrière le bloc.

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
*Portée : état, vérifiable sur les **lignes figées**. Violation : mémoriser sur une ligne de coût une
tâche porteuse qui n'est pas son premier ancêtre de planification, par exemple en la laissant
inchangée après un déplacement.*

Précision de portée. Sur un **brouillon**, INV-01 n'est pas une assertion réfutable mais la
*définition* de la fonction de résolution : la tâche porteuse n'y est mémorisée nulle part, donc
rien ne peut diverger de la remontée d'ancêtres, et la fonction de contrôle d'invariants n'a rien à
comparer. L'invariant ne devient vérifiable qu'à partir du moment où une tâche porteuse est
**recopiée** quelque part, c'est-à-dire sur le `bearing_work_item_id` d'une ligne figée : c'est là,
et là seulement, que le contrôle s'exerce.

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

INV-16 **implique strictement** [INV-18](#inv-18) : un auto-lien est un cycle de précédence à un
seul nœud, donc toute violation de INV-16 est aussi une violation de INV-18. La redondance est
assumée — l'auto-lien est le cas dégénéré le plus courant et mérite d'être nommé pour lui-même, avec
son propre message d'erreur. Un test qui viole INV-16 doit donc s'attendre à voir les **deux**
identifiants remontés, et asserter l'appartenance plutôt que l'égalité à un ensemble.

##### INV-17

**Les deux extrémités d'un lien de précédence portent une facette de planification.** La précédence
est une notion de la facette planification : une ligne de coût n'a ni prédécesseur ni successeur.
*Portée : état. Violation : créer un lien de précédence depuis ou vers un nœud de coût.*

##### INV-18

**Le graphe de précédence est acyclique.** En suivant les liens de précédence, on ne revient jamais
sur un nœud déjà visité.
*Portée : état. Violation : créer les liens A → B et B → A.*

À l'import, cet invariant se traduit par un **refus global** du fichier, avant toute mutation, et non
par le rejet du seul lien fautif : voir [Règle 3 d](#règle-3--réimport-ms-project-dans-un-brouillon-tâche-disparue-du-fichier),
qui porte l'arbitrage et son motif.

##### INV-27

**Un jalon ne porte aucun enfant.** Aucun nœud n'a pour parent un nœud dont la facette de
planification porte `is_milestone` à vrai. Un jalon est un point daté, pas un conteneur : la règle ne
regarde pas la facette de l'enfant, et interdit donc aussi bien une sous-tâche qu'une ligne de coût.
*Portée : état. Violation : indenter une tâche sous un jalon, rattacher une ligne de coût à une tâche
jalon, ou marquer comme jalon une tâche qui porte déjà des enfants.*

La **désindentation** est le cas où la règle mord le plus discrètement : elle fait du nœud
désindenté le parent des frères qui le suivaient
([Règle 5](#règle-5--la-désindentation-préserve-lordre-des-lignes-affichées)), donc désindenter un
jalon suivi d'au moins un frère est refusé, alors même que l'utilisateur n'a désigné aucun parent.
La garde ne tient que parce que ce rattachement passe par le déplacement et ses gardes ; un
`parent_id` écrit en place y échapperait.

L'invariant se lit dans les deux sens, et chacun des deux sens est refusé **avant toute mutation**,
avec l'état laissé rigoureusement inchangé : on ne rattache rien sous un jalon — création,
déplacement, indentation, réimport — et on ne marque pas comme jalon une tâche qui porte déjà des
enfants. Au réimport, il vaut comme [INV-18](#inv-18) **refus global** du fichier : y compris lorsque
le fichier marque comme jalon une tâche sous laquelle survit un nœud qu'il ne nomme pas — une ligne
de coût, ou une tâche créée dans Waterfall et jamais exportée — auquel cas rien dans le fichier ne
trahit la violation qu'il s'apprête à créer.

#### Facette coût

##### INV-19

**Une facette de coût de nature `labor` porte un rôle et un nombre d'heures, et ne porte ni catégorie
de coût propre, ni débours, ni suivi de commande.** `role_id` et `hours` sont renseignés ;
`cost_type_id`, `cost_category_id`, `unit_cost` et `supply_status` sont nuls — la catégorie d'une
ligne MO est celle de son rôle, et `supply_status` est réservé aux fournitures (voir le tableau des
attributs de la facette coût) : une ligne MO n'a pas de commande à suivre.
*Portée : état. Violation : saisir un débours sur une ligne MO, marquer une ligne MO `ordered`, ou
créer une ligne MO sans rôle.*

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

#### Lotissement

##### INV-26 (provisoire)

> **Statut : provisoire. Cet invariant n'a pas le même statut qu'INV-01..INV-25 ni
> qu'[INV-27](#inv-27).** Les vingt-six autres sont **acquis** ; celui-ci découle de la
> [Règle 4](#règle-4--le-lotissement-vit-hors-de-la-révision-provisoire), issue d'un lot de maquettage
> encore en cours et susceptible d'évoluer. Le banc d'essai d'E14-02 le vérifie exactement comme les
> autres — c'est précisément pour l'**éprouver** qu'il est énoncé ici — mais **aucune table, aucune
> migration et aucune API de l'EPIC E14 ne doit être conçue en s'appuyant dessus** tant que le lot de
> maquettage n'a pas publié sa propre spécification. Un test rouge sur INV-26 est donc à lire comme un
> signal sur la règle, pas nécessairement comme un défaut du code.

**Le lotissement est une donnée de projet, non versionnée, qu'une révision validée ne fige pas.**
Aucune révision ne porte d'entrée de lotissement : les postes, lots et livrables sont portés par le
projet et par lui seul, et restent modifiables quel que soit le statut de n'importe quelle révision
du projet. Une révision ne conserve du lotissement que l'**empreinte** du squelette qui en a été
généré ([Règle 4 c](#règle-4--le-lotissement-vit-hors-de-la-révision-provisoire)), jamais son
contenu.

« Jamais son contenu » vaut **quelle qu'en soit la forme** : ni les entrées elles-mêmes, ni un
dictionnaire `id`/`kind`/`name`, ni une ligne champ par champ, ni une chaîne sérialisée.

**Ce que la vérification garantit, et ce qu'elle ne garantit pas.** Les trois premières formes sont
**structurelles** : elles se décident sur la forme de l'objet porté par la révision, et sont
détectées de façon déterministe. La quatrième — la chaîne sérialisée — est détectée **au mieux** : le
discriminant employé est le fait qu'une sérialisation *met le nom entre guillemets*, là où la copie
parfaitement légitime d'un libellé de lot sur une tâche générée ne le fait pas. Les rendus qui ne
citent pas leurs noms (CSV, séparé par barres verticales, bloc YAML, ligne de tableau markdown,
phrase humaine, libellés seuls) passent donc inaperçus. **Un contrôle vert sur INV-26 ne vaut pas
« aucun contenu de lotissement n'est porté »** : il vaut « aucune entrée, aucun dictionnaire, aucune
ligne champ par champ, et aucune sérialisation manifeste ». Élargir l'heuristique ne ferait que
déplacer la frontière des ratés ; c'est pourquoi elle est énoncée plutôt qu'affinée.

C'est aussi pourquoi les deux moitiés de l'empreinte sont des condensés non réversibles : un rendu
lisible du lotissement — ou des libellés qui en sont issus — porté par la révision est une
violation, même s'il s'appelle « empreinte ». En revanche, un `work_item` du **projet** peut référencer l'entrée de
lotissement dont il est issu ([Règle 4 d](#règle-4--le-lotissement-vit-hors-de-la-révision-provisoire)) :
c'est une référence, pas une copie — aucun libellé, aucune nature, rien qu'une révision validée
figerait.

*Portée : état. Violation : recopier le lotissement sur la révision au moment de la génération du
squelette — une révision validée le figerait alors, et une coquille dans un libellé de lot
deviendrait incorrigible.*

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

La **désindentation** va plus loin : elle déplace aussi des lignes de coût que l'utilisateur n'a
**pas** sélectionnées, à savoir celles qui suivaient la sélection dans la même fratrie et qui en
deviennent les enfants pour que l'ordre des lignes affichées soit préservé
([Règle 5](#règle-5--la-désindentation-préserve-lordre-des-lignes-affichées)). Là encore rien du
chiffrage n'est modifié — seule la tâche porteuse change, et elle se résout à la lecture.

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
| `ms_task.structure_key`, `ms_task.structure_kind` | **PROVISOIRE — voir l'encadré sous la table** : supprimées, remplacées par l'empreinte de squelette ([Règle 4 c](#règle-4--le-lotissement-vit-hors-de-la-révision-provisoire)) |
| `wf_charge_line` | supprimée |
| `EstimateCostLine.source_line_id` (jamais créé) | identité `work_item` |
| `MsProject.planning_reference_id`, `displayed_planning_id`, `reference_estimate_id`, `Estimate.planning_id` | pointeur unique de révision |
| `WfPlanning.revision`, `Estimate.revision` | `ProjectRevision.lock_version` |
| `services/task_references.py` | supprimé, remplacé par l'immuabilité d'une révision validée |

> **Provisoire : la ligne `ms_task.structure_key` / `ms_task.structure_kind`.** Toutes les autres
> lignes de cette table sont acquises. Celle-là seule découle de la
> [Règle 4](#règle-4--le-lotissement-vit-hors-de-la-révision-provisoire), issue d'un lot de maquettage
> encore en cours et susceptible d'évoluer. Le banc d'essai d'E14-02 l'éprouve ; **aucune table, aucune
> migration et aucune API de l'EPIC E14 ne doit supprimer ni reloger ces deux colonnes sur cette seule
> base.** Leur sort définitif relèvera de la spécification que produira le lot de maquettage.

La création de ces tables est strictement additive (E14-03, #329) : les anciennes restent en place
jusqu'à ce que tous leurs consommateurs soient migrés (E14-12, #339).
