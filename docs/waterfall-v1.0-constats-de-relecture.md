# Waterfall v1.0 — Constats de relecture

État au 2026-09-16, branche `docs/spec-v1-arbitrages`.

Ce document recense ce qui, dans `waterfall-v1.0-specification.md`, empêche
aujourd'hui quelqu'un d'implémenter le produit sans reposer une question. Il naît
d'une passe de cohérence globale sur les 5 800 lignes du document, d'une revue
ciblée du premier arbitrage rendu, et de deux constats trouvés en cours de
traitement.

Il n'est pas une liste de tâches. Les constats ne sont pas indépendants : la
moitié des questions ouvertes en cachent une autre, plus profonde, dont elles ne
sont que la manifestation locale. Traiter un constat sans voir sa racine produit
un arbitrage qu'il faut défaire au constat suivant — c'est arrivé deux fois
pendant la rédaction de ce document, et c'est la raison de son organisation par
dépendance plutôt que par gravité.

## Comment lire ce document

- Le **§2** dit ce qui est déjà traité, avec le commit qui le porte.
- Le **§3** regroupe les constats bloquants par **racine commune**. Chaque groupe
  nomme la décision qui le commande ; les constats d'un même groupe se tranchent
  ensemble ou pas du tout.
- Le **§4** liste les résiduels et cosmétiques, qui sont indépendants les uns des
  autres et se traitent dans n'importe quel ordre.
- Le **§5** rappelle ce qui n'est **pas** un constat : les trois questions
  ouvertes assumées, qu'il ne faut pas confondre avec un trou.
- Le **§6** est la table récapitulative, une ligne par constat.

Chaque constat porte un numéro stable. Les numéros 1 à 27 viennent de la passe
globale, 28 et 29 ont été trouvés pendant le traitement.

---

## 2. Ce qui est traité

| Constat | Commit | Ce qui a été décidé |
|---|---|---|
| 11 — l'année d'une ligne de coût sans tâche porteuse | `67d8602`, repris par `11edf0a` | Un débours à la racine prend l'année de début du projet ; une ligne de main-d'œuvre à la racine s'étale sur toutes les années du projet, au prorata. Les « années du projet » sont définies (`EXG-DEV-021`), déduites des seules dates de planification, calculées révision par révision. |
| 2 — le second domaine en lecture seule | `c214ea5` | **Management** est en lecture seule comme **Analyse**. Le catalogue compte quatorze permissions, chiffre passé dans la vérification d'`EXG-DRO-015`. |

La revue ciblée de `67d8602` avait trouvé treize défauts dans ce seul commit.
Onze sont corrigés par `11edf0a`. Les deux autres ont été versés aux constats
existants : l'un au constat 28 (nouveau), l'autre au constat 4.

**Leçon de ces deux passes.** Un arbitrage ne casse presque jamais l'exigence
qu'il réécrit — il casse une vérification, un motif ou une prose situés trois
chapitres plus loin, qui s'appuyaient sur l'ancienne règle sans la citer. Le
commit `11edf0a` a dû toucher le chapitre 14 (`EXG-AVA-015`), le chapitre 16
(`EXG-CHA-005`) et l'annexe C pour un arbitrage rendu au chapitre 11. Toute
correction suivante doit être relue de la même façon.

---

## 3. Les constats bloquants, par racine

Treize constats bloquants restent ouverts, pour douze décisions — le 29 se
tranche avec le 4. Ils se répartissent en cinq groupes.

### Groupe A — Le temps : quelle année, quelle date, quel calendrier

C'est le groupe le plus profond, et celui qui commande le plus de chiffres. Trois
grandeurs temporelles sont employées par plusieurs chapitres et définies par
aucun. Tant qu'elles ne le sont pas, aucun montant n'est calculable de façon
reproductible.

#### Constat 28 — « L'année de référence » désigne deux grandeurs différentes

*Bloquant. Trouvé le 2026-09-16, absent du rapport de relecture initial.*

**Où** : `EXG-DEV-005`, `EXG-CYC-016`, §12.5, `EXG-RAE-008`.

**Quoi** : `EXG-DEV-005` pose que « l'année de référence d'un chiffrage est son
année de création », au singulier. Le §12.5 écrit que « la première revue de
janvier en porte naturellement une nouvelle, dont les taux sont cette fois
connus » — c'est le mécanisme même de la réconciliation annuelle d'`EXG-RAE-008`,
qui re-chiffre au taux réel devenu connu. Et `EXG-CYC-016` fait calculer un reste
à engager « pour l'année de référence **du chiffrage** », ce qui désigne la
première.

**Pourquoi c'est un problème** : il y a en réalité deux grandeurs. Celle de la
**révision de référence**, figée avec le budget de référence, qui ne bouge plus
une fois le projet en pilotage. Et celle de **chaque revue**, qui roule d'année
en année et permet de ré-estimer aux taux du moment. Le document les nomme
pareil, n'en définit qu'une, et laisse chaque chapitre choisir. Deux
implémenteurs chiffreront le même reste à engager à deux taux différents, et les
indices d'écart qui en découlent seront incomparables d'un mois sur l'autre.

**Piste** : nommer les deux — année de référence du budget, année de référence de
la revue —, dire laquelle `EXG-CYC-016` contrôle, et vérifier chaque emploi du
terme dans les chapitres 11, 12 et 19.

**Ce qu'il commande** : toute la valorisation d'un reste à engager, donc le
chapitre 12 entier, et la question de savoir si une année de consommation peut
être antérieure à l'année de référence — question qui n'a pas de sens tant que
celle-ci n'est pas désignée.

#### Constat 4 — Le calendrier applicable n'est produit par personne

*Bloquant.*

**Où** : `EXG-MOD-018`, §21.6, `EXG-MSP-009`, à confronter à `EXG-PAR-003`,
`EXG-PAR-008`, `EXG-PAR-001`, `EXG-MOD-017`.

**Quoi** : trois passages s'appuient sur un « calendrier du projet » qu'aucune
exigence ne fait exister. `EXG-PAR-003` fait du calendrier un attribut du
**rôle**, `EXG-PAR-008` décrit un calendrier **de l'installation** par défaut,
`EXG-MOD-017` en fait un attribut **par tâche**, et `EXG-PAR-001` interdit de
redéfinir un référentiel au niveau d'un projet. `EXG-MOD-018` invoque en outre
une « règle d'initialisation » et une « resynchronisation » que rien ne définit.

**Pourquoi c'est un problème** : c'est la donnée qui convertit une durée en
dates — le cœur du chapitre 10 — et personne ne la produit. `EXG-PLN-001` dit
seulement que « ceux du référentiel s'y substituent », ce qui ne désigne ni le
défaut d'installation, ni le calendrier du rôle, ni un attribut de projet. Deux
implémenteurs produiront deux planifications différentes sur le même fichier.

**Piste** : écrire l'exigence manquante — d'où un nœud tire son calendrier à la
création et à l'import, et ce qu'est le « calendrier du projet » — puis aligner
`EXG-MSP-009`, qui exporte « le » calendrier au singulier.

#### Constat 29 — La date de début du projet manque sa graine

*Bloquant. Conséquence du constat 11, laissée ouverte par `67d8602`.*

**Où** : `EXG-PLN-004`, `EXG-DEV-021`.

**Quoi** : `EXG-PLN-004` place une tâche automatique sans ancrage ni prédécesseur
« à la date de début du projet ». `EXG-DEV-021`, ajoutée pour le chiffrage,
définit l'**année** de début du projet comme la plus antérieure des dates de
planification de la révision.

**Pourquoi c'est un problème** : les deux usages ne demandent pas la même chose.
Le devis lit une année **déduite** d'un arbre déjà daté ; le planning a besoin
d'une date **amont**, une graine, avant qu'aucune date n'existe — c'est ce que
MS Project stocke comme date de début de projet, et dont `EXG-PLN-004` reprend le
comportement. Les confondre rend le calcul circulaire : la date qui sert à caler
une tâche non ancrée serait déduite des dates des tâches, celle-là comprise. Un
projet dont aucune tâche n'est ancrée n'aurait alors aucune date du tout.

**Piste** : décider si le projet porte en plus une date de début **saisie**, où
elle se saisit, et ce qui se passe si elle est vide. `EXG-DEV-021` a été
délibérément bornée au chiffrage pour ne pas préempter cette décision.

**À traiter avec le constat 4**, dont il partage la nature : une grandeur de
planification employée par deux chapitres et établie par aucun.

---

### Groupe B — L'écriture : qu'est-ce qu'un import détruit

#### Constat 1 — L'import est-il créateur ou destructeur ?

*Bloquant. Le plus grave du document.*

**Où** : `EXG-MSP-002` (§17.1), `EXG-MOD-020` (§21.7), `EXG-MSP-014` (§17.3).

**Quoi** : `EXG-MSP-002` énonce qu'« un import produit une **nouvelle révision**.
Il ne modifie aucune révision existante ». `EXG-MOD-020` énonce que « réimporter
un fichier **dans un brouillon** fait disparaître, pour une tâche absente du
fichier, son nœud et tout son sous-arbre — donc ses lignes de coût ».
`EXG-MSP-014` exige que « le brouillon reste rigoureusement inchangé tant que la
confirmation n'est pas donnée », son motif parlant du « seul geste du produit qui
détruit du travail de chiffrage ».

**Pourquoi c'est un problème** : les deux lectures produisent deux
implémentations incompatibles, et chacune passe sa propre vérification. Sous
`EXG-MSP-002`, un import ne détruit rien et `EXG-MSP-014` n'a plus d'objet. Sous
`EXG-MOD-020`, l'import écrase un brouillon existant et `EXG-MSP-002` est faux.
Un implémenteur qui lit le chapitre 17 écrit un import créateur ; celui qui lit
le chapitre 21 écrit un import destructeur.

**Piste** : trancher lequel est la cible. Si c'est l'import qui écrit dans le
brouillon courant, `EXG-MSP-002` doit dire ce qu'il protège vraiment — les
révisions **validées** — et sa vérification actuelle (« les versions antérieures
sont inchangées ») doit le refléter.

---

### Groupe C — Les habilitations : combien de portées

#### Constat 3 — Trois portées ou quatre ?

*Bloquant.*

**Où** : titre §18.1 et `EXG-DRO-001` (« trois portées »), `EXG-DRO-012` (« C'est
une **quatrième voie d'accès** »), `EXG-DRO-009` (« Avec **quatre portées**
additives »), §18.8, §4 Détail du plan (« trois portées de rôle additives »).

**Quoi** : l'exigence qui **énumère** les portées en compte trois ; trois autres
passages en comptent quatre.

**Pourquoi c'est un problème** : `EXG-DRO-001` est l'exigence normative et
fermée. Un implémenteur qui la prend au mot ne construit pas la déclaration de
besoin comme une portée, et `EXG-DRO-009` — « savoir par quelle voie » — devient
invérifiable pour le quatrième cas.

**Piste** : décider si la déclaration de besoin (`EXG-DRO-012`) est une quatrième
portée ou une voie d'attribution d'une portée existante, puis aligner
`EXG-DRO-001`, le titre du §18.1 et l'entrée du §4.

**Note** : le constat 2, voisin, est traité — le catalogue compte quatorze
permissions. Le décompte des portées est une dimension distincte et reste ouvert.

---

### Groupe D — Les vérifications qu'une autre exigence rend fausses

Quatre constats de même facture. Dans les quatre cas **la décision produit est
déjà prise** : c'est l'énoncé de la vérification qui la trahit. Ils ne demandent
donc pas d'arbitrage, seulement une réécriture attentive — mais ils sont
bloquants parce qu'un test de recette écrit sur ces phrases échouera, et sera
« corrigé » dans le mauvais sens.

#### Constat 6 — `EXG-AVA-002` contre `EXG-AVA-007`

**Où** : §14.1 et §14.2.

**Quoi** : `EXG-AVA-002` se vérifie par « La valeur acquise d'une tâche **non
terminée est nulle**, quel que soit son reste à engager ». `EXG-AVA-007` fait
acquérir la moitié de son budget à une tâche longue non terminée, dès son entrée
dans le plan de travail.

**Pourquoi** : la vérification paraît juste isolément et devient fausse sur tout
projet portant une tâche au-delà du seuil — c'est-à-dire tout projet réel.

**Piste** : borner la vérification d'`EXG-AVA-002` aux tâches sous le seuil, ou
lui faire nommer l'exception d'`EXG-AVA-007` comme `EXG-AVA-012` nomme celle
d'`EXG-AVA-015`.

#### Constat 7 — `EXG-DEV-017` : la somme des sous-projets sur un arbre

**Où** : §11.6, à confronter à `EXG-SPR-001`, `EXG-SPR-002`, `EXG-SPR-003`.

**Quoi** : la vérification dit « Chaque sous-projet du projet a son total, et leur
**somme est égale** au total du projet ». Or les sous-projets forment un arbre à
racine unique dont la racine reçoit par défaut toute ligne non ventilée, et le
motif d'`EXG-SPR-002` suppose une agrégation le long de l'arbre.

**Pourquoi** : si un total de sous-projet inclut ses descendants, la somme
double-compte et la vérification est fausse dès le second niveau ; si elle ne les
inclut pas, aucune exigence ne le dit. Aucune exigence ne définit ce qu'est « le
total d'un sous-projet ». Aggravant : `EXG-DEV-017` est la garde sur laquelle
`EXG-PLN-031` fait reposer la détection d'un doublement silencieux du budget lors
d'une copie de sous-arbre.

**Piste** : dire si un total de sous-projet est propre ou cumulé. À trancher
aussi : « le montant du projet » est-il le montant hors inflation ou le montant
corrigé ? `EXG-DEV-017`, `EXG-DEV-018` et `EXG-PLN-031` emploient trois
formulations de la même grandeur, et `EXG-PLN-031` est la seule à préciser
laquelle.

#### Constat 13 — Le référentiel des natures est-il fermé ou extensible ?

**Où** : §11.2, `EXG-DEV-018`, `EXG-PAR-005`, §19.4.

**Quoi** : le §11.2 déclare que « le référentiel de types **reste extensible** » ;
`EXG-DEV-018` exige que « la répartition **couvre les quatre types** » et somme à
cent pour cent.

**Pourquoi** : la vérification d'`EXG-DEV-018` devient fausse le jour où un
cinquième type est créé, ce que §11.2 autorise expressément — et elle porte sur
la seule figure qui vérifie qu'un chiffrage est vraisemblable.

**Piste** : trancher si « extensible » porte sur les **types de coût**
(`EXG-PAR-005`, qui se rattachent à une nature) ou sur les **natures**
elles-mêmes. Les deux mots sont employés l'un pour l'autre dans `EXG-DEV-018`.

#### Constat 5 — Le portefeuille exige un scalaire que le projet ne produit pas

**Où** : `EXG-CHA-002`, `EXG-CHA-003`, contre `EXG-AVA-013` et `EXG-ANA-005`.

**Quoi** : le portefeuille réclame par projet un **projeté à terminaison** et un
**écart**. `EXG-AVA-013` pose que « le coût final projeté n'est pas unique […]
aucune n'est présentée comme la projection par défaut », et `EXG-ANA-005` que
« l'écart à terminaison est présenté comme un **intervalle** […] et non comme une
valeur unique ».

**Pourquoi** : la vérification d'`EXG-CHA-003` — « les valeurs d'une ligne de
portefeuille sont identiques à celles du tableau de bord du projet » — est
**impossible à exécuter**, le tableau de bord n'affichant pas de valeur unique à
comparer. L'implémenteur choisira une hypothèse par défaut, ce qu'`EXG-AVA-013`
interdit, et le fera silencieusement.

**Piste** : trancher ce que le portefeuille affiche — une fourchette, une
hypothèse nommée, ou le nombre d'hypothèses et leur écartement — et dire si c'est
une exception assumée à `EXG-AVA-013`.

*Celui-ci est à la frontière du groupe : il demande une vraie décision produit,
pas seulement une réécriture.*

---

### Groupe E — Le statut du document sur lui-même

Trois constats qui ne décrivent aucun comportement mais rendent le document
impossible à parcourir : un lecteur ne sait pas ce qui est décidé.

#### Constat 9 — Les questions ouvertes ne sont pas au même endroit dans l'annexe B et dans les chapitres

*Bloquant.*

**Où** : annexe B questions 11 et 14 ; en-têtes des chapitres 11, 14, 15 ; §11.8 ;
§14.5 ; §4.

**Quoi** : trois divergences dans le même faisceau.

- Le chapitre 11 déclare ouvert le seul point des provisions, et §11.8 ferme par
  « **Rien d'autre.** » Or §11.6, trente lignes plus haut, écrit que le sort de
  la date de décaissement et de l'état d'approvisionnement « **est ouvert
  (question 11)** ».
- Le chapitre 14 ne déclare ouverte que la question 2, alors que la question 11
  pose nommément « comment s'en mesure l'avancement, la méthode 0/100 supposant
  une tâche qui se termine là où une fourniture se commande ».
- La question 14 se déclare transverse aux chapitres 11 et 15 ; le chapitre 11 ne
  la mentionne pas, et le chapitre 15 est « Décidé ».

**Pourquoi** : un lecteur qui prend §11.8 au mot chiffrera une fourniture comme
une ligne ordinaire et se croira couvert ; un lecteur de l'annexe B saura que ce
cas n'est pas tranché.

**Piste** : arrêter une règle unique — une question transverse est reprise dans
l'en-tête et la section « Ce qui reste ouvert » de **chaque** chapitre qu'elle
nomme, et le §4 la porte — puis passer les questions 2, 11 et 14 en revue pour
aligner les chapitres 8, 10, 11, 12, 14 et 15. Et supprimer le « Rien d'autre »
du §11.8, ou le rendre vrai.

#### Constat 8 — Le chapitre 21 est « Partiel » sans aucun point ouvert

*Bloquant.*

**Où** : en-tête du chapitre 21, ligne du §4, §3.2.

**Quoi** : le §3.2 définit « Partiel » comme « Décidé sauf points **explicitement
listés** ». Le chapitre 21 porte « Statut : partiel » et ne liste rien : pas de
section « Ce qui reste ouvert », aucun point ouvert au §4, et un renvoi à
l'annexe C — qui recense les écarts avec l'implémentation, non des décisions
manquantes. Son en-tête dit en outre « Ce document-là reste vivant tant qu'E14 se
livre », alors qu'E14 est livré.

**Pourquoi** : un statut « Partiel » sans liste dit à un lecteur qu'il manque une
décision sans lui dire laquelle. Il cherchera, ne trouvera pas, et reposera la
question.

**Piste** : soit passer le chapitre 21 à « Décidé » — un renvoi à l'annexe C est
un écart de livraison, pas un point ouvert au sens du §3.2, et c'est le
traitement qu'ont reçu les chapitres 13 et 19 —, soit écrire le point qui reste
ouvert et l'inscrire au §4. Retirer dans les deux cas la phrase sur E14.

#### Constat 12 — La question 5 est close mais n'a jamais été absorbée

*Bloquant.*

**Où** : `EXG-LOT-011` (§8.5), annexe B question 5, annexe C.

**Quoi** : `EXG-LOT-011` exige que la regénération ne soit proposée « que si […]
le planning n'a pas été retouché depuis » — sans dire comment cela se sait. La
question 5, **close**, porte la décision entière : empreinte portée par la
révision, calculée sur le lotissement et sur l'arbre produit, couvrant la forme
de l'arbre, les libellés, les valeurs de planification saisies, le calendrier
épinglé à la main et les liens traduits en chemins de positions, à l'exclusion
des valeurs dérivées et des identifiants.

**Pourquoi** : l'en-tête de l'annexe B dit « chacune sera reprise dans son
chapitre ». Celle-ci ne l'a pas été. Le chapitre 8 est donc un trou fonctionnel —
le motif d'`EXG-LOT-011` suppose un mécanisme qu'aucune exigence n'établit — et
l'annexe B est devenue une seconde source de vérité.

**Piste** : absorber la décision de la question 5 dans le §8.5 sous forme
d'exigence avec vérification, et réduire l'entrée d'annexe B à une trace de
décision.

---

### Hors groupe

#### Constat 10 — « En jeu » a deux définitions, et le premier passage n'est traité par personne

*Bloquant.*

**Où** : `EXG-RAE-011`, `EXG-RAE-012`, `EXG-RAE-013` (§12.3), annexe B
question 20.

**Quoi** : `EXG-RAE-011` dit que la saisie porte par défaut sur « les tâches **en
jeu à la date de la revue** », et se vérifie par « la revue présente d'emblée les
seules tâches concernées par la période ». La question 20, tranchée, définit « en
jeu » autrement : « une tâche est "en jeu" quand elle appartient au **plan de
travail** d'une revue, et l'y faire entrer déclare son démarrage ».

**Pourquoi** : les deux définitions ne coïncident pas. Sous la première, le
système calcule le périmètre à partir des dates ; sous la seconde, il le tient
d'un geste utilisateur — et alors, à la **première** revue, le plan de travail
est vide et la saisie ne porte sur rien. Aucune exigence ne dit ce que contient
le plan de travail au premier passage. Aggravant : le §12.3 borne le réservoir
« aux tâches dont la fenêtre s'ouvre dans **l'horizon de la revue** », grandeur ni
définie ni chiffrée.

**Piste** : trancher si le plan de travail est amorcé automatiquement à la
première revue et selon quel critère de date, ou s'il est vide et se remplit à la
main ; puis aligner `EXG-RAE-011` sur la définition de la question 20. Et chiffrer
« l'horizon de la revue », ou le rattacher à un paramètre existant.

---

## 4. Résiduels et cosmétiques

Indépendants les uns des autres, traitables dans n'importe quel ordre. Un lecteur
s'en sort mais hésite.

| # | Où | Quoi | Piste |
|---|---|---|---|
| 14 | `EXG-CYC-008`, `EXG-CYC-009`, `EXG-CYC-018`, `EXG-NAV-008`, `EXG-DEV-009`, `EXG-DEV-012`, `EXG-MOD-023` | Le vocabulaire « couple planning + devis » et « ses devis » au pluriel survit à l'arbitrage E14, alors que §5.6 et `EXG-MOD-001` posent deux **vues d'une même révision** et qu'il n'existe pas de couple. L'annexe C atteste que le code teste encore les deux anciennes références. | Passe de vocabulaire sur ces sept occurrences. |
| 15 | `EXG-DEV-013` contre la liste du §11.6 | Deux exigences décrivent le contenu de la même grille et ne s'accordent pas. `EXG-DEV-013` cite un « taux appliqué » et des « montants de main-d'œuvre et d'achat » qui n'existent nulle part ailleurs ; sa vérification (« l'année dont il provient ») est trivialement satisfaite. | Reliquat de `devis v0.1` antérieur à `EXG-DEV-014` : réécrire sur les grandeurs en vigueur, ou abandonner au profit du §11.6. |
| 16 | `EXG-MSP-008` et `EXG-MSP-012` | Deux énoncés de la même règle — le signalement d'un écart de dates à l'import — avec deux vérifications différentes. Un implémenteur écrira deux signalements. | Fusionner, ou faire d'`EXG-MSP-008` le cas particulier explicite d'`EXG-MSP-012`. |
| 17 | `EXG-MSP-009` | La vérification exige qu'un aller-retour « ne déplace **aucune** date » ; le motif admet deux lignes plus haut « les écarts résiduels portant sur la conversion des durées en minutes ». | Chiffrer la tolérance, ou borner la vérification aux dates exprimées en jours. |
| 18 | `EXG-NAV-004` et la phrase qui la suit | Les projets récents sont désignés « par leur code » ; aucune exigence ne dit qu'un projet porte un code, s'il est obligatoire, unique, ni de quelle forme. Le renvoi au chapitre 21 pointe un chapitre qui ne contient pas le mot. | Écrire l'exigence qui définit le code de projet, ou retirer le renvoi et dire la règle sur place. |
| 19 | `EXG-ANA-012` contre `EXG-ANA-004` | `EXG-ANA-004` est abandonnée au motif que « la règle est énoncée une fois, au chapitre qui définit ces indices ». `EXG-ANA-012` fait exactement cela deux sections plus loin, et son motif l'assume. | Réduire `EXG-ANA-012` à ce qu'elle ajoute — l'interdiction du second axe vertical — et renvoyer au vocabulaire pour le principe. |
| 20 | `EXG-AVA-007` et la phrase qui la suit, contre `EXG-PAR-001` | Le seuil des tâches longues est « un **paramètre de projet**, fixé une fois. **Valeur de départ proposée** : cent vingt jours. » `EXG-PAR-001` clôt la liste des référentiels à cinq ; aucune exigence n'attribue ce seuil à un écran ; `EXG-CYC-015` et `EXG-CYC-016` ne le mentionnent pas. Trois défauts en une phrase : donnée produite par personne, « proposée » qui n'est pas une décision, seuil sans vérification de saisie. | Trancher si le seuil est une valeur fixe du produit ou un attribut de projet ; s'il est un attribut, dire où il se saisit et ce qui se passe s'il est vide. |
| 21 | §15.3 sous `EXG-ANA-016`, et dernière ligne du §15.5 | Deux règles normatives rédigées en prose, sans identifiant ni vérification, alors que le §3.1 pose qu'« une exigence sans vérification écrite n'est pas une exigence ». L'export tabulaire du devis — colonnes, agrégats, en-tête — est une livraison entière définie hors format vérifiable, et le §11.7 lui renvoie. Le premier cas ajoute un seuil non chiffré (« beaucoup »). | Promouvoir les deux en exigences numérotées ; chiffrer le seuil du chemin critique partiel. |
| 22 | `EXG-PAR-008` | Le calendrier porte « un nombre de semaines travaillées par an » qu'aucune exigence ne lit : la capacité est en heures par mois (`EXG-PAR-004`), le calcul des dates s'appuie sur les heures par jour de semaine. | Nommer le calcul qui la consomme, ou la retirer. |
| 23 | §1.4 | « Les chapitres Droits et Administration n'ont encore rien à perdre. […] **Ils seront rédigés** » — au futur, alors que l'en-tête annonce tous les chapitres rédigés et que les chapitres 19 et 20 portent déjà la mention au présent. | Réécrire au passé comme note d'ordre de rédaction, ou fondre dans le §1.1. |
| 24 | §5.3, §11.8, §12.7 | Trois « aujourd'hui » dans le corps de chapitres, décrivant l'état des lieux et non la cible. Les quatre autres occurrences (`EXG-DRO-011`, `EXG-MOD-008`, `EXG-MOD-011`, `EXG-NFO-011`) sont dans des motifs, ce que le §3.3 autorise. | Arbitrer si l'exception du §3.3 couvre le mot lui-même ; à défaut, reformuler les trois occurrences de corps. |
| 25 | §13.5, §23.2, `EXG-CYC-014` | Renvois périmés : §13.5 renvoie à la question **3**, dissoute dans la 11 ; §23.2 attribue la conservation des sources d'import à `EXG-CRE-005`, qui est l'idempotence — c'est `EXG-CRE-011` ; le champ Source d'`EXG-CYC-014` porte « à créer ». | Corriger les trois. |
| 26 | Annexe C | Plusieurs plages closes avant l'ajout d'exigences récentes : `EXG-AVA-001 à 014` (015 absente), `EXG-CRE-001 à 010` (011 à 014), `EXG-DRO-001 à 010` (013 et 015), `EXG-ADM-001 à 008` (009 à 012), `EXG-RAE-001 à 010` (011 à 013). Deux lignes portent `EXG-DEV-014` et se recouvrent ; `EXG-PLN-018 à 019` et `EXG-PLN-019` aussi. | Ouvrir les plages jusqu'au dernier numéro de chaque domaine ; fusionner les doublons. Aucun écart déjà comblé n'a été trouvé. |
| 27 | §4, entrée du chapitre 18 | Les six autres chapitres « Partiel » portent au §4 une mention « *Point ouvert : …* ». Le chapitre 18 n'en porte aucune, alors que son en-tête et son §18.9 annoncent deux précisions à confirmer. | Ajouter la mention, par symétrie. |

---

## 5. Ce qui n'est pas un constat

Trois questions de l'annexe B sont **ouvertes et assumées**. Ne pas les traiter
comme des trous fonctionnels : elles portent leur motif et leur périmètre.

- **Question 2 — provisions pour risques.** Transverse aux chapitres 11, 12
  et 14. La plus lourde du document : un module complet suppose registre, devis
  par risque, probabilité et état ; le minimum serait un marqueur pondéré sur la
  ligne. À décider si ce minimum est le périmètre v1.0.
- **Question 11 — sous-traitance et fournitures.** Comment mesure-t-on leur
  avancement ? Une commande passée et non livrée n'est décrite par aucune des
  trois grandeurs du modèle.
- **Question 14 — avenants.** Un avenant ajoute du travail au projet et déplace
  la référence.

En revanche, **c'est un constat** (le 9) qu'un chapitre s'appuie sur une décision
que ces questions n'ont pas prise, ou qu'il les déclare closes.

---

## 6. Table récapitulative

| # | Gravité | Groupe | Objet | État |
|---|---|---|---|---|
| 1 | Bloquant | B | L'import est-il créateur ou destructeur | Ouvert |
| 2 | Bloquant | C | Le second domaine en lecture seule | **Traité** — `c214ea5` |
| 3 | Bloquant | C | Trois portées ou quatre | Ouvert |
| 4 | Bloquant | A | Le calendrier applicable | Ouvert |
| 5 | Bloquant | D | Le projeté à terminaison du portefeuille | Ouvert |
| 6 | Bloquant | D | `EXG-AVA-002` contre le 50/50 | Ouvert |
| 7 | Bloquant | D | La somme des sous-projets | Ouvert |
| 8 | Bloquant | E | Le chapitre 21 « Partiel » sans point ouvert | Ouvert |
| 9 | Bloquant | E | Questions ouvertes désalignées | Ouvert |
| 10 | Bloquant | — | « En jeu » et la première revue | Ouvert |
| 11 | Bloquant | A | L'année d'une ligne de coût à la racine | **Traité** — `67d8602`, `11edf0a` |
| 12 | Bloquant | E | La question 5 jamais absorbée | Ouvert |
| 13 | Bloquant | D | Natures fermées ou extensibles | Ouvert |
| 14 | Résiduel | — | Vocabulaire « couple planning + devis » | Ouvert |
| 15 | Résiduel | — | `EXG-DEV-013` contre le §11.6 | Ouvert |
| 16 | Résiduel | — | Doublon `EXG-MSP-008` / `EXG-MSP-012` | Ouvert |
| 17 | Résiduel | — | `EXG-MSP-009` et sa tolérance | Ouvert |
| 18 | Résiduel | — | Le code de projet | Ouvert |
| 19 | Résiduel | — | `EXG-ANA-012` redite | Ouvert |
| 20 | Résiduel | — | Le seuil des tâches longues | Ouvert |
| 21 | Résiduel | — | Règles normatives hors exigence | Ouvert |
| 22 | Résiduel | — | Les semaines travaillées par an | Ouvert |
| 23 | Résiduel | — | Le §1.4 au futur | Ouvert |
| 24 | Cosmétique | — | Tournures datées | Ouvert |
| 25 | Cosmétique | — | Renvois périmés | Ouvert |
| 26 | Cosmétique | — | Plages d'annexe C | Ouvert |
| 27 | Cosmétique | — | §4, points ouverts du chapitre 18 | Ouvert |
| 28 | Bloquant | A | Deux « années de référence » | Ouvert |
| 29 | Bloquant | A | La graine de la date de début du projet | Ouvert |

**Treize bloquants ouverts** : 1, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 28 et 29. Ils
représentent douze décisions, 29 se tranchant avec 4.

---

## 7. Origine

- Passe de cohérence globale sur les 5 820 lignes du document, 2026-09-16,
  agent `spec-reviewer` : constats 1 à 27.
- Revue ciblée du commit `67d8602`, même agent : treize défauts, onze corrigés
  par `11edf0a`, un versé au constat 28, un au constat 29.
- Constat 28 trouvé en traitant le constat 11, par confrontation du §12.5 à
  `EXG-DEV-005`.
- Constat 29 laissé ouvert par `67d8602`, qui a délibérément borné `EXG-DEV-021`
  au chiffrage pour ne pas le préempter.

Les vérifications mécaniques du document sont vertes à cette date : délimiteurs
de bloc appariés, aucun renvoi vers une exigence inexistante, aucun trou de
numérotation, aucun doublon d'identifiant hors l'exemple volontaire du §3.1.
