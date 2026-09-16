# Waterfall — Spécification v1.0

**Statut : tous les chapitres rédigés. Trois questions ouvertes (annexe B).**

Ce document est la spécification unique de Waterfall. Il a absorbé les
spécifications partielles produites pendant le cadrage ; aucune d'elles ne fait
plus autorité.

---

## 1. Objet du document

### 1.1 Pourquoi ce document

Les décisions produit de Waterfall sont aujourd'hui dispersées : quatre
spécifications partielles de portées inégales, des EPIC GitHub qui contiennent
des arbitrages structurants, une maquette d'architecture d'information, et des
messages de commit. Rien ne garantit qu'une décision prise ne soit pas perdue,
ni qu'elle ne soit pas contredite ailleurs.

Ce document rassemble ces décisions sous forme d'**exigences numérotées et
vérifiables**.

### 1.2 Ce qu'il remplace

| Document | Sort |
|---|---|
| `devis-v0.1-specification.md` | Absorbé par le chapitre 11. Il contenait au moins une erreur signalée par E10 (#250) : une colonne « engagé » qui n'existe pas. |
| Architecture d'information v0.1 | Absorbée par les chapitres 6, 7, 15 et 16. Document de travail du cadrage, non publié. |
| Avancement et valeur acquise v0.1 | Absorbée par le chapitre 14. Document de travail du cadrage, non publié. |
| Lotissement v0.1 | Absorbée par le chapitre 8. Document de travail du cadrage, non publié. |
| `planning-acceptance-checklist.md` | Absorbée. Le versionnage et les brouillons relèvent du chapitre 21, l'écart présenté avant confirmation d'`EXG-MSP-014`, le banc de performance d'`EXG-NFO-001`. Ce qui y reste est un relevé de livraison. |
| `revision-v0.1-specification.md` | Absorbée **sur le fond** par le chapitre 21. Elle reste la référence de la livraison E14 et continue d'être tenue à jour jusqu'à sa clôture ; c'est le seul de ces documents qui vive encore. |

Le champ **Source** d'une exigence peut nommer l'un de ces documents. C'est une
indication de provenance — d'où vient la décision — et non un renvoi : ce qui
fait foi est écrit ici.

Les EPIC E10 (#250), E11 (#255) et E14 (#326) restent la référence de leur
propre livraison ; ce document reprend leurs décisions de portée produit, pas
leur découpage technique.

### 1.3 Ce que « v1.0 » désigne

Deux jalons, deux finalités distinctes.

| Jalon | Finalité |
|---|---|
| **MVP** — probablement v0.6 ou v0.7 | Valider les concepts et les modèles, et permettre des démonstrations. |
| **v1.0** | **La première version réellement utilisable.** |

Ce document définit le périmètre borné de la v1.0, pas celui du MVP ni l'horizon
du produit.

**Critère d'inclusion** : une fonctionnalité relève de la v1.0 si son absence
rend le produit inutilisable en conditions réelles. Si son absence le rend
seulement moins agréable, elle relève d'une version ultérieure.

Ce critère est la règle d'arbitrage de l'ensemble du document, et il est plus
exigeant qu'il n'y paraît. Il rend notamment obligatoires, et non plus
optionnels :

- **les droits d'accès et le partage de projet** (chapitre 18) — un produit
  multi-utilisateurs sans habilitations n'est pas exploitable ;
- **la sauvegarde et la restauration** (chapitre 20) — on n'exploite pas un
  système dont on ne sait pas restaurer les données ;
- **le coût réel** (chapitre 13) — sans lui, la moitié des indicateurs d'analyse
  restent vides, et l'analyse est la finalité du produit.

Ces trois points portent aujourd'hui un statut « ouvert » ou « partiel » : cela
signifie qu'ils restent à cadrer, pas qu'ils soient facultatifs.

### 1.4 Ordre de rédaction

Les chapitres métier sont rédigés en premier. Ce n'est pas une préférence mais
une gestion de risque : les décisions métier n'existent aujourd'hui que dans des
artefacts dispersés et dans la mémoire de ceux qui les ont prises, alors que les
chapitres Droits et Administration n'ont encore rien à perdre. Les écrire d'abord reviendrait à
créer de l'information pendant qu'on en perd ailleurs.

Ces deux chapitres sont par ailleurs **faiblement couplés** au reste :
sauvegarde, restauration et supervision ne contraignent pas le modèle métier, et
le modèle d'habilitation est déjà arrêté. Ils seront rédigés sans séance de
cadrage, puis soumis à relecture.

---

## 2. Ce qu'est Waterfall

### 2.1 La thèse du produit

**L'objectif premier de Waterfall est l'analyse.** Tout le reste — saisir un
lotissement, importer un planning, chiffrer un devis, tenir un reste à engager —
existe pour alimenter la restitution qui dit au chef de projet et à sa
hiérarchie où en est réellement l'affaire.

Cette hiérarchie des finalités commande des arbitrages tout au long du document.
Quand une saisie est pénible mais conditionne un indicateur fiable, elle est
conservée. Quand un écran est agréable mais ne nourrit aucune décision, il ne
l'est pas.

### 2.2 Ce que Waterfall n'est pas

**Ce n'est pas un ordonnanceur.** MS Project reste la référence de
planification, et son rôle est **annexe** : il sert à ceux qui préfèrent son
interface pour construire un planning. Waterfall n'en retient que les tâches et
les liens de précédence ; les calendriers et les ressources du fichier sont
ignorés et remplacés par les siens.

**Ce n'est pas un outil de gestion de ressources.** Les rôles et les coûts sont
attribués par le devis, après le planning.

**Ce n'est pas un ERP.** Les coûts réels viennent de SAP par import ; Waterfall
ne les produit pas.

### 2.3 Le flux de travail

```
   Créer un projet
        ↓
   Saisir le lotissement             → facultatif ; le projet devient « initialisé »
        ↓
   Démarrer un planning              → squelette, planning vierge ou import MS Project
        ↓
   Chiffrer un devis                 → le projet devient « en chiffrage »
        ↓
   Désigner la révision de référence → le projet devient « en cours »
        ↓
   Revue mensuelle                   ⟳ nouvelle révision + reste à engager
        ↓
   Analyser
```

L'analyse n'est pas la dernière étape : elle est disponible en continu et
constitue la finalité de toutes les précédentes.

---

## 3. Conventions

### 3.1 Forme d'une exigence

```
EXG-AVA-012 — DOIT — La valeur acquise d'une tâche récapitulative est nulle.
  Motif        Sa valeur est portée par ses enfants ; la compter la doublerait.
  Vérification Sur un projet dont toutes les tâches feuilles sont terminées, la
               somme des valeurs acquises est égale au budget de référence — les
               lignes qu'aucune feuille ne porte ayant acquis la totalité du leur
               (`EXG-AVA-015`).
  Source       avancement v0.1, E10 (#250)
```

L'exemple ci-dessus n'est pas fictif : c'est `EXG-AVA-012`, citée du
chapitre 14.

- **Identifiant** `EXG-<DOM>-<nnn>`, où `<DOM>` est le code à trois lettres du
  chapitre. Un numéro n'est **jamais** réutilisé ni renuméroté. Une exigence
  retirée passe au statut « abandonnée » et conserve sa place.
- **Niveau** : `DOIT` (obligatoire), `DEVRAIT` (recommandé, un écart doit être
  justifié), `PEUT` (optionnel), `ABANDONNÉE` (retirée, place conservée, motif du
  retrait écrit). Une exigence est retirée pour deux raisons distinctes, et le
  motif doit dire laquelle : parce qu'elle était fausse ou mal placée, ou parce
  qu'elle est **sortie du périmètre de la v1.0** — auquel cas elle est décrite
  au chapitre 23, où elle reste disponible pour une version ultérieure.
- **Motif** : pourquoi, en une phrase. Sans lui, l'exigence sera « simplifiée »
  par quelqu'un qui n'en connaît pas la raison.
- **Vérification** : la condition observable qui permet de dire que l'exigence
  est satisfaite. Une exigence sans vérification écrite n'est pas une exigence.
- **Source** : d'où vient la décision.

### 3.2 Statuts de chapitre

| Statut | Signification |
|---|---|
| **Décidé** | Les arbitrages sont pris, le chapitre est rédigeable. |
| **Partiel** | Décidé sauf points explicitement listés. |
| **Ouvert** | Cadrage non fait. |

### 3.3 Le document décrit l'état cible

Une exigence énonce ce qui doit être vrai, jamais le chemin pour y arriver.
Elle ne se formule donc ni comme une correction (« X est renommé en Y »), ni
comme une interdiction tirée d'un incident (« ne plus faire X »), mais comme
l'état attendu, lisible sans connaître ce qui l'a précédé.

Cela ne fait pas disparaître les écarts avec l'implémentation actuelle : ils
sont réels et doivent être livrés. Ils sont recensés à l'**annexe C**, qui est
la liste de travail, tandis que les chapitres restent la description du produit.
Un lecteur qui découvre Waterfall dans trois ans lira les chapitres ; l'annexe C
aura disparu, vidée par les livraisons.

Un **motif** peut en revanche citer l'incident qui a révélé le besoin : c'est
souvent la seule chose qui empêche qu'une exigence soit « simplifiée » plus tard
par quelqu'un qui n'en voit plus l'utilité.

### 3.4 Codes de domaine

`GEN` général · `VOC` vocabulaire · `CYC` cycle de vie · `NAV` navigation ·
`LOT` lotissement · `SPR` sous-projets · `PLN` planning · `DEV` devis ·
`RAE` reste à engager · `CRE` coûts réels · `AVA` avancement · `ANA` analyse ·
`CHA` plan de charge · `MSP` MS Project · `DRO` droits et partage ·
`PAR` paramètres · `ADM` administration ·
`MOD` modèle de données · `NFO` non fonctionnel

---

## 4. Plan

| # | Chapitre | Code | Statut | Sources |
|---|---|---|---|---|
| 5 | Vocabulaire | VOC | Décidé | transverse |
| 6 | Cycle de vie d'un projet | CYC | Décidé | IA v0.1, maquette |
| 7 | Architecture d'information et navigation | NAV | Décidé | IA v0.1, maquette |
| 8 | Lotissement | LOT | Partiel | lotissement v0.1 |
| 9 | Sous-projets et ventilation | SPR | Décidé | maquette, E11 |
| 10 | Planning | PLN | Partiel | code existant, maquette |
| 11 | Devis | DEV | Partiel | devis v0.1, E12 |
| 12 | Reste à engager et revue mensuelle | RAE | Partiel | E10 (#250) |
| 13 | Coûts réels | CRE | Décidé | E11 (#255) |
| 14 | Avancement et valeur acquise | AVA | Partiel | avancement v0.1, E10 |
| 15 | Analyse et restitution | ANA | Décidé | maquette |
| 16 | Management et portefeuille | CHA | Décidé | maquette |
| 17 | Import et export MS Project | MSP | Décidé | code existant |
| 18 | Droits, partage et organisation | DRO | Partiel — **requis v1.0** | analyse du 2026-09-06 |
| 19 | Paramètres | PAR | Décidé — **requis v1.0** | implémentation, arbitrage 2026-09-13 |
| 20 | Administration | ADM | Décidé — **requis v1.0** | arbitrage 2026-09-13 |
| 21 | Modèle de données cible | MOD | Partiel | E14 (#326) |
| 22 | Exigences non fonctionnelles | NFO | Décidé | code existant |
| 23 | Hors périmètre v1.0 | — | — | — |

### Détail du plan

**5. Vocabulaire.** Les termes que ce document emploie avec un sens précis, et
les confusions qu'il faut prévenir : avancement physique contre financier, lot
contre sous-projet, révision contre version, budget de référence contre projeté,
consommé contre engagé.

**6. Cycle de vie d'un projet.** Les sept états, leurs transitions automatiques
et manuelles, l'irréversibilité des statuts terminaux, et ce que chaque état
autorise.

**7. Architecture d'information et navigation.** Les quatre sections, les cinq
projets récents désignés par leur code, les cinq onglets d'un projet et le
libellé variable du troisième. L'encodage visuel des statuts est traité au
chapitre 6, avec le cycle de vie.

**8. Lotissement.** Poste, lot, livrable ; la liste des livrables contractuels et
les quatre usages qui la justifient ; le rang du lotissement hors de la révision ;
le squelette comme aide et non comme étape. *Point ouvert : avenants
(question 14).*

**9. Sous-projets et ventilation.** L'arbre des codes de sous-projet, la
ventilation des coûts, et le code comme clé de rapprochement comptable. Les
lignes de coût de support s'y rattachent comme les autres ; la façon d'en
déterminer la quantité relève des chapitres 11 et 12.

**10. Planning.** Ce que Waterfall retient d'un planning, le mode manuel ou
automatique et ses contraintes, la propagation aux successeurs, les
récapitulatives et les jalons, le panneau de contrôle, la disposition de l'onglet
et la table. *Point ouvert : marquage des tâches d'avenant (question 14).*

**11. Devis.** Ce qu'un devis chiffre et ce qu'il ne confond pas, les quatre
natures de ligne et leurs deux formules, le taux tiré du référentiel, l'année de
référence et l'inflation qui la projette, les lignes de support et le total de
sélection qui les chiffre, la validation et l'instantané qu'elle fige, la
disposition de l'écran. *Point ouvert : provisions pour risques (question 2).*

**12. Reste à engager et revue mensuelle.** Le geste métier unique, sa
granularité à la ligne de coût et son groupement par code de sous-projet, le
rapprochement avec la référence et la mise en évidence du travail non anticipé,
l'achèvement déduit d'une remise à zéro, le périmètre de saisie borné aux tâches
en jeu et présentées en trois zones de natures différentes, la réconciliation
annuelle des taux, et l'immuabilité d'une revue validée. *Points ouverts :
provisions pour risques (question 2), sous-traitance et fournitures
(question 11).*

**13. Coûts réels.** L'import et son idempotence, qui est aussi le mécanisme de
reprise après rejet, le rattachement par le sous-code d'imputation analytique, le
rejet individuel plutôt que le blocage, les montants repris tels quels sans
recalcul, l'exclusion de périmètre et les deux consommés, et la granularité à
laquelle consommé et reste à engager se comparent.

**14. Avancement et valeur acquise.** L'avancement déduit et jamais estimé, la
méthode 0/100 pondérée par le budget de référence, le 50/50 des tâches longues,
les bornes et l'indisponibilité des indices avant le pilotage, les projections
multiples et les tendances. *Point ouvert : provisions pour risques
(question 2).*

**15. Analyse et restitution.** Le tableau de bord comme enchaînement de
questions, sa disposition fixe en v1.0, les tuiles avant les graphiques, le
catalogue des analyses, l'organigramme des tâches et son bornage, les règles de
représentation et l'export.

**16. Management et portefeuille.** Ce que la section agrège et pour qui, le
portefeuille comme vue de surveillance dont les valeurs sont reprises sans
recalcul, le plan de charge, sa ventilation par rôle et par nœud d'organisation,
et la capacité tracée comme un niveau constant.

**17. Import et export MS Project.** L'échange par fichier et non par
synchronisation, l'import qui produit une version plutôt que d'en modifier une,
l'identifiant d'échange conservé qui rend l'aller-retour possible, la hiérarchie
déduite de la numérotation, l'écart de calendrier signalé, et un export qui vise
la lecture d'un planning et non la restitution d'un chiffrage.

**18. Droits, partage et organisation.** Qui voit quoi, et comment un projet se
partage entre utilisateurs. Le modèle a été arrêté le 2026-09-06 puis son
implémentation différée après le MVP : arbre `org_unit` générique réutilisant
l'arbre de ressources existant ; trois portées de rôle additives — plateforme,
nœud d'organisation avec cascade aux descendants, et appartenance explicite à un
projet comme échappatoire pour les intervenants transverses ; catalogue de
permissions figé dans le code, rôles configurables. Ce chapitre **fait partie de
la v1.0** : le report décidé en 2026-09-06 portait sur l'implémentation avant le
MVP, pas sur le périmètre de la première version utilisable.

**19. Paramètres.** Le référentiel métier commun à tous les projets :
l'organisation, les rôles de ressource et leur capacité, les natures et
catégories de coût, les taux horaires et les calendriers. Ce qu'un projet
choisit sans jamais le redéfinir — l'inflation en est exclue, étant une
hypothèse d'affaire.

**20. Administration.** Les comptes et leur désactivation, la sauvegarde
couvrant la base et les fichiers conservés, la restauration éprouvée plutôt que
documentée, la trace des actes irréversibles sur laquelle quatre chapitres
s'appuyaient sans qu'elle existe, et ce que le système dit de lui-même. Il
administre aussi les habilitations définies au chapitre 18.

**21. Modèle de données cible.** La révision unique portant les facettes
planification et coût, telle que définie par E14. **Horodatages de ligne** : date
de création et de dernière modification sur toute table, et auteur de l'une comme
de l'autre sur les seules tables dont les lignes sont éditées individuellement
par une personne. Les lignes produites par lot — pièces comptables importées,
instantanés de version — tiennent leur auteur du lot ou de la version qui les a
produites, et non d'une colonne répétée des milliers de fois. Ces horodatages ne
remplacent pas la trace du chapitre 20 : ils disent qui a touché une ligne en
dernier, jamais ce qu'elle valait avant ni pourquoi elle a changé.

**22. Exigences non fonctionnelles.** La volumétrie gardée par un banc de
performance, l'accessibilité au clavier et au contraste, les deux thèmes, le
contrat d'échange vérifié contre les routes servies, les gardes de qualité
identiques en local et en intégration, la montée en charge et le cache, et la
langue.

**23. Hors périmètre v1.0.** Ce qui a été envisagé puis écarté, avec la raison,
en distinguant ce qui est différé de ce qui ne relève pas de ce produit.

---

---

## 5. Vocabulaire

**Statut : décidé.**

Ce chapitre fixe le sens des termes. Il n'est pas décoratif : trois erreurs de
conception rencontrées pendant le cadrage étaient des erreurs de vocabulaire
avant d'être des erreurs de raisonnement — un avancement comparé à un autre qui
n'avait pas le même dénominateur, un lot confondu avec un sous-projet, et un rôle
prêté à MS Project qu'il n'a pas.

### 5.1 Les deux avancements, et ce qui les sépare

Trois taux coexistent. Ils n'ont **pas le même dénominateur** et ne sont donc pas
interchangeables.

| Terme | Formule | Ce qu'il mesure |
|---|---|---|
| **Consommation du budget** | `coût réel / budget de référence` | la part du budget dépensée |
| **Avancement physique** | `valeur acquise / budget de référence` | la part du travail produite |
| **Avancement financier** | `coût réel / (coût réel + reste à engager)` | la progression dans la **projection courante** |

Dans ces trois formules, « coût réel » désigne le **consommé du périmètre**
défini en 5.3, jamais le consommé de l'affaire. Un budget de référence qui ne
couvre que le périmètre du devis ne peut être comparé qu'à un consommé de même
portée.

Les deux premiers partagent le budget de référence : ils sont comparables, leur
écart se lit directement, et leur rapport est exactement l'indice de performance
des coûts. Le troisième se mesure contre une projection qui grossit quand le
projet dérive — il est donc mécaniquement tiré vers le bas par la dérive
elle-même.

```
EXG-VOC-001 — DOIT — Le mot « avancement » n'est jamais employé seul dans
l'interface ni dans ce document ; il porte toujours son qualificatif, physique
ou financier.
  Motif        Les deux mesures divergent précisément quand le projet dérape,
               c'est-à-dire au moment où la confusion coûte le plus cher.
  Vérification Aucune étiquette d'interface ne contient « avancement » sans
               qualificatif adjacent.
  Source       avancement v0.1
```

```
EXG-VOC-002 — DOIT — Deux taux de dénominateurs différents ne sont jamais
présentés côte à côte sans que leur base soit nommée.
  Motif        Sur un projet en dépassement, l'avancement financier est inférieur
               à l'avancement physique, ce qui laisse croire que la production
               est en avance sur la dépense — l'exact contraire de la réalité.
  Vérification Toute paire de taux adjacents dans une même vue partage sa base,
               ou chacun porte la mention explicite de la sienne.
  Source       avancement v0.1, maquette
```

### 5.2 Grandeurs de la valeur acquise

| Terme | Abréviation | Définition |
|---|---|---|
| **Budget de référence** | BAC | Le coût total prévu par le devis de référence. Ne bouge pas. |
| **Valeur planifiée** | PV | La part du budget de référence qui aurait dû être produite à la date. |
| **Coût réel** | AC | Les dépenses constatées cumulées à la date. |
| **Valeur acquise** | EV | La part du budget de référence effectivement produite. |
| **Projeté à terminaison** | EAC | L'estimation courante du coût final. |
| **Écart à terminaison** | — | `EAC − BAC`. Positif = dépassement. |
| **Indice de délai** | SPI | `EV / PV`. Sous 1, le projet est en retard. |
| **Indice de coût** | CPI | `EV / AC`. Sous 1, le projet dépasse. |

Le **projeté à terminaison n'est pas unique** : plusieurs hypothèses le
calculent, et l'estimation du chef de projet en est une parmi d'autres.

### 5.3 Consommé, engagé, reste à engager

Le modèle issu d'E10 ne connaît que trois grandeurs : **budget de référence**,
**reste à engager** et **consommé**. Il n'y a pas aujourd'hui de notion d'« engagé »
distincte du consommé, et l'export SAP ne porte aucune date de commande qui
permettrait d'en dater une.

Ce n'est pas une décision, c'est l'état des lieux. Ce qu'il laisse ouvert est
énoncé en **question 11** : pour la sous-traitance et les fournitures, une
commande passée n'est ni du travail produit ni une dépense constatée, et aucune
des trois grandeurs ne la décrit.

```
EXG-VOC-003 — ABANDONNÉE — remplacée par la question ouverte 11.
  Motif        Son énoncé — « il n'existe pas de notion d'engagé » — était un
               constat de l'état actuel, pas une exigence : rien n'y était
               vérifiable au sens du chapitre 3, et il fermait par omission une
               question qui n'est pas tranchée.
```

Le **consommé** n'existe qu'à la granularité du **code de sous-projet**, jamais à
celle de la ligne de coût ni de la tâche, parce que c'est la seule granularité
que l'import SAP fournit.

Le mot recouvre en réalité **deux grandeurs**, et les confondre fausse tout
indicateur d'écart :

- le **consommé de l'affaire** est la totalité de ce que la comptabilité a imputé
  au projet ;
- le **consommé du périmètre** ne retient que les coûts correspondant au travail
  que le devis a chiffré.

Les deux diffèrent parce qu'une affaire reçoit aussi des coûts qui ne relèvent
d'aucune tâche estimée : frais généraux, et charges affectées par décision
externe — « il reste de l'argent sur cette affaire, on y passera ça ». Ces coûts
sont réels et correctement imputés ; ils ne sont simplement pas le sujet de la
mesure.

Le **périmètre du devis** est donc la base de comparaison de tous les
indicateurs. Le budget de référence ne couvre que ce périmètre ; lui opposer un
consommé plus large, c'est mesurer une dérive contre un budget qui n'a jamais
prétendu la couvrir — la même faute de dénominateur que proscrit `EXG-VOC-002`,
appliquée cette fois au numérateur.

Le **reste à engager** recouvre deux objets que le même mot désigne, et la
distinction est structurante :

- le **reste à engager global** dépend d'une structure de tâches complète. Ce qui
  le fausse est ce qui n'y figure pas — les tâches jamais anticipées ;
- le **reste à engager d'une tâche** — « il me reste une semaine » — porte sur un
  objet qui existe, et constitue une information fiable.

```
EXG-VOC-004 — DOIT — L'achèvement d'une tâche se déduit de son reste à engager
ramené à zéro, jamais d'un pourcentage saisi à l'appréciation.
  Motif        Un pourcentage intermédiaire est une opinion ; une remise à zéro
               est une affirmation binaire, bien plus visible et intenable dans
               la durée si elle est fausse.
  Vérification Une tâche dont le reste à engager est nul est comptée terminée ;
               une tâche dont il n'a jamais été saisi ne l'est pas.
  Source       E10 (#250), avancement v0.1
```

### 5.4 Découpages du projet

Trois découpages coexistent et **ne se confondent pas**.

| Découpage | Niveaux | Sert à | Porté par |
|---|---|---|---|
| **Lotissement** | poste → lot → livrable | énumérer les livrables contractuels | le projet, hors révision |
| **Sous-projets** | arbre à racine unique | ventiler les coûts | `ProjectCostCode` |
| **Planning** | arbre de tâches, profondeur libre | ordonnancer | la révision |

- **Poste** : regroupement contractuel. Ne porte aucun montant.
- **Lot** : regroupement de livrables contractuels. Il ne porte aucun montant en
  v1.0 — la gestion financière du lotissement est différée (chapitre 23).
- **Livrable** : élément contractuellement dû au client. C'est l'unité que le
  lotissement sert à ne pas oublier.
- **Sous-projet** : nœud de l'arbre des codes de coût. Chaque ligne de coût et
  chaque affectation de rôle s'y rattache.
- **Ligne de coût de support** : ligne de main-d'œuvre chiffrant un travail
  d'encadrement — management, qualité, assurance produit — dont la quantité
  d'heures se détermine en proportion de l'effort encadré plutôt que par
  estimation directe. Elle n'a aucune autre particularité : même rôle, même taux,
  même inflation, même reste à engager, et le coût réel lui revient par
  imputation comme à toute autre ligne. Il n'existe pas de « sous-projet de
  support » : le support est une nature de ligne, pas de nœud.

```
EXG-VOC-005 — DOIT — « Lot » et « sous-projet » ne sont jamais employés l'un
pour l'autre.
  Motif        Le premier énumère ce qui est dû au client, le second ventile
               des coûts. Un projet a les deux, et ils ne se recouvrent pas.
  Vérification Aucun libellé d'interface n'emploie l'un des deux termes pour
               désigner l'objet de l'autre.
  Source       maquette, lotissement-v0.1
```

### 5.5 Structure du planning

- **Tâche** : unité de travail portant une durée et des dates.
- **Jalon** : événement daté, de durée nulle, sans coût.
- **Tâche récapitulative** : tâche qui porte au moins une **sous-tâche**. Sa
  valeur est portée par ses enfants et n'est jamais comptée pour elle-même.
- **Tâche feuille** : tâche qui ne porte aucune sous-tâche. Les deux qualités se
  jugent sur les seules **tâches** enfants : une tâche feuille peut porter des
  lignes de coût, qui sont pourtant des nœuds enfants elles aussi
  (`EXG-MOD-012`). Sans cette précision, toute tâche chiffrée serait une
  récapitulative et plus aucune ligne ne pourrait acquérir (`EXG-AVA-015`).
- **Prédécesseur** : lien d'antériorité, typé — fin-début, fin-fin, début-début,
  début-fin — dont dépend la date à laquelle il s'ancre.
- **Mode manuel** : les dates sont saisies telles quelles.
- **Mode automatique** : les dates sont calculées à partir d'une durée et d'un
  point d'ancrage, qui est soit une date de début stockée, soit un prédécesseur
  qui en fournit une.

```
EXG-VOC-006 — DOIT — La structure du planning est libre.
  Motif        Le découpage poste / lot / livrable est une bonne pratique, pas
               une contrainte. Un planning importé a la profondeur et la
               nomenclature qu'on lui a données.
  Vérification Aucun écran ne nomme les niveaux du planning d'après le
               lotissement ; ils sont numérotés.
  Source       maquette
```

### 5.6 Versions et références

- **Révision** : version complète du projet à une date. C'est l'unité qui se
  crée, se valide et s'archive ; l'objet que le reste du document désigne quand
  il parle d'une version du projet.

  Elle porte **l'arbre des nœuds** du projet, et chaque nœud y porte exactement
  une facette (`EXG-MOD-012`) : une **facette de planification** — dates, durée,
  mode, liens de précédence — si le nœud est une tâche, une **facette de coût**
  — nature, quantité, montant, imputation — si le nœud est une ligne de coût.
  Elle porte aussi son **nom** et sa description (`EXG-MOD-023`), son statut de
  brouillon ou de validée, ses **chronologies** et son ensemble de **jalons
  suivis** (`EXG-PLN-020`, `EXG-PLN-026`).

  Elle ne porte ni le lotissement ni l'arbre des sous-projets (5.4) : ceux-là
  appartiennent au projet et traversent les révisions. Elle ne porte pas non
  plus les coûts réels, qui sont importés au projet et rapprochés d'elle.
- **Planning** et **devis** : les deux lectures d'une même révision — l'une par
  les facettes de planification, l'autre par les facettes de coût. Ce sont deux
  vues, et non deux objets : il n'existe pas de planning séparé de son devis
  (`EXG-MOD-001`). Les deux mots restent employés pour désigner ces vues, jamais
  pour désigner des versions distinctes.
- **Révision de référence** : la révision désignée comme référence du projet. Sa
  désignation fait passer le projet en pilotage, et son chiffrage devient le
  budget de référence.
- **Revue mensuelle** : geste unique combinant la création d'une nouvelle
  révision et la saisie du reste à engager. Les deux ne se créent, ne se
  valident et ne s'archivent jamais séparément.

```
EXG-VOC-007 — DOIT — Le mot « révision » désigne exclusivement l'objet défini au
chapitre 21. Le compteur de concurrence porté par les plannings et les devis
n'est jamais désigné par ce mot, dans aucune couche.
  Motif        Ce compteur n'est pas un numéro de version mais un garde-fou de
               concurrence. L'homonymie ferait lire « le projet est en révision
               4 » là où il s'agit du nombre d'écritures concurrentes évitées.
  Vérification Aucun libellé d'interface, aucun champ de contrat et aucun nom de
               colonne ne porte « révision » pour désigner ce compteur.
  Source       E14 (#326)
```

### 5.7 Identifiants

| Terme | Nature | Portée |
|---|---|---|
| **uid** | identifiant MS Project | **externe**, relève de l'import et de l'export seuls |
| **identifiant positionnel** | rang d'affichage, calculé à la lecture | présentation |
| **work_item** | identité d'un élément de travail à travers les versions | domaine, modèle cible |

```
EXG-VOC-008 — DOIT — L'identité d'un élément de travail à travers les versions
est portée par `work_item`. L'uid MS Project est un attribut d'échange : lu à
l'import, écrit à l'export, et sans effet entre les deux.
  Motif        Une identité de domaine doit être allouée par un seul producteur.
               Un identifiant venu d'un fichier extérieur ne peut pas l'être :
               il est alloué par MS Project, et par Waterfall quand il génère.
  Vérification Aucune opération de domaine ne résout un nœud par son uid ; seuls
               l'import et l'export le lisent ou l'écrivent.
  Source       E14 (#326)
```

### 5.8 Organisation, rôles et charge

Le mot **rôle** désigne deux choses sans rapport, et c'est un piège :

- un **rôle de ressource** est une qualification professionnelle porteuse d'un
  taux horaire, utilisée pour chiffrer la main-d'œuvre ;
- un **rôle d'habilitation** est un ensemble de permissions attribué à un
  utilisateur.

```
EXG-VOC-009 — DOIT — Les deux acceptions de « rôle » sont distinguées par leur
qualificatif partout où les deux peuvent être présentes.
  Motif        Les deux notions coexistent dans l'administration et dans les
               paramètres ; leur homonymie est installée dans le modèle.
  Vérification Aucun libellé d'interface n'emploie « rôle » sans qualificatif là
               où les deux acceptions peuvent se présenter.
  Source       analyse du 2026-09-06
```

- **Nœud d'organisation** : nœud de l'arbre qui structure l'entreprise. Le même
  arbre sert à rattacher les rôles de ressource et, dans le modèle cible, à
  porter les habilitations.
- **Année de référence** : l'année dont les taux horaires servent de base à un
  chiffrage. C'est la seule année dont les taux doivent être connus.
- **Coefficient d'inflation** : facteur unique, porté par le projet, qui
  reporte un montant de l'année de référence sur une année ultérieure. Il se
  compose autant de fois qu'il y a d'années écoulées (`EXG-DEV-020`).
- **Charge** : quantité de travail, exprimée en heures.
- **Coût** : valorisation de cette charge, en euros.
- **Capacité** : charge qu'un périmètre peut absorber sur une période.

```
EXG-VOC-010 — DOIT — Charge et coût ne sont jamais exprimés dans la même unité
ni sur le même axe.
  Motif        La charge se raisonne en heures et se compare à une capacité ; le
               coût se raisonne en euros et se compare à un budget.
  Vérification Aucune vue ne somme des heures et des euros, et aucun graphique ne
               porte les deux sur le même axe.
  Source       maquette
```

---

## 6. Cycle de vie d'un projet

**Statut : décidé.**

Le statut d'un projet n'est pas une étiquette décorative : il commande ce qui est
modifiable. Le principe directeur de ce chapitre est qu'**un projet n'avance pas
parce qu'on le lui demande, mais parce que le travail a été fait**. Les
transitions de progression sont donc automatiques et déduites d'un fait
observable ; seules les sorties sont des décisions humaines.

### 6.1 Les sept états

| État | Code | Ce qu'il signifie |
|---|---|---|
| Créé | `cree` | La fiche existe, rien n'a été décidé du contenu. |
| Initialisé | `initialise` | Le lotissement est saisi : on sait ce qu'on vend. |
| Chiffrage | `en_chiffrage` | Un planning et un devis existent et se construisent. |
| En cours | `en_cours` | Une révision de référence est désignée : le projet est piloté. |
| Terminé | `termine` | Le projet est allé à son terme. |
| Perdu | `perdu` | L'affaire n'a pas été remportée. |
| Abandonné | `abandonne` | Le projet est arrêté avant son terme. |

```
EXG-CYC-001 — DOIT — Ces sept états sont les seuls. Aucun écran, aucun endpoint
n'expose de statut supplémentaire ni d'état intermédiaire implicite.
  Motif        Un statut commande des droits d'écriture ; un état non déclaré est
               un trou dans la règle d'immuabilité.
  Vérification L'énumération des statuts du contrat OpenAPI compte exactement
               sept valeurs et coïncide avec ce tableau.
  Source       schemas/projects.py, services/project_lifecycle.py
```

```
EXG-CYC-002 — DOIT — Le troisième état porte le code `en_chiffrage` et le
libellé « Chiffrage ».
  Motif        Tout projet franchit cet état, y compris ceux qui ne répondent à
               aucun appel d'offres. Le nom d'un état doit décrire le travail qui
               s'y fait, et ce travail est le chiffrage. Le franchissement
               obligatoire n'est pas un défaut : c'est le moment où le planning
               et le devis se construisent.
  Vérification Aucun statut n'est désigné par « appel d'offres » ni par une de
               ses abréviations.
  Source       arbitrage maquette
```

### 6.2 Prérequis de configuration

Un projet ne se pilote pas dans le vide : le planning a besoin d'un calendrier
pour convertir une durée en dates, et le devis a besoin de rôles, de taux et
d'une inflation pour convertir une charge en euros. Le calendrier, les rôles et
les taux sont portés par le référentiel commun, l'inflation par le projet
lui-même (`EXG-DEV-020`) ; dans les deux cas, un projet créé sans eux est un
projet qui échouera plus tard, loin de la cause.

Ils se vérifient en **deux temps** : ce qui ne dépend que de l'existence du
référentiel se vérifie dès la création ; ce qui dépend des catégories que le
devis emploie réellement ne peut se vérifier qu'au devis. Le second temps ne
porte que sur l'**année de référence** du devis : un chiffrage n'a jamais besoin
de connaître les taux des années futures.

```
EXG-CYC-015 — DOIT — La création d'un projet est refusée tant que le référentiel
commun (chapitre 19) est incomplet : calendrier par défaut actif portant au moins
un jour ouvré, au moins une catégorie de coût active, au moins un rôle de
ressource actif.
  Motif        Sans jour ouvré, toute durée calculée vaut zéro ; sans catégorie
               ni rôle, aucune ligne de devis ne peut être chiffrée. Laisser
               créer le projet ne fait que déplacer l'échec vers un écran où la
               cause n'est plus visible.
  Vérification La création est refusée et la réponse nomme chaque prérequis
               manquant ; elle aboutit dès qu'ils sont tous satisfaits.
  Source       #109, services/project_setup.py
```

```
EXG-CYC-016 — DOIT — Le calcul d'un devis ou d'un reste à engager est refusé
tant qu'une catégorie de coût employée n'a pas de taux horaire pour l'**année de
référence** du chiffrage, ou que le projet ne porte pas de coefficient
d'inflation. Les manques sont nommés un à un.
  Motif        Un taux manquant substitué par zéro produit un budget faux sans
               rien signaler. La couverture exigée s'arrête à l'année de
               référence : exiger un taux pour chaque année future demanderait
               une donnée qui n'existe pas — c'est précisément le rôle de
               l'inflation que de projeter le taux connu sur les années à venir.
               Le contrôle sur l'inflation est binaire, le projet portant un
               coefficient unique (`EXG-DEV-020`) : il est saisi ou il ne l'est
               pas, et il n'y a pas d'année à couvrir.
  Vérification Le refus énumère les catégories sans taux pour l'année de
               référence, et signale l'absence de coefficient d'inflation sur le
               projet.
  Source       arbitrage 2026-09-12 ; services/estimate_calculation.py (#175)
```

Le mécanisme lui-même appartient au chapitre 11, mais son principe commande ce
qui précède : **on chiffre avec les taux de l'année de référence, et le planning
dit quand la charge sera consommée**. L'inflation reporte le taux connu sur
l'année de consommation prévue. Aucune autre donnée de taux n'est requise.

```
EXG-CYC-017 — ABANDONNÉE — sortie du périmètre v1.0 avec la trésorerie
(chapitre 23).
  Motif        Elle exigeait des lots valorisés pour entrer en pilotage, au motif
               que la courbe de trésorerie s'en nourrit. La trésorerie étant
               différée, le lot ne porte plus de montant et la condition n'a plus
               d'objet.
```

### 6.3 Transitions de progression — automatiques

```
EXG-CYC-003 — DOIT — Les trois transitions de progression sont déclenchées par
un fait métier et ne sont jamais offertes à l'utilisateur comme une action.
  Motif        Un statut qu'on avance à la main finit par décrire l'intention de
               celui qui a cliqué, pas l'état réel du projet. Déduit d'un fait, il
               reste vrai sans discipline.
  Vérification Aucun écran ne propose de bouton, de menu ou de sélecteur menant à
               `initialise`, `en_chiffrage` ou `en_cours`.
  Source       arbitrage maquette
```

| De | Vers | Déclencheur |
|---|---|---|
| `cree` | `initialise` | Enregistrement d'un lotissement non vide |
| `cree` ou `initialise` | `en_chiffrage` | Création de la première révision |
| `en_chiffrage` | `en_cours` | Désignation de la révision de référence |

```
EXG-CYC-004 — DOIT — Le passage à `en_cours` exige qu'une révision de référence
soit désignée et qu'elle porte au moins une tâche.
  Motif        La seconde condition n'est pas redondante : une désignation peut
               pointer une révision vide, et le projet serait alors piloté contre
               un budget de référence sans structure. Une seule désignation
               suffit parce qu'une révision porte les deux facettes
               (`EXG-MOD-001`) : il n'existe pas d'état où le planning serait
               référencé et le chiffrage non.
  Vérification Une tentative de passage à `en_cours` sans l'une des deux
               conditions est refusée avec un conflit, et l'interface nomme la
               condition manquante.
  Source       services/project_lifecycle.py
```

```
EXG-CYC-018 — DOIT — Le lotissement est facultatif. Un projet qui n'en a pas
passe directement de `cree` à `en_chiffrage` à la création de son planning et de
son devis.
  Motif        Sans cette voie, le lotissement resterait obligatoire de fait : il
               était la seule sortie de `cree`, donc aucun projet ne pouvait être
               chiffré sans lui. Le rendre facultatif suppose de dire par où l'on
               passe quand on s'en dispense.
  Vérification Un projet sans lotissement atteint `en_chiffrage` puis
               `en_cours`. Un projet encore à `cree` qui enregistre un
               lotissement passe par `initialise` ; au-delà de `cree`,
               l'enregistrement ne change plus le statut.
  Source       arbitrage 2026-09-13
```

```
EXG-CYC-005 — DOIT — Les conditions non satisfaites sont nommées à
l'utilisateur, une par une, avant qu'il ait tenté quoi que ce soit.
  Motif        Une transition automatique qui ne se produit pas est muette par
               nature : sans énoncé des conditions, l'utilisateur ne peut pas
               savoir ce qui manque.
  Vérification Le survol du badge de statut énonce le prochain état, son
               déclencheur, et la liste de ce qui reste à satisfaire.
  Source       maquette
```

### 6.4 Sorties — manuelles et définitives

Trois sorties seulement, et ce sont les seules transitions qu'un utilisateur
commande :

| Sortie | Depuis | Motif |
|---|---|---|
| Terminé | `en_cours` | Le projet est allé à son terme. |
| Perdu | `cree`, `initialise`, `en_chiffrage` | L'affaire ne se fera pas. |
| Abandonné | `cree`, `initialise`, `en_chiffrage`, `en_cours` | Arrêt avant terme. |

```
EXG-CYC-006 — DOIT — « Perdu » n'est pas atteignable depuis `en_cours`.
  Motif        Une affaire ne se perd qu'avant d'être lancée ; un projet lancé
               qui s'arrête est abandonné, pas perdu. La distinction porte le sens
               commercial des statistiques de projets.
  Vérification La transition `en_cours` → `perdu` est refusée par le serveur.
  Source       services/project_lifecycle.py
```

```
EXG-CYC-007 — DOIT — Les trois statuts terminaux sont irréversibles. Aucune
transition n'en part, y compris vers un autre statut terminal.
  Motif        Le projet devient une archive comptable ; sa réouverture
               invaliderait rétroactivement les analyses qui le comptaient clos.
  Vérification Toute tentative de transition depuis `termine`, `perdu` ou
               `abandonne` est refusée avec un conflit.
  Source       services/project_lifecycle.py
```

```
EXG-CYC-008 — DOIT — Une sortie manuelle est confirmée par un dialogue qui
énonce son caractère définitif et ce qu'elle rend non modifiable.
  Motif        C'est la seule action de l'application qu'aucun geste ultérieur ne
               peut annuler.
  Vérification Le dialogue nomme le statut visé, son motif, et la mise en lecture
               seule du projet, de son planning et de ses devis.
  Source       maquette
```

### 6.5 Ce que le statut autorise

```
EXG-CYC-009 — DOIT — Dans un statut terminal, le projet, ses plannings et ses
devis sont en lecture seule, et cette règle est appliquée par le serveur sur
chaque écriture, non par le masquage des commandes dans l'interface.
  Motif        Une garde côté interface protège l'utilisateur attentif ; elle ne
               protège ni un appel direct, ni un import, ni une tâche de fond.
  Vérification Toute écriture sur un projet terminal est refusée avec un conflit,
               quel que soit le point d'entrée.
  Source       services/project_lifecycle.py (`ensure_project_mutable`)
```

```
EXG-CYC-010 — DOIT — Un projet terminal reste entièrement consultable :
planning, devis, coûts réels, analyses et exports.
  Motif        La valeur d'un projet clos est justement d'être relu — pour
               chiffrer le suivant, ou pour justifier le précédent.
  Vérification Toutes les vues de lecture d'un projet clos répondent
               normalement ; seules les écritures sont refusées.
  Source       arbitrage maquette
```

### 6.6 Restitution du statut

```
EXG-CYC-011 — DOIT — Un statut est restitué par un libellé, une icône et une
couleur. La couleur ne porte jamais l'information seule.
  Motif        Sept états séparés par la seule teinte sont indiscernables en
               vision déficiente, en impression, et en contraste forcé.
  Vérification Chaque badge de statut contient un libellé textuel et une icône
               distincte, dans tous les emplacements où il apparaît.
  Source       maquette, règles de représentation (ch. 15)
```

```
EXG-CYC-012 — DOIT — La couleur d'un statut est stable : le même statut porte la
même couleur dans la liste des projets, l'en-tête d'un projet et le plan de
charge, en thème clair comme en thème sombre.
  Motif        Une couleur qui change d'emplacement en emplacement cesse d'être
               apprise et redevient un simple ornement.
  Vérification Le couple statut → couleur est défini en un seul endroit et
               consommé par toutes les vues.
  Source       maquette
```

```
EXG-CYC-013 — DOIT — Le statut vit dans l'en-tête du projet, accompagné d'une
seule commande : le menu des sorties. Il n'existe pas de carte, de section ni
d'onglet dédié au cycle de vie.
  Motif        Une carte « cycle de vie » occupe la largeur d'un écran pour
               afficher une information d'un mot et une action rarissime, et
               repousse vers le bas le contenu utile.
  Vérification Aucune vue de projet ne consacre un bloc au statut ; les
               conditions de transition sont accessibles au survol du badge.
  Source       arbitrage maquette
```

### 6.7 Le contrat avec l'interface

```
EXG-CYC-014 — DOIT — Le serveur expose les transitions permises, les statuts
terminaux et les conditions non satisfaites. L'interface les affiche sans
réimplémenter la machine à états.
  Motif        Une table de transitions dupliquée dans les deux couches diverge :
               la règle évolue d'un côté, et l'autre continue d'afficher une
               action que le serveur refusera.
  Vérification Aucun module frontend ne contient de table de transitions ni de
               liste de statuts terminaux.
  Source       maquette (`GET /projects/{id}/status-transitions`, à créer)
```

---

## 7. Architecture d'information et navigation

**Statut : décidé.**

Deux principes commandent ce chapitre. **La navigation ne bouge pas** : ni les
sections, ni les onglets n'apparaissent ou ne disparaissent selon l'état du
projet. Et **un écran vide vaut mieux qu'un écran absent**, à condition qu'il
dise ce qui manque.

Une application qui change de forme sous les pieds de son utilisateur coûte plus
cher à apprendre qu'un écran vide correctement expliqué : l'utilisateur d'une
interface stable apprend une fois où se trouvent les choses ; celui d'une
interface mouvante réapprend à chaque état, et ne sait jamais si une fonction
manque ou s'il l'a mal cherchée.

### 7.1 Navigation principale

Quatre sections, dans cet ordre :

| Section | Contenu | Chapitre |
|---|---|---|
| **Projets** | Tous les projets, puis les projets récents | 7.2 |
| **Management** | Ce qui agrège plusieurs projets : plan de charge, portefeuille | 16 |
| **Administration** | Utilisateurs, sauvegarde, santé système | 20 |
| **Paramètres** | Organisation, coûts, calendriers | 19 |

```
EXG-NAV-001 — DOIT — Ces quatre sections sont présentes en permanence, dans cet
ordre, quel que soit l'état de l'application ou les droits de l'utilisateur.
  Motif        Une entrée qui disparaît selon les droits laisse l'utilisateur
               sans moyen de savoir qu'elle existe, ni à qui la demander. Une
               section interdite se signale, elle ne s'escamote pas.
  Vérification Les quatre entrées sont rendues pour tout utilisateur authentifié ;
               celles dont l'accès est refusé l'indiquent au clic.
  Source       IA v0.1, maquette
```

```
EXG-NAV-002 — DOIT — La gestion des utilisateurs relève d'Administration.
Paramètres ne porte que le référentiel métier : organisation, coûts,
calendriers.
  Motif        Administrer qui accède au produit et paramétrer comment il calcule
               sont deux métiers, exercés par deux personnes différentes.
  Vérification Aucun écran de gestion d'utilisateur n'est atteignable depuis
               Paramètres.
  Source       IA v0.1
```

### 7.2 Les projets récents

```
EXG-NAV-003 — DOIT — La section Projets liste les cinq derniers projets ouverts,
du plus récent au plus ancien, sous une entrée « Tous les projets » qui reste le
point d'accès complet.
  Motif        Il est rare de travailler sur plus de cinq projets à la fois. La
               liste est un raccourci vers le travail en cours, pas un index.
  Vérification L'ouverture d'un sixième projet fait sortir le plus anciennement
               ouvert ; « Tous les projets » reste atteignable en un geste.
  Source       arbitrage maquette
```

```
EXG-NAV-004 — DOIT — Un projet y est désigné par son code, jamais par son nom.
  Motif        À la largeur d'une barre latérale, les noms longs se tronquent.
               Deux projets partageant un préfixe — le cas courant dès qu'un
               projet a une variante — deviennent alors indiscernables, et la
               liste censée faire gagner du temps en fait perdre.
  Vérification Chaque entrée affiche le code du projet, sans troncature.
  Source       arbitrage maquette
```

Un projet dépourvu de code fait exception : il s'affiche sous son nom tronqué,
faute de mieux. Le référentiel n'impose pas de code (chapitre 21).

### 7.3 Navigation d'un projet

Cinq onglets :

```
Général · Planning · Devis | Reste à engager · Coûts réels · Analyse
```

```
EXG-NAV-005 — DOIT — Ces cinq onglets sont présents dans tous les états du
projet. Aucun n'apparaît ni ne disparaît.
  Motif        Voir le préambule du chapitre. Un onglet sans contenu affiche son
               état vide ; il ne se retire pas.
  Vérification Les cinq onglets sont rendus pour un projet dans chacun des sept
               états du chapitre 6.
  Source       IA v0.1, maquette
```

```
EXG-NAV-006 — DOIT — Tout onglet sans contenu affiche un état vide qui nomme ce
qui manque et propose le geste qui le produit.
  Motif        C'est la contrepartie de la stabilité : un onglet permanent qui
               n'expliquerait pas son propre vide serait pire qu'un onglet
               absent, parce qu'il laisserait croire à une panne.
  Vérification Sur un projet nouvellement créé, chacun des cinq onglets affiche
               un état vide nommant son prérequis.
  Source       maquette
```

```
EXG-NAV-007 — DOIT — Général est la page d'entrée d'un projet, et la création
d'un projet enchaîne sur l'onglet Général du projet créé.
  Motif        Général porte l'identité, les sous-projets et le lotissement —
               c'est-à-dire ce qu'on saisit en premier, et la seule chose qu'on
               puisse saisir sur un projet neuf.
  Vérification L'ouverture d'un projet depuis n'importe quelle liste, et la
               création d'un projet, aboutissent l'une comme l'autre sur Général.
  Source       IA v0.1, arbitrage maquette
```

### 7.4 Le troisième onglet change de libellé

```
EXG-NAV-008 — DOIT — Le troisième onglet s'intitule « Devis » tant qu'aucune
révision de référence n'a été désignée, et « Reste à engager » ensuite —
définitivement, y compris sur un projet clos.
  Motif        La bascule suit le geste métier, pas le statut : un projet
               abandonné après son lancement a un reste à engager à consulter, et
               le renvoyer à « Devis » désignerait le mauvais objet. Le critère
               est la désignation du couple, qui est justement ce qui a fait
               basculer le projet dans le pilotage.
  Vérification Un projet `abandonne` atteint depuis `en_cours` affiche « Reste à
               engager » ; un projet `abandonne` atteint depuis `en_chiffrage`
               affiche « Devis ».
  Source       arbitrage 2026-09-12 ; maquette
```

```
EXG-NAV-009 — DOIT — Le devis de référence reste consultable en lecture seule
après la bascule du libellé.
  Motif        C'est la base de tous les écarts affichés par l'analyse : un
               indicateur dont on ne peut pas remonter à la référence n'est pas
               vérifiable.
  Vérification Depuis l'onglet « Reste à engager », le devis de référence est
               atteignable et affiché non modifiable.
  Source       IA v0.1
```

### 7.5 L'onglet Coûts réels

```
EXG-NAV-011 — DOIT — Un onglet Coûts réels porte l'import des coûts constatés et
la consultation des lignes importées : total par code de sous-projet, et détail
des pièces qui le composent.
  Motif        Le coût réel est la moitié de tout indicateur d'écart. Sans écran
               pour le charger et le vérifier, il n'existe que dans un fichier
               que personne ne relit, et les indices d'analyse deviennent
               invérifiables — on ne peut ni les expliquer ni les contester.
  Vérification L'onglet permet de charger un export de coûts, affiche le rapport
               des lignes rejetées, et donne accès au détail pièce par pièce.
  Source       E11 (#255), arbitrage 2026-09-12
```

C'est également ici que se décide le **périmètre** : chaque ligne importée peut
être sortie du périmètre du devis, et l'écran affiche les deux totaux qui en
résultent — consommé de l'affaire et consommé du périmètre (5.3). Le geste
appartient à cet écran parce qu'il demande de voir la pièce pour en juger.

L'onglet vit à côté du reste à engager plutôt que dans Analyse : charger et
vérifier des données est une **saisie**, pas une restitution. Analyse consomme ce
que cet onglet produit.

### 7.6 Planning et Devis ne sont pas une seule grille

```
EXG-NAV-010 — DOIT — Planning et Devis présentent la même arborescence de
tâches avec des données de nature différente. Ils partagent l'arbre et les
comportements qui s'y appliquent — sélection, pliage, déplacement, largeur des
colonnes — et gardent chacun sa table. Ils restent deux onglets distincts.
  Motif        Les fusionner en une grille unique imposerait à chaque écran les
               colonnes de l'autre, et la largeur est la ressource rare de ces
               deux tables. Partager l'arbre sans partager la table est ce qui
               permet aux deux d'être denses. Partager en outre les comportements
               est ce qui garantit qu'un même geste produit le même effet des
               deux côtés — deux implémentations séparées s'accordent tant que
               personne ne les fait diverger, et divergent sans que rien ne le
               signale.
  Vérification Les deux onglets rendent le même arbre, dans le même ordre, avec
               des jeux de colonnes disjoints ; un même geste y produit le même
               effet sur la structure.
  Source       IA v0.1, E14-09 (#381)
```

### 7.7 Encodage visuel des statuts

Les règles de restitution d'un statut — libellé, icône, couleur stable, absence
de carte dédiée — appartiennent au cycle de vie et sont énoncées en **6.6**
(`EXG-CYC-011` à `EXG-CYC-013`). Elles s'appliquent partout où un statut
apparaît : liste des projets, en-tête de projet, plan de charge.

---

## 8. Lotissement

**Statut : partiel.** Un point reste ouvert : le traitement des avenants
(question 14).

Le lotissement est la liste des **livrables contractuels** : ce que le projet
doit remettre au client. Il est **facultatif**, et tout ce chapitre en découle —
il n'impose rien au planning, ne conditionne aucun écran, et un projet peut être
conduit sans lui.

Sa finalité financière — porter ce que le projet vend et quand il le facture —
est **différée** et non abandonnée (chapitre 23). Elle pourrait devenir le sujet
principal d'une version suivante ; le découpage qui la porterait existe déjà.

### 8.1 Ce que c'est

Une arborescence à trois niveaux, de profondeur fixe :

| Niveau | Rôle |
|---|---|
| **Poste** | regroupement contractuel |
| **Lot** | regroupement de livrables |
| **Livrable** | élément contractuellement dû |

```
EXG-LOT-001 — DOIT — Le lotissement a exactement trois niveaux. Sa profondeur
n'est ni variable ni configurable.
  Motif        C'est un découpage contractuel, pas une reproduction du planning.
               Un projet courant compte quatre ou cinq postes, deux à quatre lots
               par poste, et jusqu'à une dizaine de livrables par lot ; cette
               forme est stable et ne demande pas de niveau supplémentaire.
  Vérification Aucun écran ni endpoint ne permet de créer un quatrième niveau.
  Source       lotissement v0.1, arbitrage maquette
```

Le lotissement **ne se confond pas avec les sous-projets**, qui portent la
ventilation des coûts, ni avec le planning, dont la structure est libre
(`EXG-VOC-005`, `EXG-VOC-006`). Les trois découpages coexistent.

### 8.2 Ce à quoi il sert

```
EXG-LOT-013 — DOIT — Le lotissement énumère les livrables contractuels du
projet. Il ne porte aucun montant en v1.0.
  Motif        Quatre usages le justifient, et aucun n'est financier. Il fixe ce
               qui est **contractuellement dû**, donc ce qu'on ne peut pas
               oublier. Il alimente le squelette, qui garantit qu'aucun livrable
               ne manque au planning (`EXG-LOT-009`). Il se **lit** en revue,
               en regard du planning qui dit où en est le travail de chaque
               livrable — rédiger, vérifier, livrer sont des tâches comme les
               autres. Et il guide le découpage en sous-projets, que beaucoup de
               projets calquent sur les lots, ce qui facilite ensuite le
               rattachement des lignes de coût.
  Vérification Le lotissement est consultable en entier, livrable par livrable,
               et aucun écran n'y demande de montant.
  Source       arbitrage 2026-09-13
```

```
EXG-LOT-002 — ABANDONNÉE — sortie du périmètre v1.0 avec la trésorerie
(chapitre 23).
  Motif        Elle faisait porter au lot un prix de vente et une date
               contractuelle, seule source du cash-in. La courbe de trésorerie
               étant différée, ces deux attributs n'auraient aucun consommateur.
```

```
EXG-LOT-003 — ABANDONNÉE — sans objet avec `EXG-LOT-002`.
  Motif        Elle interdisait d'agréger un prix de vente avec des coûts. Sans
               prix de vente dans le modèle, la confusion qu'elle prévenait n'est
               plus exprimable.
```

### 8.3 Le lotissement vit au niveau projet

```
EXG-LOT-004 — DOIT — Le lotissement est porté par le projet, en dehors de toute
révision. Il n'est pas versionné et n'a pas d'historique.
  Motif        Il doit pouvoir être corrigé à tout moment, ne serait-ce que pour
               une coquille. Porté par la révision, il serait gelé dès la
               première validation. Les deux propriétés sont incompatibles, et
               c'est la correction permanente qui l'emporte.
  Vérification Valider une révision ne rend pas le lotissement non modifiable.
  Source       lotissement v0.1, E14 (#326)
```

```
EXG-LOT-005 — DOIT — Le lotissement est modifiable quel que soit l'état des
révisions, et cesse de l'être dans un statut terminal.
  Motif        La seule limite est celle qui vaut pour tout le projet clos
               (`EXG-CYC-009`) ; aucune autre ne se justifie.
  Vérification Un projet `en_cours` accepte une modification du lotissement ; un
               projet `termine` la refuse.
  Source       lotissement v0.1
```

### 8.4 Sa modification ne propage rien au planning

```
EXG-LOT-006 — DOIT — Modifier le lotissement ne crée, ne modifie ni ne supprime
aucune tâche du planning.
  Motif        Un lotissement corrigé pour une coquille ne doit pas réécrire un
               planning travaillé pendant des semaines. La propagation était la
               contrepartie d'un modèle où la génération restait propriétaire des
               lignes qu'elle avait créées ; ce chapitre lui retire cette
               propriété.
  Vérification Après modification du lotissement, l'arbre des tâches est
               inchangé, y compris pour un lot renommé ou supprimé.
  Source       lotissement v0.1
```

Le comportement additif et idempotent **reste légitime ailleurs** : la
réconciliation des aller-retours MS Project en dépend (chapitre 17). Il n'est
retiré qu'au squelette.

```
EXG-LOT-007 — DOIT — L'enregistrement d'un lotissement non vide fait passer le
projet de `cree` à `initialise`. Un lotissement vide l'y laisse.
  Motif        C'est le seul déclencheur de cette transition (`EXG-CYC-003`) :
               savoir ce qu'on vend est ce qui distingue une fiche d'un projet.
  Vérification Enregistrer une structure sans aucun lot ne change pas le statut ;
               en enregistrer une avec au moins un lot le fait passer à
               `initialise`.
  Source       lotissement v0.1
```

```
EXG-LOT-008 — DOIT — Une clé de poste est unique dans le projet ; une clé de lot
est unique dans son poste.
  Motif        Sans unicité, deux lots homonymes rendent ambigu tout ce qui s'y
               réfère — la revue des livrables comme le rattachement d'un
               sous-projet calqué sur le lot.
  Vérification Enregistrer un lotissement comportant deux clés identiques au même
               niveau est refusé, en nommant la clé en double.
  Source       lotissement v0.1
```

### 8.5 Le squelette est une aide, pas une étape

```
EXG-LOT-009 — DOIT — Générer un squelette depuis le lotissement est l'une des
trois façons d'amorcer un planning, à égalité avec le planning vierge et
l'import MS Project. Aucune n'est obligatoire, et aucune ne conditionne l'accès
à l'onglet Planning.
  Motif        Le squelette n'est qu'une aide pour ne pas démarrer sur une page
               blanche. En faire une étape obligatoire imposait un détour à tous
               ceux qui arrivent avec un planning déjà construit.
  Vérification Un projet sans lotissement accède à l'onglet Planning et peut y
               démarrer par les deux autres voies ; l'option squelette y est
               visible mais désactivée, avec sa raison affichée.
  Source       lotissement v0.1, arbitrage maquette
```

```
EXG-LOT-010 — DOIT — La génération est ponctuelle : elle crée des tâches une
fois, puis n'entretient plus aucune relation avec elles. Elle crée en outre un
jalon de fin par lot, non saisi par l'utilisateur.
  Motif        C'est le corollaire d'`EXG-LOT-006`. Une génération qui resterait
               propriétaire de ses lignes réintroduirait la propagation qu'on
               vient de retirer.
  Vérification Une tâche issue du squelette est modifiable et supprimable comme
               n'importe quelle autre, sans effet sur le lotissement.
  Source       lotissement v0.1
```

```
EXG-LOT-011 — DOIT — La regénération n'est proposée que si un squelette existe
et que le planning n'a pas été retouché depuis. Sinon elle est refusée
explicitement, jamais ignorée en silence.
  Motif        Regénérer sur un planning retouché écraserait du travail manuel.
               Un refus muet est pire qu'un refus : l'utilisateur croit l'action
               faite.
  Vérification Sur un planning modifié après génération, la commande est
               indisponible et sa raison est affichée.
  Source       lotissement v0.1
```

```
EXG-LOT-012 — DOIT — La génération n'alloue aucun identifiant MS Project.
L'export en est le seul producteur, et l'identifiant qu'il émet pour une tâche
est conservé, de sorte qu'un import de retour réconcilie cette tâche au lieu
d'en créer une copie.
  Motif        La génération allouait ses identifiants dans la plage qu'utilise
               MS Project, si bien qu'un import adoptait régulièrement des lignes
               générées. Retirer cette allocation ne doit pas casser l'aller-
               retour : un squelette exporté pour être complété dans MS Project
               doit revenir sur ses propres tâches. Un identifiant produit à
               l'export et non conservé rendrait chaque retour aveugle.
  Vérification Une tâche issue du squelette ne porte aucun identifiant MS Project
               tant qu'elle n'a pas été exportée ; après un export puis un import
               du fichier inchangé, l'arbre est identique et aucune tâche n'est
               dupliquée.
  Source       lotissement v0.1, E14 (#326), arbitrage 2026-09-12
```

Le mécanisme de cette conservation — attribut porté par le nœud ou table de
correspondance par export — relève du chapitre 17, avec le reste de la
réconciliation MS Project.

### 8.6 Ce qui reste ouvert

**Les avenants** (question 14). Un avenant ajoute des tâches au budget de
référence. La question déborde ce chapitre.

---

## 9. Sous-projets et ventilation

**Statut : décidé.**

Le lotissement dit ce que le projet vend ; les sous-projets disent **où ses coûts
tombent**. Les deux découpages coexistent sans se recouvrir (`EXG-VOC-005`), et
c'est le second qui permet de suivre un avancement autrement qu'au niveau du
projet entier.

### 9.1 L'arbre et sa racine

```
EXG-SPR-001 — DOIT — Chaque projet porte exactement un sous-projet racine, créé
avec le projet. Tout autre sous-projet descend de cette racine.
  Motif        Une racine garantie permet à toute dépense d'avoir un point de
               rattachement, y compris sur un projet dont personne n'a encore
               défini le découpage. Sans elle, la première ligne de coût devrait
               commencer par créer une structure.
  Vérification Un projet nouvellement créé possède un sous-projet racine ; aucun
               projet n'en possède deux.
  Source       E6-01 (#62)
```

```
EXG-SPR-002 — DOIT — Un sous-projet ne peut pas devenir son propre ancêtre, et
son code est unique dans le projet.
  Motif        Un cycle rendrait toute agrégation infinie. L'unicité du code est
               une condition de rapprochement, voir `EXG-SPR-006`.
  Vérification Rattacher un sous-projet à l'un de ses descendants est refusé ;
               deux sous-projets d'un même projet ne peuvent porter le même code.
  Source       E6-01 (#62)
```

Le même code peut en revanche être réemployé librement d'un projet à l'autre :
l'unicité est bornée au projet.

### 9.2 Ce qui s'y rattache

```
EXG-SPR-003 — DOIT — Toute ligne de coût et toute affectation de rôle est
rattachée à un sous-projet. À défaut de choix explicite, elle l'est à la racine.
  Motif        Une dépense sans rattachement n'apparaît dans aucune ventilation
               et disparaît des totaux par sous-projet sans que rien ne le
               signale. Le défaut à la racine rend l'oubli impossible.
  Vérification Aucune ligne de coût ni affectation de rôle ne porte un
               rattachement vide.
  Source       E6-02 (#63)
```

```
EXG-SPR-004 — DOIT — Le rattachement est figé au moment où le devis est validé.
Un reclassement ultérieur ne réécrit pas les chiffrages déjà validés.
  Motif        Un devis validé est une référence : si une réorganisation des
               sous-projets en déplaçait rétroactivement les montants, deux
               lectures du même devis à deux dates ne donneraient pas le même
               résultat, et aucun écart ne serait explicable.
  Vérification Déplacer une ligne vers un autre sous-projet ne change aucune
               valeur d'un devis déjà validé.
  Source       E6-02 (#63)
```

```
EXG-SPR-005 — DOIT — Un sous-projet désactivé n'accepte plus aucun nouveau
rattachement, mais conserve ceux qui existent déjà.
  Motif        La désactivation ferme l'avenir sans falsifier le passé. Purger
               les rattachements existants reviendrait à effacer des dépenses
               réelles.
  Vérification Créer une ligne sur un sous-projet désactivé est refusé ; les
               lignes antérieures restent rattachées et comptées.
  Source       E6-02 (#63)
```

### 9.3 Le code est une clé de rapprochement

```
EXG-SPR-006 — DOIT — Le code d'un sous-projet est la clé par laquelle les coûts
réels importés se rattachent. Le renommer rompt ce rapprochement, et l'interface
en avertit avant de l'accepter.
  Motif        L'import résout le rattachement d'une pièce comptable en lisant le
               sous-code de son imputation analytique. Ce code vit dans le
               système comptable, hors de Waterfall : le changer ici sans le
               changer là-bas fait rejeter toutes les pièces suivantes, et le
               rejet se découvre un mois plus tard, à l'import.
  Vérification Une tentative de renommage d'un code déjà porteur de coûts réels
               affiche le nombre de pièces concernées avant confirmation.
  Source       E11 (#255), arbitrage 2026-09-12
```

### 9.4 Les lignes de coût de support s'y rattachent comme les autres

Le management, la qualité et l'assurance produit sont proportionnés à l'effort
qu'ils encadrent : leur quantité d'heures se détermine comme une part de cet
effort plutôt que par estimation directe. Cela ne change rien à leur nature — ce
sont des lignes de main-d'œuvre ordinaires, portées par des tâches comme les
autres, et rien ne les distingue ensuite (chapitres 11, 12 et 14).

Ce chapitre n'a qu'une chose à en dire.

```
EXG-SPR-011 — DOIT — Une ligne de coût de support se rattache à un sous-projet
comme n'importe quelle autre ligne, et peut se rattacher à n'importe lequel. Un
sous-projet n'ayant que des lignes de support n'est pas un objet d'une nature
différente.
  Motif        La façon dont une quantité a été déterminée ne qualifie pas le
               nœud auquel la ligne se rattache. En faire une propriété du
               sous-projet interdirait d'y mêler des lignes ordinaires, alors que
               c'est le cas courant : un sous-projet de management porte des
               lignes de support et, souvent, quelques lignes chiffrées à part.
  Vérification Un même sous-projet accepte les deux ; aucun écran ne classe les
               sous-projets en deux familles.
  Source       arbitrage 2026-09-12
```

Côté **coût réel**, rien n'est calculé : le support reçoit de vraies imputations
comptables, qu'il faut rapprocher de son budget comme celui de tout autre
sous-projet (chapitre 13).

Les quatre exigences ci-dessous plaçaient au niveau du sous-projet une
dérivation du budget qui a été écartée depuis (chapitre 23). Elles sont
retirées.

```
EXG-SPR-007 — ABANDONNÉE — retirée avec la dérivation du budget.
  Motif        Elle faisait du taux et de la base des attributs d'un sous-projet.
               Le mécanisme entier a été écarté : la quantité d'une ligne de
               support se saisit, aidée du total de sélection (`EXG-DEV-015`).
```

```
EXG-SPR-008 — ABANDONNÉE — retirée avec la dérivation du budget.
  Motif        Elle imposait un recalcul automatique du budget d'un sous-projet.
               Aucun recalcul entretenu n'est retenu : la quantité d'une ligne
               de support se saisit à la main.
```

```
EXG-SPR-009 — ABANDONNÉE — reprise par `EXG-CRE-009`.
  Motif        Son contenu reste vrai — le coût réel n'est jamais calculé — mais
               il relève du rapprochement des imputations, pas de la structure de
               ventilation.
```

```
EXG-SPR-010 — ABANDONNÉE — retirée avec la dérivation du budget.
  Motif        Elle exigeait de rendre lisibles un taux et une base qui
               n'existent plus.
```

---

## 10. Planning

**Statut : partiel.** Un point reste ouvert : le marquage des tâches d'un
avenant (question 14).

Le planning de Waterfall n'est pas un ordonnanceur. Il retient d'un planning ce
qui est nécessaire pour chiffrer et suivre, et rien de plus — le reste relève de
MS Project, dont le rôle est annexe (2.2).

### 10.1 Ce que Waterfall retient

```
EXG-PLN-001 — DOIT — D'un planning importé, Waterfall ne retient que les tâches
et les liens de précédence. Les calendriers et les ressources du fichier ne
sont jamais repris : ceux du référentiel s'y substituent. Ils peuvent être lus
pour être comparés à ce qui avait été exporté (`EXG-MSP-011`), jamais pour
alimenter le projet.
  Motif        Les calendriers et les ressources d'un fichier MS Project
               décrivent l'organisation de celui qui l'a produit, pas celle de
               Waterfall. Les reprendre ferait calculer les durées sur des jours
               ouvrés étrangers au référentiel, et les coûts sur des ressources
               que le devis n'attribue qu'après le planning. La lecture reste
               permise parce qu'elle ne sert qu'à avertir : c'est la condition
               du signalement d'`EXG-MSP-011`, qui ne peut nommer un écart sans
               l'avoir constaté.
  Vérification Après import, le calendrier appliqué est celui du référentiel, et
               aucune ressource du fichier n'apparaît dans le projet.
  Source       arbitrage produit, code existant
```

La structure de l'arbre est libre : rien n'impose qu'elle reproduise le
lotissement, ni aucun niveau nommé (`EXG-VOC-006`).

### 10.2 Les liens de précédence

Le chapitre invoque les prédécesseurs à chaque calcul de dates sans avoir dit ce
qu'un lien est.

```
EXG-PLN-028 — DOIT — Un lien de précédence relie deux tâches d'une même révision.
Il porte l'un des quatre types — fin-début, début-début, fin-fin, début-fin — et
un décalage éventuel, positif ou négatif.
  Motif        Les quatre types viennent de MS Project, et s'en tenir au seul
               fin-début obligerait à refuser ou à déformer des plannings réels
               dès le premier import. Le décalage relève de la même nécessité :
               il exprime une attente — séchage, instruction, délai de livraison
               — qu'une tâche fictive rendrait moins lisible et fausserait au
               chiffrage, puisqu'elle porterait une charge nulle. Restreindre le
               lien à une seule révision est ce qui permet à une révision d'être
               une version complète (`EXG-MOD-001`) : un lien traversant les
               versions ferait dépendre les dates d'un chiffrage validé d'un
               brouillon que quelqu'un modifie.
  Vérification Les quatre types importés d'un fichier MS Project sont conservés,
               replacés à l'export, et chacun contraint les dates selon sa
               définition ; aucun lien ne désigne une tâche d'une autre révision.
  Source       models/ms_core.py, services/planning_tree.py
```

```
EXG-PLN-029 — DOIT — Une ligne de coût n'a ni prédécesseur ni successeur.
  Motif        La précédence contraint des dates, et une ligne de coût n'en porte
               pas : elle relève de la facette de coût, non de celle de
               planification (`EXG-MOD-012`). Un lien qui la désignerait n'aurait
               rien à contraindre, et le calcul devrait le traverser sans rien en
               tirer.
  Vérification Aucun lien de précédence n'a pour extrémité un nœud portant une
               facette de coût.
  Source       revision v0.1
```

```
EXG-PLN-030 — DOIT — Le graphe des liens de précédence est sans cycle. Un lien
qui en créerait un est refusé, et le refus nomme les tâches de la boucle.
  Motif        Un cycle rend le calcul des dates insoluble : chaque tâche attend
               une tâche qui l'attend. Le moment où le lien se crée est la seule
               occasion où l'on sait quel lien est de trop ; découvert au calcul,
               il ne laisse qu'un planning entier à démêler. Nommer les tâches de
               la boucle est ce qui distingue ce refus d'une impasse.
  Vérification Créer un lien fermant une boucle est refusé et le message énumère
               les tâches concernées ; un fichier importé porteur d'un cycle est
               rejeté de la même façon.
  Source       revision v0.1
```

### 10.3 Mode manuel, mode automatique

C'est le champ que Waterfall exploite le plus, et le seul qui fasse du planning
autre chose qu'un tableau de dates.

```
EXG-PLN-002 — DOIT — Les dates d'une tâche automatique sont calculées par le
serveur. Une date de fin transmise pour une telle tâche est ignorée ; une date
de début ne sert que d'ancrage à défaut de contrainte amont.
  Motif        Le serveur ne doit jamais retourner une date incohérente avec son
               propre calcul. Accepter une fin saisie créerait une valeur que
               rien ne garantit, et que le premier recalcul contredirait.
  Vérification Une fin transmise sur une tâche automatique n'est pas conservée :
               la valeur retournée est celle recalculée depuis le début et la
               durée.
  Source       services/planning_tree.py
```

```
EXG-PLN-003 — DOIT — Une tâche automatique exige une durée strictement positive.
  Motif        Une durée nulle sur une tâche qui n'est pas un jalon est soit un
               jalon qui s'ignore, soit une saisie oubliée. Dans les deux cas le
               calcul n'a pas d'entrée.
  Vérification La modification est refusée, en nommant la durée comme cause.
  Source       services/planning_tree.py
```

```
EXG-PLN-004 — DOIT — Une tâche automatique dont aucun prédécesseur ne fournit de
contrainte, et qui ne porte pas de date de début, commence à la date de début du
projet. Elle n'est jamais refusée pour ce motif.
  Motif        C'est le comportement de MS Project, et il rend possible la façon
               dont un planning se saisit réellement : créer toutes les tâches,
               puis tous les liens, puis les durées. Exiger une date à la création
               imposerait de saisir une information qu'on ne connaît pas encore et
               qu'un lien rendra caduque. Le regroupement de tâches au début du
               projet n'est d'ailleurs pas un défaut d'affichage : c'est le signal
               visible qu'il manque des liens.
  Vérification Créer une tâche sans date ni prédécesseur la place au début du
               projet ; lui ajouter ensuite un prédécesseur la déplace.
  Source       arbitrage 2026-09-12, comportement MS Project
```

```
EXG-PLN-022 — DOIT — Une tâche créée sans durée reçoit une durée par défaut d'un
jour ouvré.
  Motif        Même raison qu'`EXG-PLN-004` : la durée se saisit en dernier. Une
               création qui exigerait la durée bloquerait la saisie en masse des
               libellés, qui est la première étape du travail réel.
  Vérification Créer une tâche sans rien saisir d'autre que son libellé aboutit,
               et la tâche porte une durée d'un jour ouvré.
  Source       arbitrage 2026-09-12, comportement MS Project
```

```
EXG-PLN-005 — DOIT — Lorsque des prédécesseurs contraignent une tâche
automatique, son début est la plus tardive de leurs contraintes.
  Motif        Une tâche ne peut commencer qu'une fois toutes ses dépendances
               satisfaites ; retenir la plus précoce en ignorerait certaines.
  Vérification Ajouter un prédécesseur plus tardif décale la tâche ; en ajouter
               un plus précoce ne la déplace pas.
  Source       services/planning_tree.py
```

```
EXG-PLN-006 — DOIT — La modification d'une tâche recalcule ses successeurs
automatiques, de proche en proche. Une tâche manuelle interrompt la propagation.
  Motif        C'est ce qui fait d'un planning autre chose qu'une liste de dates
               indépendantes. Une tâche manuelle est une décision de figer une
               date : la propager la contredirait.
  Vérification Décaler une tâche déplace ses successeurs automatiques en aval ;
               un successeur manuel reste en place, et rien ne bouge au-delà de
               lui par ce chemin.
  Source       #73, services/planning_tree.py
```

### 10.4 Récapitulatives et jalons

```
EXG-PLN-007 — DOIT — Les dates d'une tâche récapitulative dérivent de ses
enfants. Elles ne se saisissent pas et ne dépendent d'aucun lien de précédence.
  Motif        Une récapitulative ne décrit pas un travail mais l'enveloppe de
               celui de ses enfants. Lui donner des dates propres permettrait de
               la voir finir avant eux.
  Vérification Une modification directe des dates d'une récapitulative est
               refusée ; ses dates suivent celles de ses enfants.
  Source       services/planning_tree.py
```

```
EXG-PLN-008 — DOIT — Un jalon ne porte aucun enfant, quelle que soit la nature
de celui-ci : ni sous-tâche, ni ligne de coût.
  Motif        Un jalon marque un instant et n'a pas de durée. Une tâche qui
               porte des enfants tient ses dates de ceux-ci et devient de fait
               une récapitulative : les deux natures s'excluent. La règle ignore
               la nature de l'enfant parce que c'est le jalon qui l'interdit, et
               non ce qu'on tente d'y placer : un jalon porteur de lignes de coût
               serait une tâche chiffrée sans durée, donc un budget qu'aucun
               avancement ne pourrait consommer.
  Vérification Placer un nœud sous un jalon est refusé, qu'il porte une facette
               de planification ou une facette de coût ; marquer comme jalon une
               tâche qui porte déjà des enfants l'est aussi.
  Source       services/planning_tree.py, E14
```

Cette règle est un invariant du modèle : elle est vérifiée par le contrôle
d'invariants, au même titre que l'acyclicité de l'arbre.

Elle mord le plus discrètement à la **désindentation**. Désindenter un nœud le
rend parent des frères qui le suivaient (`EXG-PLN-027`) : désindenter un jalon
suivi d'au moins un frère est donc refusé, alors même que l'utilisateur n'a
désigné aucun parent et ne voit pas de rattachement dans son geste. Le refus
nomme la règle (`EXG-PLN-017`), sans quoi il serait incompréhensible.

```
EXG-PLN-025 — DOIT — Une tâche porte toujours un début, une fin et une durée.
La création les fournit, et aucune commande ne permet de les vider.
  Motif        Une tâche sans dates n'apparaît sur aucun calendrier, échappe au
               plan de charge, et ses heures ne produisent aucune ligne de coût —
               elles manquent donc au budget de référence, qui est le
               dénominateur de tout l'avancement physique. Le défaut est
               silencieux et coûteux ; il est plus simple de rendre l'état
               inatteignable que d'en traiter les conséquences partout.
  Vérification Aucun écran ni endpoint n'accepte de vider une date ou une durée ;
               toute tâche importée ou créée en porte.
  Source       arbitrage 2026-09-13
```

Cette garantie ne coûte rien à l'import : sur six exports MS Project réels
totalisant deux mille six cent soixante-six tâches, aucune ne manque de début, de
fin, de durée ni d'indicateur de mode. La règle « tâche sans dates » du panneau
ci-dessous devient donc un contrôle défensif, qui ne devrait jamais rien trouver.

### 10.5 Le panneau de contrôle

Pendant la saisie, ce qu'on cherche dans un planning, ce sont des anomalies —
typiquement une tâche sans prédécesseur. C'est un besoin de **contrôle**, pas de
visualisation : une condition testable ne se devine pas sur une image.

```
EXG-PLN-009 — DOIT — L'onglet Planning porte un panneau listant les anomalies
avec leur compte. Cliquer une anomalie filtre la table sur les tâches
concernées.
  Motif        Un compte sans accès aux lignes concernées oblige à les chercher à
               la main, et on renonce. Le filtre est ce qui rend le panneau
               utilisable.
  Vérification Chaque règle affiche son nombre d'occurrences et filtre la table
               au clic.
  Source       maquette
```

```
EXG-PLN-010 — DOIT — Les règles de contrôle ne portent que sur ce que le
planning contient : structure, dates, durées, mode et liens. Jamais sur un rôle
ni sur un coût.
  Motif        Les rôles et les coûts sont attribués par le devis, qui vient
               après le planning dans le flux. Signaler une tâche « sans rôle »
               pendant la saisie du planning reprocherait à l'utilisateur de ne
               pas avoir fait une étape ultérieure.
  Vérification Aucune règle de contrôle ne lit une affectation de rôle ni un
               montant.
  Source       arbitrage produit
```

Les règles retenues, et leur gravité :

| Règle | Gravité | Ce qu'elle signale |
|---|---|---|
| Tâche sans prédécesseur | vigilance | Sa date ne dépend de rien : un décalage amont ne la déplacera pas, et elle reste calée au début du projet. |
| Tâche sans dates | anomalie | Elle n'apparaît sur aucun calendrier et échappe à toute agrégation. |
| Durée nulle hors jalon | anomalie | Soit un jalon qui s'ignore, soit une saisie oubliée. |
| Jalon daté avant son prédécesseur | anomalie | Le jalon serait atteint avant la fin du travail qui le conditionne. |

La règle sur la durée n'est pas inventée : elle énonce avant la saisie le cas
qu'`EXG-PLN-003` fait refuser pendant. Celle du prédécesseur manquant est d'une
autre nature — rien n'est refusé, et c'est justement pourquoi elle mérite d'être
comptée : une tâche sans lien reste au début du projet, indéfiniment, sans que
rien ne proteste.

### 10.6 La disposition de l'onglet

```
EXG-PLN-011 — DOIT — L'onglet présente, de haut en bas : la chronologie, la
table, puis le panneau de contrôle.
  Motif        La table est l'objet de travail ; tout ce qui la précède la
               repousse vers le bas. Le panneau de contrôle se consulte par
               intermittence et vit donc sous elle, où sa hauteur ne coûte rien.
  Vérification La table est visible sans défilement à l'ouverture de l'onglet.
  Source       arbitrage maquette
```

```
EXG-PLN-012 — DOIT — Le diagramme de Gantt ne vit pas dans cet onglet.
  Motif        Il occuperait la moitié de la largeur pour un besoin que le
               panneau de contrôle sert mieux et pour presque rien. Son second
               usage, l'analyse d'ensemble, relève de l'onglet Analyse, en pleine
               largeur.
  Vérification Aucun Gantt n'est rendu dans l'onglet Planning.
  Source       arbitrage maquette
```

### 10.7 La table

La table est le poste de travail du chapitre : c'est là que le planning se
construit, et sa qualité d'usage conditionne tout le reste. Elle n'est pas une
grille de lecture à laquelle on aurait ajouté l'édition.

```
EXG-PLN-014 — DOIT — La table rend l'arbre des tâches : chaque nœud se plie et
se déplie, s'indente et se désindente, et la largeur de chaque colonne est
ajustable par l'utilisateur.
  Motif        Un planning de plusieurs centaines de tâches ne se lit qu'en
               repliant ce qu'on n'examine pas. L'indentation est le geste par
               lequel la structure se construit, pas un attribut qu'on saisirait
               dans un champ.
  Vérification Replier un nœud masque ses descendants sans les déplacer ;
               indenter une tâche la rattache au frère qui la précède.
  Source       code existant
```

```
EXG-PLN-015 — DOIT — Plusieurs tâches se sélectionnent à la fois, contiguës ou
non. Une sélection contenant un ancêtre et ses descendants se réduit à
l'ancêtre, dont les descendants suivent implicitement.
  Motif        Sans cette réduction, déplacer un parent et un enfant
               simultanément demanderait de placer l'enfant deux fois — une fois
               avec son parent, une fois pour lui-même — et le résultat
               dépendrait de l'ordre de traitement.
  Vérification Sélectionner un parent et l'un de ses enfants, puis déplacer,
               produit le même arbre que sélectionner le parent seul.
  Source       code existant
```

```
EXG-PLN-016 — DOIT — Indenter, désindenter, réordonner et coller après une
coupe sont **le même déplacement** : ils produisent la même commande et sont
soumis aux mêmes invariants.
  Motif        Quatre gestes qui aboutissent au même effet doivent emprunter le
               même chemin, sinon trois d'entre eux finissent par accepter ce que
               le quatrième refuse. C'est ainsi qu'un arbre devient incohérent
               sans qu'aucune règle n'ait été violée explicitement.
  Vérification Les quatre gestes refusent tous de placer un nœud sous lui-même,
               sous l'un de ses descendants, ou sous un jalon (`EXG-PLN-008`).
  Source       code existant, arbitrage 2026-09-12
```

```
EXG-PLN-017 — DOIT — Un refus de déplacement nomme la règle enfreinte et la
tâche en cause.
  Motif        Sur une sélection de plusieurs dizaines de lignes, un refus global
               sans désignation oblige à chercher le coupable à la main, et le
               geste est abandonné.
  Vérification Coller une sélection sous un jalon affiche la règle et le nom de
               la tâche cible.
  Source       arbitrage 2026-09-12
```

```
EXG-PLN-018 — DOIT — Couper puis coller déplace les tâches. Copier puis coller
crée de nouvelles tâches, portant de nouvelles identités.
  Motif        Un déplacement conserve l'identité d'un élément de travail — donc
               son histoire à travers les versions (`EXG-VOC-008`) — tandis
               qu'une copie crée un travail qui n'existait pas. Les confondre
               ferait apparaître la même identité à deux endroits de l'arbre, ce
               qu'aucune agrégation ne saurait interpréter.
  Vérification Après un couper-coller, le nombre de tâches est inchangé ; après
               un copier-coller, il augmente, et les tâches créées ont des
               identités distinctes de leurs sources.
  Source       arbitrage 2026-09-12
```

```
EXG-PLN-031 — DOIT — Copier une tâche emporte **tout son sous-arbre** : ses
sous-tâches et ses lignes de coût, avec leurs quantités, leurs heures et leurs
montants. Chaque nœud créé reçoit une identité nouvelle (`EXG-PLN-018`).
  Motif        C'est la raison d'être de la commande. Dupliquer un lot de travail
               récurrent — une campagne d'essais, une phase de qualification qui
               se répète d'un équipement à l'autre — suppose d'en rapporter le
               chiffrage : sans lui, il faudrait ressaisir ligne à ligne ce qu'on
               vient de copier, et la copie ne ferait gagner que l'arborescence,
               c'est-à-dire la partie la moins coûteuse à refaire.

               Le risque symétrique — un doublement silencieux du chiffrage —
               est réel, mais il ne justifie pas de vider la commande de son
               contenu. Il est traité là où il se voit : le montant du projet et
               celui de chaque sous-projet sont affichés en permanence au-dessus
               de la grille (`EXG-DEV-017`), et un collage qui double un budget
               s'y lit dans l'instant.

               Rien de particulier n'est à écrire sur les lignes de coût : elles
               sont des nœuds de l'arbre au même titre que les tâches
               (`EXG-MOD-012`), donc des descendants de la tâche copiée.
               Emporter le sous-arbre les emporte.
  Vérification Copier une tâche portant deux sous-tâches et trois lignes de coût,
               puis coller, ajoute six nœuds aux identités distinctes de leurs
               sources, et augmente le montant **hors inflation** du projet de
               celui du sous-arbre copié. Le montant corrigé, lui, dépend des
               dates de la tâche d'accueil (`EXG-DEV-019`) et ne se conserve pas
               par un collage ailleurs dans le temps.
  Source       arbitrage 2026-09-15
```

```
EXG-PLN-019 — DOIT — La table tient un historique d'au moins dix actions,
annulables et rétablissables dans l'ordre.
  Motif        Déplacer quarante tâches tient en une frappe ; les remettre en
               place à la main n'a pas d'équivalent. Sans annulation, le geste
               existe mais personne ne l'emploie, et la sélection multiple perd
               sa raison d'être. Dix actions, parce qu'une erreur de structure ne
               se voit qu'après deux ou trois gestes de plus — annuler le seul
               dernier arrive trop tard.
  Vérification Après un déplacement, l'annulation restitue l'arbre dans son état
               antérieur, ordre des frères compris, et le rétablissement le
               ramène. Dix actions successives sont annulables une à une.
  Source       arbitrage 2026-09-12
```

Deux précisions, sans lesquelles cette exigence serait sous-spécifiée au point
d'être livrée fausse.

**L'annulation restitue aussi les dates.** Une modification d'horaire se propage
aux successeurs automatiques (`EXG-PLN-006`) : l'annuler suppose de rendre à
chacun d'eux la date qu'il portait, pas seulement à la tâche éditée. Une
annulation qui ne défait que le geste visible laisse un planning faux.

**L'historique ne survit pas à une écriture concurrente.** Si la révision a été
modifiée ailleurs entre-temps, l'historique est abandonné plutôt que rejoué :
rétablir un état ancien par-dessus le travail d'un autre serait pire que ne rien
annuler du tout.

```
EXG-PLN-020 — DOIT — Une chronologie est une composition nommée : un sous-ensemble
de tâches choisi à la main depuis la table. Elle appartient à la révision, qui en
porte plusieurs et en affiche une à la fois.
  Motif        L'intérêt n'est pas d'avoir une chronologie, c'est d'avoir
               plusieurs vues du même planning — une pour la direction, une par
               sous-projet, une par échéance contractuelle. Un attribut unique par
               tâche n'en autorise qu'une, et condamne à recomposer à chaque fois
               qu'on change de lecteur. Le rattachement à la révision garantit par
               construction que la composition ne désigne que des tâches qui
               existent.
  Vérification Créer une seconde chronologie ne modifie pas la première ; les
               deux restent disponibles et se choisissent à l'affichage.
  Source       arbitrage 2026-09-12
```

En pratique une chronologie ne retient que des tâches récapitulatives et des
jalons. C'est une observation d'usage, **pas une contrainte** : rien n'interdit
d'y placer une tâche feuille. Mais elle explique pourquoi composer à la main est
raisonnable — une chronologie compte quelques lignes, pas quelques centaines.

```
EXG-PLN-023 — DOIT — Supprimer une tâche la retire des chronologies de sa
révision et de ses jalons suivis. Aucune composition ne désigne une tâche qui
n'existe plus.
  Motif        C'est le corollaire du rattachement à la révision : la cohérence
               entre une composition et l'arbre est garantie par construction, à
               condition que la suppression d'une tâche y soit propagée. Une
               référence orpheline ferait échouer le dessin, ou pire, le ferait
               échouer silencieusement.
  Vérification Supprimer une tâche figurant dans deux chronologies la retire des
               deux, sans les vider ni les supprimer ; supprimer un jalon suivi
               le retire du diagramme de dérive.
  Source       arbitrage 2026-09-12
```

```
EXG-PLN-024 — DOIT — Créer une révision y recopie les chronologies et
l'ensemble des jalons suivis de celle dont elle est issue, amputés des tâches
qu'elle ne reprend pas. Les copies sont indépendantes : modifier une chronologie
ou l'ensemble des jalons suivis ne touche pas ceux des autres révisions.
  Motif        C'est ce qui rend le rattachement à la révision tenable. Sans
               report, une composition faite à la main serait à refaire à chaque
               revue mensuelle — et ne serait refaite qu'une fois. Avec un report
               par copie, le travail se conserve tout en laissant chaque révision
               afficher la vue qui lui correspond, ce qui est la condition pour
               comparer deux révisions sur la même sélection de tâches. Le
               report vaut a fortiori pour les jalons suivis : le diagramme de
               dérive porte un point par revue (`EXG-ANA-017`), et un ensemble
               non reporté le ramènerait à un point unique à chaque révision,
               c'est-à-dire à rien.
  Vérification Une révision issue d'une autre présente les mêmes chronologies et
               les mêmes jalons suivis ; en renommer une ne renomme pas son
               homologue dans la révision d'origine.
  Source       arbitrage 2026-09-12
```

```
EXG-PLN-027 — DOIT — Désindenter une sélection ne change que son niveau : la
suite des lignes affichées reste exactement celle que l'utilisateur avait sous
les yeux. La commande porte sur un bloc contigu de frères.
  Motif        C'est la sémantique de MS Project, d'où viennent les utilisateurs
               de ce produit. Une désindentation qui réordonne des lignes qu'ils
               n'ont pas sélectionnées y serait perçue comme un défaut, non comme
               une variante défendable. Le rattachement des frères suivants au
               dernier nœud désindenté en découle : c'est la seule façon de leur
               conserver leur rang.
  Vérification Sur un parent portant trois enfants, désindenter le deuxième
               laisse les quatre lignes dans le même ordre qu'avant.
  Source       E14 (#326)
```

Une désindentation déplace donc des lignes de coût que l'utilisateur n'a pas
sélectionnées, puisqu'un nœud emporte sa facette. Leur montant et leur imputation
sont inchangés ; seule leur tâche porteuse change, et elle n'est jamais mémorisée
(`EXG-DEV-002`).

```
EXG-PLN-026 — DOIT — La table permet de suivre un jalon au diagramme de dérive
et de cesser de le suivre. Les jalons suivis forment un ensemble unique par
révision, distinct des chronologies : le geste se fait au même endroit, la cible
n'est pas la même.
  Motif        Un planning réel porte des centaines de jalons — quatre cent
               dix-huit sur les deux mille six cent soixante-six tâches mesurées.
               Les tracer tous rendrait le diagramme illisible ; en choisir
               quelques-uns est le geste qui le rend utile. Il se fait là où on
               voit les jalons dans leur contexte, c'est-à-dire dans la table, et
               non dans une liste détachée de l'arbre. L'ensemble est unique
               parce que le diagramme l'est : une chronologie s'affiche au choix
               parmi plusieurs (`EXG-PLN-020`), le diagramme de dérive n'a pas
               d'équivalent entre lequel choisir.
  Vérification Un jalon suivi depuis la table apparaît au diagramme de dérive ;
               cesser de le suivre l'en retire sans effacer les points déjà
               relevés des autres. Composer une chronologie ne modifie pas
               l'ensemble des jalons suivis.
  Source       arbitrage 2026-09-13
```

```
EXG-PLN-013 — DOIT — La table n'essaie pas de tout afficher. Elle propose des
jeux de colonnes enregistrés, fige ses premières colonnes et fait défiler le
reste horizontalement.
  Motif        Les colonnes utiles à la saisie, au contrôle et à l'export ne sont
               pas les mêmes. Les réunir toutes rend chacune trop étroite ;
               choisir un sous-ensemble unique en prive quelqu'un.
  Vérification Changer de jeu de colonnes ne fait pas défiler la table
               horizontalement, et les colonnes figées restent visibles pendant
               le défilement.
  Source       maquette
```

Les colonnes en vigueur sont : l'identifiant positionnel (5.7), le nom, le
type, le début, la fin, la durée, le mode et les prédécesseurs. La colonne
d'identifiant est celle du rang d'affichage, et non l'uid MS Project, qui ne
sort pas de l'import et de l'export (`EXG-VOC-008`).

```
EXG-PLN-021 — DOIT — Tout ce que la souris permet sur la table, le clavier le
permet aussi : sélection, pliage, indentation, déplacement, annulation.
  Motif        La saisie d'un planning est un travail de volume. Quiconque en
               saisit plusieurs centaines de lignes quitte la souris, et une
               commande qui n'existe qu'au pointeur n'est pas employée.
  Vérification Chaque commande de cette section est atteignable au clavier, et
               le raccourci est affiché à côté de son équivalent pointé.
  Source       arbitrage 2026-09-12
```

### 10.8 Ce qui reste ouvert

**Le marquage des tâches d'un avenant** (question 14). Si la piste retenue est de
créer les tâches d'un avenant dans le planning général en les marquant, ce
marquage est un attribut de tâche, et son filtrage une fonction de cette table.

---

## 11. Devis

**Statut : partiel.** Un point reste ouvert : les provisions pour risques
(question 2).

Le devis chiffre le planning. Il n'invente pas sa propre structure : il reprend
l'arbre des tâches et y accroche des lignes de coût. Cette dépendance est le
fait central du chapitre — un devis sans planning n'a rien à chiffrer, et un
planning sans devis ne produit aucun budget.

### 11.1 Ce qu'un devis chiffre

```
EXG-DEV-001 — DOIT — Une tâche de planning et une ligne de coût sont deux objets
distincts, même lorsqu'une même grille les affiche l'un sous l'autre.
  Motif        Une tâche porte des dates et une structure ; une ligne porte un
               montant. Les fondre ferait d'un chiffrage une propriété de la
               tâche, et interdirait qu'une même tâche reçoive plusieurs rôles,
               plusieurs fournitures, ou aucun coût du tout.
  Vérification Supprimer une ligne de coût ne supprime pas sa tâche ; une tâche
               peut porter zéro, une ou plusieurs lignes.
  Source       devis v0.1
```

```
EXG-DEV-002 — DOIT — Une ligne de coût est portée par la tâche la plus proche
au-dessus d'elle dans l'arbre. Une ligne placée à la racine est un coût global du
projet, sans tâche porteuse.
  Motif        Les frais d'assurance, les déplacements ou les indemnités ne se
               rattachent à aucune tâche, et les forcer sous une tâche arbitraire
               fausserait la valeur acquise de celle-ci. L'ancêtre le plus proche
               est déduit de la position, non stocké sur la ligne : une ligne
               déplacée change donc de porteuse sans réécriture.
  Vérification Une ligne à la racine est comptée dans le budget du projet et dans
               aucune tâche ; déplacer une ligne sous une autre tâche change sa
               porteuse.
  Source       devis v0.1, E14 (#326)
```

### 11.2 Les natures de ligne

Quatre natures, et le référentiel de types reste extensible :
**main-d'œuvre**, **fourniture**, **frais**, **unité d'œuvre**.

```
EXG-DEV-003 — DOIT — Le coût d'une ligne de main-d'œuvre est le produit de sa
quantité, de ses heures et du taux horaire applicable. Celui d'une ligne non
main-d'œuvre est le produit de sa quantité et de son débours unitaire.
  Motif        Deux formules seulement, et aucune saisie de montant final : un
               total saisi à la main ne se recalcule pas quand un taux change, et
               diverge sans que rien ne le signale.
  Vérification Aucun écran ne permet de saisir directement le montant d'une
               ligne ; il est toujours calculé depuis ses facteurs.
  Source       devis v0.1
```

```
EXG-DEV-004 — DOIT — Le taux horaire d'une ligne de main-d'œuvre vient de la
catégorie de coût du rôle affecté. Il n'est jamais saisi sur la ligne.
  Motif        Le taux est une donnée de référentiel, partagée par tous les
               projets. Saisi ligne à ligne, il autoriserait deux chiffrages du
               même rôle à des taux différents, et rendrait toute comparaison
               entre projets arbitraire.
  Vérification Changer le rôle d'une ligne change son taux ; aucun champ de
               saisie de taux n'existe sur la ligne.
  Source       devis v0.1
```

### 11.3 Taux, année de référence et inflation

C'est le point du chapitre où une erreur coûte le plus cher, parce qu'elle ne se
voit pas : un budget faux reste un nombre plausible.

```
EXG-DEV-005 — DOIT — L'**année de référence** d'un chiffrage est son année de
création. Il emploie les taux horaires de cette année, et le coefficient
d'inflation appliqué à un montant est l'inflation **cumulée** de l'année de
référence jusqu'à l'année où ce montant sera consommé. La règle vaut pour
**toute nature de ligne** : une fourniture, un frais ou une prestation
sous-traitée subissent l'inflation au même titre qu'une charge de main-d'œuvre.
  Motif        Les taux des années futures ne sont pas connus, et ne le seront
               pas : personne ne les saisira. C'est le rôle de l'inflation que de
               projeter un taux connu. Le cumul n'est pas un détail : un montant
               consommé deux ans après le chiffrage subit l'inflation des deux
               années, et n'appliquer que celle de l'année d'arrivée sous-évalue
               le budget d'autant plus que le projet est long.

               L'extension aux débours n'est pas une symétrie de principe : un
               prix d'achat monte comme un salaire, et exonérer les fournitures
               sous-évaluerait d'autant les projets où elles pèsent le plus —
               ceux dont l'essentiel du budget n'est pas de la main-d'œuvre.
  Vérification Un devis créé en 2026 chiffre une charge de 2027 au taux 2026
               majoré d'une année d'inflation, et une charge de 2028 au même taux
               majoré de deux années. Aucun taux d'année future n'est réclamé. Un
               débours consommé en 2028 est majoré des deux mêmes années.
  Source       arbitrage 2026-09-12, issue #323
```

Le cumul est une propriété du **résultat**, pas de la forme de stockage : un
coefficient annuel composé d'année en année et un indice absolu rapporté à
l'année de référence satisfont tous deux cette exigence. Le choix relève du
chapitre 21.

L'année de référence étant celle de la création, chaque revue mensuelle du
premier mois d'une année nouvelle en produit une nouvelle — dont les taux sont
cette fois connus. C'est exactement la **réconciliation annuelle** du chapitre
12 : la même règle, vue depuis l'autre bout.

```
EXG-DEV-020 — DOIT — L'inflation est un **coefficient unique porté par le
projet**. Il s'applique à chaque année postérieure à l'année de référence du
chiffrage, composé autant de fois qu'il y a d'années écoulées.
  Motif        Le porter au projet est la seule façon d'avoir des hypothèses par
               affaire : deux projets chiffrés à deux ans d'écart n'ont ni la
               même année de référence ni les mêmes perspectives, et certains
               marchés portent leur propre clause d'indexation. Un paramètre
               commun à l'installation interdirait de les distinguer, et sa
               modification déplacerait le budget de tous les projets en cours.

               Un coefficient et non une série : une prévision d'inflation année
               par année sur dix ans serait une donnée que personne ne tient à
               jour, et dont la précision apparente masquerait qu'elle est une
               hypothèse unique. Un seul nombre se saisit, se discute et se
               défend.
  Vérification Le projet porte un coefficient et un seul ; une charge consommée
               deux ans après l'année de référence est majorée de ce coefficient
               appliqué deux fois. Modifier le coefficient d'un projet ne change
               aucun montant d'un autre projet.
  Source       arbitrage 2026-09-14
```

```
EXG-DEV-014 — DOIT — La grille affiche pour chaque ligne le montant **hors
inflation** et le montant **corrigé**. Le montant hors inflation est calculé au
taux de l'année de référence, sans inflation et **sans répartition** sur les
années de consommation. Les deux sont produits par le moteur de calcul et
jamais recalculés par la grille.
  Motif        L'inflation est appliquée sans que rien ne le montre, sur des
               années que l'utilisateur n'a pas saisies. Un seul montant à
               l'écran rend l'écart invisible : personne ne peut vérifier ni
               contester une majoration qu'il ne voit pas. Les deux côte à côte
               font de l'inflation une information plutôt qu'un effet de bord.

               La définition du montant hors inflation n'est pas un détail de
               présentation : sans répartition, il ne dépend que de la ligne,
               tandis que le montant corrigé dépend aussi de ce qui la porte —
               sa tâche, ou le projet lorsqu'elle est à la racine. C'est leur
               écart qui rend visible l'effet décrit plus bas.
               Et les deux viennent du moteur parce qu'une grille qui
               réimplémenterait le calcul en produirait une approximation
               divergente, sans que rien ne le signale.
  Vérification Une ligne consommée l'année de référence affiche deux montants
               égaux ; une ligne consommée deux ans plus tard affiche l'écart
               correspondant au cumul. Aucun des deux montants n'est calculé par
               l'interface.
  Source       arbitrage 2026-09-12, précisé le 2026-09-14 (#390)
```

```
EXG-DEV-019 — DOIT — Un débours est consommé en **une seule** année : celle du
début de sa tâche porteuse. Un débours placé à la racine, qui n'a pas de tâche
porteuse (`EXG-DEV-002`), est consommé l'année du **début du projet**.
  Motif        Un débours est un montant ponctuel, non un effort étalé : il n'y a
               rien à répartir. Sous une tâche, l'année de début de la porteuse
               est retenue parce qu'elle est toujours définie et parce qu'elle
               rend le traitement homogène avec la main-d'œuvre, qui tire ses
               années de la même tâche. **À la racine, cette homogénéité cesse, et
               c'est voulu** : une ligne de main-d'œuvre s'y étale sur toutes les
               années du projet (`EXG-DEV-022`), un débours n'en prend qu'une. Un
               projet qui s'allonge coûte plus cher en encadrement ; un engagement
               de fourniture n'a pas de raison de croître parce que le planning se
               décale. L'année du début du projet est retenue plutôt que l'année en
               cours, qui ferait changer tout seul, au passage du premier janvier,
               le montant d'un brouillon que personne n'a touché. La **date
               prévisionnelle de décaissement** (`EXG-MOD-021`) n'est délibérément
               **pas** lue : elle existe pour situer une dépense dans le temps, non
               pour la valoriser, et elle est facultative — la valorisation d'un
               budget ne peut pas dépendre d'un champ qu'on a le droit de laisser
               vide.
  Vérification Déplacer une ligne de fourniture sous une tâche commençant une
               année plus tard change son montant corrigé d'une application
               supplémentaire du coefficient ; renseigner ou vider sa date de
               décaissement ne le change pas. Le montant d'une ligne de frais
               laissée à la racine est le même avant et après le passage d'une
               année civile.
  Source       arbitrage 2026-09-14, issue #390 ; racine précisée le 2026-09-16
```

```
EXG-DEV-021 — DOIT — Les **années du projet** sont celles que couvre l'intervalle
allant de la plus antérieure à la plus tardive des **dates de planification**
portées par une révision. L'**année de début du projet** est la première d'entre
elles. Ni l'une ni l'autre ne se saisit. Une révision qui ne porte aucune tâche
n'a pas d'années du projet : ses lignes de racine sont valorisées à l'année de
référence du chiffrage (`EXG-DEV-005`).
  Motif        Deux exigences de valorisation s'appuient sur ces années et aucune
               ne les définissait. Les déduire plutôt que les stocker évite qu'un
               projet porte une date de début déclarée que son propre planning
               contredit, et fait lire au chiffrage les mêmes dates qu'à la table
               de planning.

               **Seules les dates de planification comptent.** Une ligne de coût
               est un nœud de la révision au même titre qu'une tâche, et elle peut
               porter une date prévisionnelle de décaissement (`EXG-MOD-021`).
               Comptée ici, l'échéance d'une fourniture allongerait le projet de
               plusieurs années et majorerait toutes les lignes de racine — alors
               que c'est la date même qu'`EXG-DEV-019` refuse de lire pour
               valoriser.

               La grandeur se calcule **révision par révision**, et son nom la
               rapporte au projet parce qu'une révision en est une version
               complète (`EXG-MOD-001`). Un brouillon qui repousse une tâche de
               deux ans change ses propres montants de racine, jamais ceux d'une
               révision validée, qui n'accepte aucune écriture (`EXG-MOD-005`).

               Le repli sur l'année de référence ne concerne qu'un cas : le
               premier brouillon d'un chiffrage, où une ligne est posée à la
               racine avant la première tâche. Une révision de revue n'y tombe
               jamais, descendant d'une référence qui porte au moins une tâche
               (`EXG-CYC-004`).
  Vérification Ajouter une tâche commençant avant toutes les autres recule
               l'année de début du projet ; en ajouter une finissant après toutes
               les autres ajoute une année au prorata d'`EXG-DEV-022`. Renseigner
               sur une ligne une date prévisionnelle de décaissement postérieure à
               la dernière tâche ne déplace aucune des deux bornes.
  Source       arbitrage 2026-09-16
```

```
EXG-DEV-022 — DOIT — Une ligne de main-d'œuvre placée à la racine, qui n'a pas de
tâche porteuse (`EXG-DEV-002`), répartit ses heures sur **les années du projet**,
selon la même règle de prorata qu'une ligne portée par une tâche
(`EXG-DEV-006`).
  Motif        La main-d'œuvre et le débours ne réagissent pas de la même façon à
               un projet qui s'allonge, et la racine doit le refléter plutôt que
               de les traiter pareil. Une durée plus longue coûte plus cher en
               main-d'œuvre : l'encadrement et la coordination se paient au temps
               écoulé. Un engagement de fourniture ou de sous-traitance n'a pas de
               raison de croître parce que le planning se décale, d'où l'année
               unique d'`EXG-DEV-019`. Accrocher une ligne à la racine plutôt qu'à
               la tâche qu'elle sert reste une mauvaise pratique de chiffrage ;
               le produit en tire la conséquence arithmétique, il ne la corrige
               pas.
  Vérification Une ligne de main-d'œuvre à la racine d'un projet de sept ans
               étale ses heures sur sept années ; allonger le projet d'un an **en
               repoussant sa dernière date** augmente son montant corrigé, là où
               celui d'un débours placé à la même racine ne change pas.
  Source       arbitrage 2026-09-16
```

```
EXG-DEV-006 — DOIT — Les heures d'une ligne dont la tâche chevauche plusieurs
années sont réparties **au prorata du temps** passé dans chacune, et cette règle
est énoncée dans le résultat du calcul.
  Motif        Une interpolation linéaire, et non un partage à parts égales entre
               les années traversées : une tâche allant du 20 décembre au
               10 janvier est à quatre-vingt-quinze pour cent sur la première
               année, et la partager en deux lui appliquerait la moitié d'une
               inflation qu'elle ne subit presque pas. La règle elle-même reste
               une convention, pas une mesure — non écrite à côté du chiffre,
               elle se prend pour une observation que personne ne conteste.
  Vérification Une tâche du 20 décembre au 10 janvier impute l'essentiel de ses
               heures à la première année ; le détail de la ligne montre la part
               de chaque année et nomme la règle employée.
  Source       devis v0.1, arbitrage 2026-09-12
```

**Ce que la position d'une ligne dans l'arbre change à son montant.** Une ligne
de main-d'œuvre tire ses années de sa tâche porteuse, c'est-à-dire du premier
ancêtre portant une facette de planification (`EXG-DEV-002`). Accrochée à une
tâche de trois mois, elle est valorisée sur une seule année ; accrochée à une
récapitulative courant sur sept ans, ses heures s'étalent sur sept années et
subissent jusqu'à sept applications du coefficient ; laissée à la racine, sur
toutes les années du projet (`EXG-DEV-022`). **Plus on accroche haut dans
l'arbre, plus le coût se dilue dans le temps** — et plus il augmente, l'inflation
étant cumulative. Un débours ne suit pas cette gradation (`EXG-DEV-019`).

La gradation n'est pas un défaut : c'est la conséquence exacte de la règle de la
tâche porteuse, et déplacer une ligne est un geste délibéré. Ce que le motif
d'`EXG-DEV-022` déconseille est autre chose — laisser une ligne à la racine
plutôt que de l'accrocher à la tâche qu'elle sert, qui est un défaut de chiffrage
et non un effet de la règle. Mais l'effet est invisible
à la saisie, et c'est ce que les deux montants d'`EXG-DEV-014` rendent lisibles :
le montant hors inflation ne bouge pas quand la ligne change de porteuse, le
montant corrigé si.

### 11.4 Les lignes de coût de support

Le management, la qualité et l'assurance produit se chiffrent comme une part de
l'effort qu'ils encadrent. Ce sont des lignes de main-d'œuvre ordinaires — rôle,
taux, inflation, tout s'y applique normalement. Seule leur **quantité d'heures**
se détermine autrement.

Ce qui manque pour les chiffrer n'est pas un mécanisme : c'est un nombre. Pour
appliquer dix ou quinze pour cent à ce qu'on encadre, il faut la somme de ce
qu'on encadre ; le pourcentage, lui, se calcule de tête.

```
EXG-DEV-015 — DOIT — La table totalise en permanence les colonnes additionnables
des lignes sélectionnées — heures et montants — et le total suit la sélection.
  Motif        C'est ce qui rend les lignes de support ordinaires plutôt
               qu'exceptionnelles. Le total de sélection ne leur est d'ailleurs
               pas propre : c'est l'outil qu'on emploie dans un tableur pour
               n'importe quelle vérification, et il sert partout ailleurs dans la
               grille. Il ne coûte presque rien — la sélection multiple existe
               (`EXG-PLN-015`), les récapitulatives totalisent déjà, et le socle
               d'arbre est partagé avec le planning (`EXG-NAV-010`) — le total de
               sélection est un comportement de ce socle, donc offert des deux
               côtés sans être écrit deux fois.
  Vérification Sélectionner plusieurs lignes affiche la somme de leurs heures et
               de leurs montants ; modifier la sélection met le total à jour.
  Source       arbitrage 2026-09-13
```

Les deux exigences ci-dessous décrivaient un assistant dédié — sélectionner un
ensemble, saisir un pourcentage, laisser l'outil reporter les heures. Il est sans
objet : le total de sélection donne la seule chose qui manquait.

```
EXG-DEV-007 — ABANDONNÉE — remplacée par `EXG-DEV-015`.
  Motif        Elle décrivait un assistant appliquant un pourcentage à un
               ensemble de lignes. Afficher le total de la sélection suffit, et
               évite d'inventer un mécanisme propre aux lignes de support.
```

```
EXG-DEV-008 — ABANDONNÉE — sans objet avec `EXG-DEV-007`.
  Motif        Le mémo de calcul ne conservait que les paramètres d'un assistant
               qui n'existe plus.
```

### 11.5 Validation et immuabilité

```
EXG-DEV-009 — DOIT — Un devis est modifiable tant qu'il est en brouillon. Une
fois validé, il ne change plus.
  Motif        Un devis validé sert de référence à des écarts : s'il pouvait
               bouger, deux lectures du même écart à deux dates différeraient sans
               que rien ne l'explique.
  Vérification Toute écriture sur un devis validé est refusée, quel que soit le
               point d'entrée.
  Source       devis v0.1, code existant
```

```
EXG-DEV-010 — DOIT — La validation fige sur chaque ligne un instantané de ce qui
a servi à la calculer : code comptable, libellés, taux horaire, coefficient
d'inflation et rattachement au sous-projet.
  Motif        Sans instantané, modifier un taux du référentiel réécrirait
               rétroactivement des devis validés des années plus tôt. Le
               référentiel décrit le présent ; un devis validé décrit une
               décision passée.
  Vérification Modifier un taux du référentiel ne change aucune valeur d'un devis
               validé.
  Source       devis v0.1, E6-02 (#63)
```

```
EXG-DEV-011 — DOIT — Une catégorie de coût employée par un devis n'est jamais
supprimée ; elle est désactivée. Une catégorie désactivée n'accepte plus de
nouvelle ligne mais reste lisible sur les lignes existantes.
  Motif        Même raison qu'`EXG-SPR-005` : fermer l'avenir sans falsifier le
               passé.
  Vérification Désactiver une catégorie n'altère aucun devis existant, et la
               rend indisponible à la saisie.
  Source       devis v0.1
```

```
EXG-DEV-012 — DOIT — Le devis désigné comme référence du projet fournit le
budget de référence. Il n'y en a qu'un à la fois.
  Motif        Toutes les grandeurs de la valeur acquise se mesurent contre lui
               (5.2). Deux références simultanées produiraient deux jeux
               d'indicateurs également défendables.
  Vérification Un projet piloté expose exactement un budget de référence, celui
               du devis désigné avec son planning (`EXG-CYC-004`).
  Source       devis v0.1
```

### 11.6 La disposition de l'écran

Comme l'onglet Planning (10.6), l'écran du devis place ce qui se lit d'un coup
d'œil avant ce qui se travaille.

```
EXG-DEV-016 — DOIT — L'écran présente, de haut en bas : une bande de totaux, la
répartition par type de coût, puis la grille.
  Motif        Le montant du projet et sa ventilation sont ce qu'on vient
               vérifier en ouvrant l'écran ; la grille est ce qu'on vient
               modifier. Chercher un total au bas de plusieurs centaines de lignes
               fait recalculer de tête ce que l'écran sait déjà.
  Vérification La bande de totaux est visible sans défilement à l'ouverture de
               l'onglet.
  Source       arbitrage 2026-09-13
```

```
EXG-DEV-017 — DOIT — La bande de totaux porte le montant du projet et le montant
de chaque sous-projet.
  Motif        Le total par sous-projet est le seul niveau auquel le chiffrage se
               compare ensuite au consommé (`EXG-CRE-010`). L'afficher au
               chiffrage, et non seulement à l'analyse, permet de constater une
               ventilation improbable avant de valider plutôt qu'un mois après.
  Vérification Chaque sous-projet du projet a son total, et leur somme est égale
               au total du projet.
  Source       arbitrage 2026-09-13
```

```
EXG-DEV-018 — DOIT — La répartition par type de coût — main-d'œuvre, fourniture,
frais, unité d'œuvre — est affichée graphiquement.
  Motif        C'est la vérification la plus rapide qu'un chiffrage est
               vraisemblable : une proportion inhabituelle entre main-d'œuvre et
               achats se voit d'un regard, alors qu'elle se cherche longtemps dans
               une grille.
  Vérification La répartition couvre les quatre types et somme à cent pour cent
               du montant du projet.
  Source       arbitrage 2026-09-13
```

Les règles de représentation du chapitre 15 s'appliquent à cette figure comme aux
autres : la couleur n'y porte jamais seule l'identité d'un type (`EXG-ANA-011`).

Les colonnes en vigueur pour une ligne de coût sont : la nature, la catégorie de
coût, le libellé, le sous-projet d'imputation, la quantité, les heures ou le
débours unitaire, le **taux de référence**, le montant hors inflation et le montant
corrigé (`EXG-DEV-014`), la **date prévisionnelle de décaissement**
(`EXG-MOD-021`) et l'**état d'approvisionnement** (`EXG-MOD-022`). Les deux
dernières se saisissent et se lisent sans qu'aucun calcul de la v1.0 les
consomme : ce qu'on en fera dans le reste à engager et dans la valeur acquise
est ouvert (question 11), et les saisir dès maintenant évite d'avoir à ressaisir
un historique le jour où la question sera tranchée.

### 11.7 Restitution

```
EXG-DEV-013 — DOIT — La grille affiche, pour chaque ligne, ses facteurs et son
résultat : quantité, heures ou débours, taux appliqué, et montants de
main-d'œuvre et d'achat.
  Motif        Un montant sans ses facteurs ne se vérifie pas. C'est
               particulièrement vrai du taux, qui vient du référentiel et de
               l'année : sans lui à l'écran, un écart de budget entre deux lignes
               semblables est inexplicable.
  Vérification Chaque ligne montre le taux qui lui a été appliqué et l'année dont
               il provient.
  Source       devis v0.1, maquette
```

L'export du chiffrage relève du chapitre 15, avec les autres restitutions.

### 11.8 Ce qui reste ouvert

**Les provisions pour risques** (question 2). Elles n'ont aujourd'hui aucune
forme propre : elles se saisissent comme une ligne de frais ordinaire, ce qui les
rend indiscernables d'une dépense prévue. La pratique — un devis complet par
risque, reporté pondéré dans le devis global — supposerait un module de gestion
des risques, dont l'appartenance à la v1.0 n'est pas acquise. La question reste
ouverte, y compris sur son périmètre.

Rien d'autre. L'assistant de saisie des lignes de support, un temps envisagé
ici, est sorti du périmètre v1.0 et figure au chapitre 23.

---

## 12. Reste à engager et revue mensuelle

**Statut : partiel.** Deux points restent ouverts : le sort des provisions pour
risques (question 2) et la sous-traitance et les fournitures (question 11).

Une fois le projet en pilotage, un seul geste l'alimente : la **revue
mensuelle**. Elle produit une nouvelle révision et une estimation du
reste à faire, et c'est d'elle que sortent tous les indicateurs d'écart. Le
chapitre tient en une idée : ce geste est unique, et il le reste.

### 12.1 Un seul geste

```
EXG-RAE-001 — DOIT — Une nouvelle révision et la saisie du reste à
engager forment un geste unique. Ils sont créés, validés et archivés ensemble,
jamais séparément.
  Motif        Un reste à engager saisi sur une structure de tâches différente de
               celle qu'il prétend chiffrer ne veut rien dire. Les séparer
               autoriserait précisément cela, et l'incohérence ne se verrait
               qu'au moment de comparer.
  Vérification Aucun endpoint ni écran ne permet de créer une estimation de reste
               à engager sans révision, ni l'inverse.
  Source       E10 (#250)
```

```
EXG-RAE-002 — DOIT — Une revue mensuelle n'est possible que sur un projet en
cours.
  Motif        Avant le pilotage, il n'existe pas de révision de référence à
               laquelle
               rapporter le reste à engager (`EXG-CYC-004`) ; après la clôture,
               le projet est en lecture seule (`EXG-CYC-009`).
  Vérification Le déclenchement d'une revue est refusé dans les six autres états.
  Source       E10 (#250)
```

### 12.2 La granularité de la saisie

```
EXG-RAE-003 — DOIT — Le reste à engager se saisit **à la ligne de coût**, jamais
à la tâche.
  Motif        C'est la granularité du devis, donc la seule qui permette de
               comparer ligne à ligne avec la référence. Saisi à la tâche, il
               faudrait le ventiler pour le rapprocher, et la ventilation serait
               une invention.
  Vérification Toute ligne présentée à la saisie correspond à une ligne de coût
               et à une seule ; aucune saisie ne porte sur une tâche entière. Le
               sous-ensemble affiché relève d'`EXG-RAE-011`.
  Source       E10 (#250)
```

```
EXG-RAE-004 — DOIT — La saisie est groupée par code de sous-projet, avec un
total par code.
  Motif        Le consommé n'existe qu'à cette granularité (5.3). C'est donc le
               seul niveau auquel reste à engager et consommé se comparent, et
               un total par tâche ne servirait à rien.
  Vérification Chaque code de sous-projet porte la somme du reste à engager des
               lignes qui lui sont rattachées.
  Source       E10 (#250), E11 (#255)
```

### 12.3 Le rapprochement avec la référence

```
EXG-RAE-005 — DOIT — Une ligne de prévision se rapproche de sa ligne budgétaire
par l'identité de l'élément de travail, non par un pointeur vers la ligne
source.
  Motif        Une identité traverse les versions par construction
               (`EXG-VOC-008`) ; un pointeur ne survit qu'aussi longtemps que la
               ligne visée, et se rompt au premier remaniement du devis de
               référence.
  Vérification Renuméroter ou réordonner les lignes du devis de référence ne
               rompt aucun rapprochement.
  Source       devis v0.1, E14 (#326)
```

```
EXG-RAE-006 — DOIT — Une ligne de prévision sans correspondance dans la
référence est du travail **non anticipé**, et la revue la distingue comme telle.
Une ligne de la référence absente de la revue correspond à un travail
abandonné ; aucune ligne n'est créée pour la représenter.
  Motif        C'est le seul défaut sérieux du reste à engager, et il est
               invisible par nature. Le reste à engager d'une tâche qui existe
               est une information fiable ; ce qui fausse le total, c'est ce qui
               n'y figure pas (5.3). Un reste à engager qui ne décroît pas d'un
               mois sur l'autre s'explique presque toujours par du travail
               découvert en route — encore faut-il le voir.
  Vérification Les lignes sans correspondance sont signalées et dénombrées ; leur
               total est lisible à part.
  Source       E10 (#250), arbitrage 2026-09-12
```

```
EXG-RAE-011 — DOIT — La saisie porte par défaut sur les seules tâches **en jeu**
à la date de la revue, et non sur la totalité du planning. Le périmètre reste
élargissable.
  Motif        Un planning réel compte plusieurs centaines de tâches sur
               plusieurs années. Une tâche qui commence dans trois ans n'a rien à
               dire ce mois-ci, et sa présence dans la grille noie les quelques
               dizaines de lignes qui, elles, ont bougé. Une revue mensuelle qu'on
               ne peut pas lire est une revue qu'on bâcle.
  Vérification Sur un planning pluriannuel, la revue présente d'emblée les seules
               tâches concernées par la période, et permet d'en ajouter.
  Source       arbitrage 2026-09-13
```

```
EXG-RAE-012 — DOIT — La revue présente les tâches en trois zones de **natures
différentes** : un réservoir de ce qui n'a pas commencé, un plan de travail, et
un dépôt de ce qui est terminé. Seul le plan de travail se parcourt.
  Motif        Trois colonnes symétriques s'effondrent aux deux extrémités du
               projet : cinq cents tâches à gauche au démarrage, autant à droite
               à la fin. On puise dans le réservoir et on verse dans le dépôt ;
               ni l'un ni l'autre n'est un espace de navigation.
  Vérification Au démarrage d'un projet de cinq cents tâches comme à sa clôture,
               la revue reste lisible sans défilement démesuré.
  Source       arbitrage 2026-09-13
```

Trois règles suffisent à tenir cette promesse, et toutes réemploient l'existant.
Le réservoir montre l'**arbre replié** — quelques récapitulatives plutôt que
quatre cents feuilles — et se borne aux tâches dont la fenêtre s'ouvre dans
l'horizon de la revue, le reste derrière un compteur. Le dépôt se **groupe par
revue**, puisque ce qu'on veut voir est ce qui s'est terminé ce mois-ci. Et les
éléments sont des **lignes denses**, non des vignettes : le glisser ne demande
pas des pavés.

```
EXG-RAE-013 — DOIT — Faire entrer une tâche dans le plan de travail déclare son
démarrage. L'amener au dépôt ramène son reste à engager à zéro, et le geste
affiche ce qu'il solde : le nombre de lignes et le montant concernés. Le retour
en arrière ne restitue aucune valeur ancienne — la tâche redevient inachevée
avec un reste à engager à saisir.
  Motif        Un seul geste et une seule vérité : le déplacement exécute l'acte
               au lieu de poser un marqueur à côté de lui, faute de quoi deux
               états coexisteraient et divergeraient. Afficher ce qui est soldé
               parce qu'un glissement est un geste léger là où l'affirmation
               qu'il porte ne l'est pas. Et ne rien restituer au retour parce
               qu'une correction est une nouvelle estimation, pas l'annulation de
               la précédente (`EXG-RAE-007`).
  Vérification Déposer une tâche en terminé met toutes ses lignes à zéro après
               confirmation chiffrée ; l'en ressortir laisse ses lignes vides et
               non revenues à leur valeur antérieure.
  Source       arbitrage 2026-09-13
```

### 12.4 L'achèvement se déduit

```
EXG-RAE-007 — DOIT — Une tâche dont le reste à engager de toutes les lignes
atteint zéro est terminée. Ce n'est pas une saisie mais une déduction, et elle
est réversible : une revue ultérieure qui remonte ce total au-dessus de zéro
rend la tâche inachevée.
  Motif        Corollaire d'`EXG-VOC-004` : une remise à zéro est une affirmation
               binaire, plus visible et plus intenable qu'un pourcentage
               d'appréciation. La réversibilité protège du cas courant — une
               saisie corrigée le mois suivant — qu'un achèvement figé rendrait
               indéfendable.
  Vérification Ramener à zéro le reste à engager de la dernière ligne d'une tâche
               la marque terminée ; le remonter la démarque.
  Source       E10 (#250)
```

L'indicateur d'achèvement porté par la tâche est donc un **résultat**, jamais une
entrée. Aucun écran ne le propose à la saisie.

### 12.5 La réconciliation annuelle

```
EXG-RAE-008 — DOIT — Lorsqu'une revue porte sur des charges chiffrées avec un
taux projeté par l'inflation et que le taux réel de cette année est désormais
connu, elle signale l'écart et **propose** la mise à jour du reste à engager.
Elle ne l'applique jamais d'elle-même.
  Motif        C'est le moment où une hypothèse devient un fait, et le seul
               endroit où l'écart entre les deux se voit. Proposer plutôt
               qu'appliquer, parce que la mise à jour déplace un budget : elle
               doit être un geste, visible et daté, et non un effet de bord de
               l'ouverture d'un écran.
  Vérification La revue distingue les charges encore chiffrées sur un taux
               projeté, affiche pour chacune le taux prévu et le taux réel, et
               n'en modifie aucune sans validation explicite.
  Source       arbitrage 2026-09-12, précisé le 2026-09-13
```

Ce n'est pas un mécanisme séparé : l'année de référence d'un chiffrage étant son
année de création (`EXG-DEV-005`), la première revue de janvier en porte
naturellement une nouvelle, dont les taux sont cette fois connus.

### 12.6 Immuabilité

```
EXG-RAE-009 — DOIT — Une revue validée ne change plus. Une correction passe par
une nouvelle revue, jamais par la modification d'une revue passée.
  Motif        La suite des revues est l'histoire du projet : c'est d'elle que se
               lisent les tendances et le moment où la dérive a commencé.
               Réécrire une revue passée effacerait précisément ce qu'on cherche
               à voir.
  Vérification Toute écriture sur une revue validée est refusée ; l'historique
               des revues reste consultable en entier.
  Source       E10 (#250)
```

```
EXG-RAE-010 — DOIT — Les lignes de coût de support se ré-estiment comme les
autres, ligne à ligne.
  Motif        Elles n'ont rien de particulier une fois le devis établi : ce sont
               des lignes de main-d'œuvre ordinaires (11.4). Leur réserver un
               traitement ferait du reste à engager du support une projection du
               budget plutôt qu'une estimation.
  Vérification Aucune ligne n'est exclue de la saisie ni préremplie par un
               calcul.
  Source       arbitrage 2026-09-12
```

### 12.7 Ce qui reste ouvert

**Les provisions pour risques** (question 2). Une provision est-elle une ligne
que l'on ré-estime comme une autre, et que devient-elle quand le risque survient
ou s'écarte ? La réponse dépend du périmètre retenu pour le sujet entier.

**La sous-traitance et les fournitures** (question 11). Que saisit-on dans le
reste à engager d'une fourniture commandée et non livrée, et faut-il une notion
d'engagé pour la décrire ? La question déborde sur la date à laquelle un
engagement se reconnaît — commande, facturation ou règlement — dont l'import
comptable ne donne aujourd'hui que la dernière.

---

## 13. Coûts réels

**Statut : décidé.**

Le coût réel ne se produit pas dans Waterfall : il vient de la comptabilité, par
import. Cette extériorité commande tout le chapitre — Waterfall n'a pas à
recalculer ce que la comptabilité a déjà arrêté, et n'a pas le droit de le
contredire.

### 13.1 Ce qui est importé, et à quelle finesse

```
EXG-CRE-001 — DOIT — Chaque pièce comptable est conservée individuellement.
Waterfall ne stocke jamais un seul total agrégé par code de sous-projet.
  Motif        Un total ne se conteste pas : quand un écart apparaît, seule la
               pièce permet de dire d'où il vient. C'est aussi la condition de
               l'exclusion de périmètre (13.4), qui porte sur une ligne.
  Vérification Le détail d'un code de sous-projet énumère les pièces qui
               composent son total.
  Source       E11 (#255)
```

```
EXG-CRE-002 — DOIT — Les montants importés sont repris tels quels. Aucun taux
horaire n'est recalculé, y compris sur la main-d'œuvre interne, déjà valorisée
en euros à la source.
  Motif        Recalculer introduirait un écart entre Waterfall et la
               comptabilité, et c'est la comptabilité qui fait foi. Un consommé
               que le contrôle de gestion ne peut pas réconcilier avec son propre
               système ne sert à rien.
  Vérification La somme des lignes importées d'un fichier égale la somme du
               fichier, au centime.
  Source       E11 (#255)
```

Un fichier ne concerne qu'un projet à la fois. La nature comptable de chaque
pièce est conservée à titre informatif, sans rapprochement avec le référentiel
de catégories : les deux nomenclatures sont celles de deux systèmes distincts, et
les faire coïncider serait un chantier propre.

### 13.2 Le rattachement

```
EXG-CRE-003 — DOIT — Une pièce se rattache à un sous-projet par le sous-code de
son imputation analytique, rapproché du code du sous-projet.
  Motif        C'est la seule clé commune aux deux systèmes. Elle vit dans la
               comptabilité, ce qui interdit de la renommer librement du côté de
               Waterfall (`EXG-SPR-006`).
  Vérification Une pièce dont le sous-code correspond à un sous-projet du projet
               lui est rattachée ; aucune n'est rattachée par son libellé.
  Source       E11 (#255)
```

```
EXG-CRE-004 — DOIT — Une pièce dont le sous-code est introuvable est rejetée
seule. L'import se poursuit sur les autres et produit un rapport des rejets.
  Motif        Un fichier réel comporte presque toujours quelques imputations
               inattendues. Bloquer l'import entier pour elles rendrait la
               fonction inutilisable le jour où elle sert.
  Vérification Un fichier mêlant des pièces valides et des pièces à sous-code
               inconnu importe les premières et énumère les secondes.
  Source       E11 (#255)
```

### 13.3 L'idempotence, et ce qu'elle permet

```
EXG-CRE-005 — DOIT — L'import est idempotent : une pièce déjà importée n'est pas
recréée. Le numéro de pièce de référence en est la clé.
  Motif        Les exports comptables se recouvrent d'un mois sur l'autre.
               Sans idempotence, chaque import doublerait une partie du consommé,
               et l'erreur serait invisible — un consommé trop élevé ressemble à
               une dérive.
  Vérification Importer deux fois le même fichier laisse les totaux inchangés.
  Source       E11 (#255)
```

L'idempotence n'est pas qu'une protection : c'est **le mécanisme de reprise**.
Après avoir créé le sous-projet manquant, on réimporte le même fichier ; les
pièces déjà présentes sont ignorées et les pièces rejetées sont enfin rattachées.
Sans elle, corriger un rejet demanderait une saisie manuelle.

Cette reprise porte sur **le même fichier**, ce qui suppose de l'avoir conservé.

```
EXG-CRE-011 — DOIT — Un import conserve son fichier source et l'empreinte de
celui-ci, pour la durée de vie du projet. La règle vaut pour tout import, quelle
qu'en soit l'origine.
  Motif        Trois raisons, dont une seule suffirait. La reprise ci-dessus se
               fait sur le fichier d'origine : l'exiger de l'utilisateur des
               semaines plus tard revient à parier qu'il l'a gardé, et le rejet
               qu'on voulait corriger le resterait. Un export comptable n'est par
               ailleurs **pas reproductible** — la même extraction rejouée plus
               tard rend un autre contenu, les corrections passées entre-temps s'y
               trouvant —, si bien qu'un fichier perdu l'est définitivement.
               L'empreinte, enfin, est ce qui permet de reconnaître un fichier
               déjà importé avant de l'ouvrir, et d'établir après coup sur quoi un
               chiffre a été bâti.

               Le coût est mesuré et tenable : de l'ordre de cinq gigaoctets par
               an dans le stockage objet (chapitre 22), contre les deux cents
               attendus sur dix ans.
  Vérification Le fichier d'un import figurant à l'historique (`EXG-ADM-010`) se
               récupère et son empreinte se vérifie ; la sauvegarde le restitue
               avec la base (`EXG-ADM-003`).
  Source       E13-02 (#299), arbitrage 2026-09-13
```

```
EXG-CRE-012 — DOIT — La reprise d'un import se déclenche depuis son historique,
sur le fichier conservé, sans nouveau dépôt.
  Motif        C'est ce qui fait de la conservation autre chose qu'une archive.
               Le geste de reprise suit toujours une correction du référentiel ou
               des sous-projets, c'est-à-dire un moment où l'on sait exactement
               quel import rejouer : le faire depuis l'historique nomme cet import
               sans ambiguïté, là où un nouveau dépôt oblige à retrouver le bon
               fichier parmi ceux d'une année.
  Vérification Après création du sous-projet manquant, relancer l'import depuis
               l'historique rattache les pièces auparavant rejetées et laisse les
               autres inchangées (`EXG-CRE-005`).
  Source       arbitrage 2026-09-13
```

### 13.4 Le périmètre

Une affaire reçoit des coûts qui ne relèvent d'aucune tâche estimée : frais
généraux, charges affectées par décision externe. Ils sont réels et correctement
imputés ; ils ne sont simplement pas le sujet de la mesure (5.3).

```
EXG-CRE-006 — DOIT — Une ligne de coût peut être sortie du périmètre du devis.
Elle reste visible, comptée dans le consommé de l'affaire, et son exclusion est
réversible et motivée par un **texte libre**. Exclure relève de l'écriture sur
les **coûts réels**, distincte de l'écriture sur le chiffrage (`EXG-DRO-015`).
  Motif        Ce n'est pas la correction d'une erreur : la ligne est juste. C'est
               une décision de périmètre, et elle doit rester lisible et
               révocable — une exclusion définitive et anonyme serait
               indiscernable d'une suppression.

               Le motif est libre parce qu'une liste fermée n'a pas de bonne
               taille : courte, elle force à ranger sous « autre » les cas qui
               justifiaient précisément d'écrire quelque chose ; longue, elle ne
               se lit plus. Ce qu'on perd — des motifs dénombrables — n'a pas
               d'usage identifié.

               Les deux domaines ne se confondent pas : un responsable de
               service écrit sur le chiffrage pour y porter ses charges (18.6)
               sans avoir à décider de ce qui entre dans la mesure du projet.
               L'écriture sur les coûts réels est attribuée au chef de projet
               dans la configuration livrée.
  Vérification Exclure une ligne ne la retire d'aucune vue de détail ; le motif
               et l'auteur de l'exclusion sont consultables. Un utilisateur
               disposant de l'écriture sur le chiffrage mais non sur les coûts
               réels se voit refuser l'exclusion, et le refus nomme le domaine
               manquant.
  Source       arbitrage 2026-09-12, précisé le 2026-09-15
```

```
EXG-CRE-007 — DOIT — Une ligne exclue sort de **tous** les indicateurs, sans
exception.
  Motif        Le budget de référence ne couvre que le périmètre du devis. Lui
               opposer un consommé plus large mesure une dérive contre une
               référence qui n'a jamais prétendu la couvrir. Une exclusion qui ne
               vaudrait que pour la valeur acquise laisserait les autres
               indicateurs faux.
  Vérification Aucun indicateur, aucun graphique, aucun export ne compte une
               ligne exclue.
  Source       arbitrage 2026-09-12
```

```
EXG-CRE-008 — DOIT — Les deux totaux sont affichés ensemble : consommé de
l'affaire et consommé du périmètre.
  Motif        Le second seul ferait disparaître de l'écran des dépenses qui ont
               bel et bien été imputées au projet, et rendrait la réconciliation
               avec la comptabilité impossible. Le premier seul masquerait le
               périmètre.
  Vérification L'écran des coûts réels porte les deux totaux et leur écart.
  Source       arbitrage 2026-09-12
```

```
EXG-CRE-013 — DOIT — L'exclusion porte sur **une ligne**. Elle ne se propage
jamais d'elle-même : aucune règle portant sur un code de sous-projet, une nature
comptable ou un libellé n'exclut par avance ce qui n'a pas encore été importé.
  Motif        L'idempotence de l'import (13.3) protège déjà une ligne exclue du
               ré-import : une pièce déjà connue n'est pas recréée, et son
               exclusion tient quel que soit le recouvrement des dates d'export.
               Ce qu'elle ne protège pas, c'est l'arrivée d'une pièce **nouvelle**
               de même nature — l'imputation des frais généraux du mois suivant
               porte son propre numéro et n'est le doublon de rien.

               C'est ce cas qu'une règle automatique prétendrait couvrir, et c'est
               pour cela qu'elle est refusée. Ses deux échecs ne se valent pas :
               oublier d'exclure laisse une dépense dans les indicateurs, où elle
               se remarque ; une règle trop large en retire une qui devait y
               rester, et rien ne le signale jamais. Le geste manuel reste tenable
               parce qu'`EXG-CRE-014` le rend fiable.
  Vérification Aucun écran ne permet de définir une règle d'exclusion ; importer
               une pièce de même nature qu'une pièce exclue la fait entrer dans
               le périmètre.
  Source       arbitrage 2026-09-15
```

```
EXG-CRE-014 — DOIT — Le résultat d'un import distingue les lignes qu'il vient de
créer de celles qui étaient déjà connues.
  Motif        C'est la condition pour que l'exclusion ligne à ligne
               (`EXG-CRE-013`) ne devienne pas un geste qu'on oublie. Sur un
               export qui recouvre le mois précédent, la plupart des lignes sont
               déjà là ; celles qui appellent une décision sont les nouvelles, et
               les chercher dans la masse est exactement ce que personne ne fait
               tous les mois.
  Vérification Après un import recouvrant partiellement le précédent, les lignes
               créées par ce dernier import sont identifiables sans les comparer
               à la main à l'état antérieur.
  Source       arbitrage 2026-09-15
```

### 13.5 Ce que le coût réel n'est pas

```
EXG-CRE-009 — DOIT — Aucun coût réel n'est déduit d'un calcul. Le travail de
support donne lieu à de vraies imputations comptables, comme tout autre travail.
  Motif        Déduire le consommé du support d'un pourcentage le rendrait
               proportionnel à son budget, donc structurellement incapable de
               révéler le seul écart qui intéresse — entre ce qu'on avait prévu
               d'y passer et ce qu'on y a passé.
  Vérification Le consommé rattaché à du travail de support provient
               exclusivement de pièces importées.
  Source       arbitrage 2026-09-12
```

```
EXG-CRE-010 — DOIT — La comparaison entre consommé et reste à engager se fait au
niveau du code de sous-projet, jamais à celui de la ligne ou de la tâche.
  Motif        C'est la seule granularité que les deux grandeurs partagent : le
               reste à engager se saisit à la ligne de coût, le consommé arrive
               par pièce comptable, et rien ne relie une pièce à une ligne. Les
               comparer plus finement supposerait une ventilation inventée.
  Vérification Aucune vue ne présente un écart consommé / reste à engager à une
               granularité plus fine que le code de sous-projet.
  Source       E10 (#250), E11 (#255)
```

La date retenue pour une pièce est sa **date de pièce**, c'est-à-dire celle du
règlement. L'export comptable ne porte aucune date de commande, ce qui interdit
de dater un engagement de façon fiable — voir les questions 3 et 11.

---

## 14. Avancement et valeur acquise

**Statut : partiel.** Un point reste ouvert : le traitement des provisions pour
risques (question 2).

C'est le chapitre où le produit tient sa promesse : dire où en est réellement
l'affaire. Tout le reste l'alimente. Sa règle fondatrice tient en une phrase —
**l'avancement physique n'est jamais estimé**.

### 14.1 L'avancement se déduit, il ne se saisit pas

```
EXG-AVA-001 — DOIT — L'avancement physique est déduit de règles fixées à
l'avance, qui ne demandent que des réponses binaires. Aucun écran ne propose de
saisir un pourcentage d'avancement.
  Motif        Un pourcentage intermédiaire est une opinion, et une opinion
               optimiste est indétectable. Une règle binaire produit un chiffre
               que son auteur ne choisit pas.
  Vérification Aucun champ de saisie d'avancement n'existe dans l'application.
  Source       avancement v0.1
```

```
EXG-AVA-002 — DOIT — La méthode est **0/100 par tâche, pondérée par le budget de
référence de la tâche** : une tâche terminée acquiert toute sa valeur, une tâche
en cours n'en acquiert aucune.
  Motif        Toute méthode intermédiaire réintroduit l'appréciation qu'on vient
               d'écarter. La sous-estimation qui en résulte est bornée et connue,
               là où l'optimisme ne l'est pas.
  Vérification La valeur acquise d'une tâche non terminée est nulle, quel que
               soit son reste à engager.
  Source       avancement v0.1
```

```
EXG-AVA-003 — DOIT — Le signal d'achèvement est le reste à engager de la tâche
ramené à zéro. L'indicateur d'avancement stocké sur la tâche est un **résultat**
de cette règle, jamais une entrée.
  Motif        C'est la même affirmation binaire qu'`EXG-VOC-004`, prise du côté
               du calcul. L'indicateur stocké sert à l'affichage et à l'export ;
               le prendre pour une source rendrait l'avancement dépendant de qui
               l'a écrit en dernier.
  Vérification Aucun calcul de valeur acquise ne lit l'indicateur stocké ; il est
               recalculable en entier depuis les restes à engager.
  Source       avancement v0.1, E10 (#250)
```

```
EXG-AVA-004 — DOIT — Le reste à engager d'une ligne **jamais saisie** vaut son
budget de référence.
  Motif        C'est la seule valeur juste : tant que rien n'a été dit du reste à
               faire, tout reste à faire. Le mettre à zéro ferait démarrer tout
               projet à cent pour cent d'avancement physique ; le laisser vide
               rendrait la projection à terminaison — coût réel plus reste à
               engager — fausse jusqu'à la première revue, et d'autant plus basse
               que le projet est jeune.
  Vérification Sur un projet en cours n'ayant reçu aucune revue, la somme des
               restes à engager est égale au budget de référence, et l'avancement
               physique est nul.
  Source       avancement v0.1, arbitrage 2026-09-13
```

```
EXG-AVA-005 — ABANDONNÉE — déjà couverte par `EXG-PLN-001`.
  Motif        Elle énonçait que l'avancement d'un fichier MS Project est ignoré.
               C'est une conséquence directe de ce que Waterfall retient d'un
               import — les tâches et les liens de précédence, rien d'autre. Deux
               exigences disant la même chose finissent par diverger.
```

```
EXG-AVA-006 — DOIT — Une tâche terminée crédite son **budget de référence**,
jamais ce qu'elle a coûté.
  Motif        C'est ce qui rend la méthode robuste au reste à engager. Une tâche
               achevée en dépassement crédite son budget pendant que le coût réel
               est supérieur : l'indice de coût se dégrade correctement. Créditer
               le coût réel ferait qu'un dépassement ressemblerait à de la
               production.
  Vérification Une tâche terminée à deux fois son budget acquiert son budget, et
               l'indice de coût du projet baisse.
  Source       avancement v0.1
```

Il en découle qu'un travail exécuté et payé mais **absent du planning** fait
croître le coût réel sans faire croître la valeur acquise, donc baisser l'indice
de coût. La méthode ne détecte pas l'oubli, mais elle en révèle l'effet — ce
qu'un avancement financier seul est incapable de faire.

### 14.2 Les tâches qui échappent à la règle nominale

```
EXG-AVA-007 — DOIT — Une tâche dont la durée dépasse un seuil paramétré acquiert
en **50/50** : la moitié de sa valeur à son démarrage — au sens d'`EXG-RAE-013`,
c'est-à-dire son entrée dans le plan de travail d'une revue — l'autre à son
achèvement.
  Motif        En 0/100, une tâche de six mois ne pèse rien pendant six mois puis
               saute d'un coup. Le 50/50 borne cette sous-estimation sans
               réintroduire d'appréciation : les deux moments restent binaires.
  Vérification Au-delà du seuil, une tâche entrée dans le plan de travail et non
               finie acquiert exactement la moitié de son budget, et l'entrée
               signale cet effet.
  Source       avancement v0.1
```

Le seuil est un paramètre de projet, fixé une fois. Valeur de départ proposée :
cent vingt jours.

```
EXG-AVA-008 — ABANDONNÉE — le support n'a pas de traitement propre.
  Motif        Elle faisait acquérir les coûts de support au rythme de la
               production encadrée, en s'appuyant sur une qualification portée par
               le sous-projet. Or ni la dérivation du budget ni la notion de
               sous-projet de support n'existent : une ligne de support est une
               ligne de main-d'œuvre ordinaire, portée par une tâche comme les
               autres (`EXG-SPR-011`, 11.4). Le cas qui la motivait — une tâche
               d'encadrement longue qui ne pèserait rien pendant des années — est
               couvert par la règle des tâches longues (`EXG-AVA-007`).
```

### 14.3 Bornes et disponibilité

```
EXG-AVA-009 — DOIT — L'indice de délai et l'indice de coût ne sont pas définis
avant le pilotage. Ils sont affichés comme indisponibles, jamais comme valant un.
  Motif        Un indice à un se lit « tout va bien ». Sur un projet qui n'a
               pas encore de reste à engager, c'est une affirmation sans contenu,
               et elle est rassurante — donc dangereuse.
  Vérification Sur un projet qui n'est pas en cours, les deux indices affichent
               une mention d'indisponibilité et non une valeur.
  Source       avancement v0.1
```

```
EXG-AVA-010 — DOIT — Valeur planifiée, coût réel et valeur acquise ne sont
tracés que jusqu'à la date du jour. Aucune n'est extrapolée ; au-delà, seule la
référence est tracée.
  Motif        Prolonger une courbe de constat lui donne l'apparence d'un fait.
               Les projections existent, elles sont distinctes, et elles portent
               leur nom (14.4).
  Vérification Les trois courbes s'arrêtent à la date du jour.
  Source       avancement v0.1
```

```
EXG-AVA-011 — DOIT — La valeur acquise n'excède jamais le budget de référence.
Elle peut décroître, lorsqu'une tâche cesse d'être terminée, et ce retour en
arrière est tracé, pas absorbé silencieusement.
  Motif        Un achèvement qui se rétracte est une information : soit une
               correction de saisie, soit du travail qu'on croyait fini. Les deux
               méritent d'être vus.
  Vérification Ramener au-dessus de zéro le reste à engager d'une tâche terminée
               fait baisser la valeur acquise et laisse une trace datée.
  Source       avancement v0.1, E10 (#250)
```

```
EXG-AVA-012 — DOIT — La valeur acquise d'une tâche récapitulative est nulle.
  Motif        Sa valeur est portée par ses enfants ; la compter la doublerait.
  Vérification Sur un projet dont toutes les tâches feuilles sont terminées, la
               somme des valeurs acquises est égale au budget de référence — les
               lignes qu'aucune feuille ne porte ayant acquis la totalité du leur
               (`EXG-AVA-015`).
  Source       avancement v0.1, E10 (#250)
```

Un jalon ne porte aucun coût : sa valeur acquise est nulle par construction, et
le terminer n'acquiert rien. Une tâche sans coût se comporte de même.

```
EXG-AVA-015 — DOIT — Une ligne de coût dont la tâche porteuse **ne peut pas
acquérir** — parce qu'elle n'en a aucune, ou parce que sa porteuse est une
récapitulative — acquiert au **taux d'ensemble** du projet : la part déjà acquise
du périmètre qui, lui, acquiert.
  Motif        Sans règle, ces lignes entrent au dénominateur de l'avancement
               physique sans que rien ne les fasse jamais entrer au numérateur :
               le taux plafonne sous cent pour cent, d'autant plus bas qu'elles
               pèsent. Elles sont plus nombreuses qu'il n'y paraît — une ligne de
               support accrochée à la récapitulative « Management » que porte
               tout planning réel est dans ce cas, au même titre qu'une ligne de
               racine.

               Les **exclure des deux termes** aurait paru plus propre et ne
               l'est pas. Le §5.1 pose que l'avancement physique et la
               consommation du budget partagent le même dénominateur, et que leur
               rapport est exactement l'indice de performance des coûts : les
               retirer d'un seul des deux rompt cette identité. Les retirer des
               deux la préserve, mais fait alors disparaître des indicateurs une
               dépense qui croît justement avec l'allongement du planning — c'est
               l'encadrement d'un projet qui dérive, et le sortir de la mesure
               reviendrait à ne plus voir ce qu'on cherche.

               **Exiger une tâche porteuse** ne fermerait pas la question non
               plus : il faudrait exiger une tâche **feuille**, une récapitulative
               n'acquérant rien. Accrocher le support à la récapitulative qui
               porte son nom resterait sans effet, et une feuille créée pour la
               circonstance n'aurait ni durée sensée ni achèvement observable.

               Le taux d'ensemble est enfin défendable métier : une assurance
               couvre le projet, une équipe d'encadrement encadre le projet.
               Quand la moitié du travail est produite, la moitié de ce qu'elles
               servent à couvrir l'a été.
  Vérification Sur un projet dont les tâches feuilles terminées représentent la
               moitié du budget qu'elles portent, ces lignes créditent la moitié
               du leur ; lorsque toutes sont terminées, l'avancement physique
               atteint cent pour cent. Une ligne portée par une récapitulative
               **acquiert** comme une ligne de racine ; les deux se **valorisent**
               en revanche différemment, sur les années de la récapitulative pour
               l'une et sur celles du projet pour l'autre (`EXG-DEV-022`).
  Source       arbitrage 2026-09-15
```

Le calcul se fait en **deux temps**, et l'ordre lève toute circularité : le taux
d'ensemble s'établit d'abord sur le seul périmètre acquérant — les lignes portées
par une tâche feuille —, puis s'applique aux autres. Ces dernières n'entrent
jamais dans le taux qui les détermine.

Tant qu'aucune ligne n'est portée par une tâche feuille, le taux d'ensemble est
nul et la valeur acquise de ces lignes l'est aussi. Le cas n'appelle pas de
traitement particulier : un projet dont aucun travail n'est mesurable n'a pas
d'avancement physique à montrer.

**Ce que cette règle ne donne pas.** Ces lignes ne montrent jamais d'écart qui
leur soit propre : elles héritent de celui du projet. On ne lit donc pas « le
management dérape » isolément, mais que le projet dérape et que le management
pèse dedans — ce qui est la bonne lecture, l'enjeu d'une dérive d'encadrement
n'étant jamais le coût de la ligne d'encadrement.

### 14.4 Projections

```
EXG-AVA-013 — DOIT — Le coût final projeté n'est pas unique. Plusieurs
hypothèses sont présentées ensemble, chacune nommée : le reste conforme au plan,
la performance de coût constante, et la performance de coût corrigée du retard.
  Motif        Une projection unique passe pour une prévision. Trois courbes
               affichées ensemble montrent l'éventail, et leur écartement dit
               lui-même l'incertitude. L'estimation du chef de projet — coût réel
               plus reste à engager — en est une parmi d'autres, pas la vérité.
  Vérification Le graphe de projection porte au moins trois hypothèses nommées,
               et aucune n'est présentée comme la projection par défaut.
  Source       avancement v0.1, arbitrage maquette
```

```
EXG-AVA-014 — DOIT — Les indices portent leur tendance : leur valeur courante
est accompagnée de leur évolution depuis les revues précédentes.
  Motif        Un indice de coût à quatre-vingt-quinze pour cent ne dit pas la
               même chose selon qu'il remonte ou qu'il descend. Sans tendance,
               une dégradation lente est indiscernable d'un état stable.
  Vérification Chaque indice affiche son évolution sur les dernières revues.
  Source       arbitrage maquette
```

La règle de dénominateur (`EXG-VOC-002`) s'applique à toutes ces restitutions :
consommation du budget et avancement physique se présentent côte à côte, leur
rapport étant exactement l'indice de coût ; l'avancement financier ne leur est
jamais adjacent sans que sa base soit nommée.

### 14.5 Ce qui reste ouvert

**Les provisions pour risques** (question 2). Une provision consommée n'est pas
du travail produit : la compter comme telle gonflerait l'avancement physique.
Reste à décider si elle entre au dénominateur, et ce que sa survenue déplace.

---

## 15. Analyse et restitution

**Statut : décidé.**

L'analyse est la finalité du produit (2.1). Tout ce qui précède existe pour
l'alimenter, et ce chapitre dit ce qu'elle montre.

### 15.1 Le tableau de bord répond à des questions, dans l'ordre

Sa disposition n'est pas une composition graphique : c'est un enchaînement de
questions, chacune préparant la suivante.

| # | Question | Ce qui y répond |
|---|---|---|
| 1 | Où en est-on ? | Les tuiles d'indicateurs, avant tout graphique |
| 2 | Suis-je dans les clous ? | Écart au budget de référence, dérive des jalons |
| 3 | Pourquoi ? | Les trois courbes de la valeur acquise |
| 4 | Où en est chaque sous-projet ? | Avancement ventilé |
| 5 | De qui ai-je besoin, et quand ? | Le plan de charge du projet (`EXG-ANA-015`) |
| 6 | Quand l'a-t-on vu venir ? | Évolution de la projection à terminaison |
| 7 | À quoi ressemble le projet ? | Planning et organigramme des tâches, pleine largeur |

```
EXG-ANA-001 — DOIT — La disposition du tableau de bord est fixe en v1.0, et
suit cet ordre.
  Motif        L'ordre porte un raisonnement : on constate, on situe, on
               explique, on ventile, on dimensionne, on projette. Une disposition
               libre
               permettrait de le défaire, et la première chose qu'on y perdrait
               est la règle de dénominateur (`EXG-VOC-002`), qui dépend du
               voisinage des tuiles. Rendre la disposition configurable est une
               fonctionnalité de confort ; elle ne relève pas du critère
               d'inclusion (1.3).
  Vérification Les sept blocs apparaissent dans l'ordre du tableau ci-dessus, et
               aucun écran ne permet d'en déplacer, d'en masquer ou d'en
               redimensionner un.
  Source       arbitrage maquette
```

Le tableau de bord remplace ce qui aurait été une seconde rangée d'onglets. Une
analyse répartie sur des onglets oblige à retenir ce qu'on a vu ailleurs pour le
comparer ; réunie sur une page, la comparaison est immédiate.

### 15.2 Les indicateurs

```
EXG-ANA-002 — DOIT — La bande de tuiles d'indicateurs précède tout bloc
graphique de la page. La tendance portée par une tuile (`EXG-AVA-014`) n'est pas
un de ces blocs.
  Motif        Un chiffre se lit en une seconde, une courbe en dix. Celui qui
               ouvre l'écran veut d'abord savoir si quelque chose va mal ; il
               cherche l'explication ensuite, et seulement s'il le faut. La
               réserve sur la tendance évite de lire cette règle comme une
               interdiction de tout tracé à l'intérieur d'une tuile : c'est
               l'ordre des blocs de la page qui est fixé, pas leur contenu.
  Vérification Le premier bloc de la page est la bande de tuiles.
  Source       arbitrage maquette
```

```
EXG-ANA-003 — DOIT — Les deux avancements sont présentés chacun avec sa base
nommée, et l'avancement physique est accompagné de la consommation du budget,
qui partage son dénominateur.
  Motif        Application directe d'`EXG-VOC-002`. L'avancement financier est
               mécaniquement tiré vers le bas par la dérive elle-même : juxtaposé
               sans précaution à l'avancement physique, il annonce que la
               production est en avance sur la dépense, l'exact contraire de la
               réalité.
  Vérification Chaque tuile de taux porte la mention de sa base ; consommation et
               avancement physique sont adjacents.
  Source       avancement v0.1, maquette
```

```
EXG-ANA-004 — ABANDONNÉE — répétait `EXG-AVA-014`.
  Motif        La règle — les indices portent leur tendance — est énoncée une
               fois, au chapitre qui définit ces indices. La répéter ici en
               aurait fait deux énoncés voués à diverger. La tuile d'indice
               applique `EXG-AVA-014`.
```

```
EXG-ANA-005 — DOIT — L'écart à terminaison est présenté comme un **intervalle**
issu de plusieurs hypothèses, et non comme une valeur unique.
  Motif        Une valeur unique se lit comme une prévision. L'écartement des
               hypothèses est lui-même l'information : il dit combien on sait. Le
               chiffre du chef de projet y figure comme l'une d'elles.
  Vérification La tuile porte une fourchette et le nombre d'hypothèses qui la
               produisent.
  Source       arbitrage maquette
```

### 15.3 Le catalogue des analyses

| Analyse | Ce qu'elle répond |
|---|---|
| Écart au budget de référence | Quels postes dérivent, et de combien |
| Dérive des jalons | À quelle vitesse les échéances reculent |
| Valeur acquise | D'où sortent les deux indices |
| Avancement par sous-projet | Où se concentre le retard |
| Évolution de la projection | À quel moment on a vu venir la dérive |
| Planning | La forme du projet dans le temps |
| Plan de charge du projet | Quels rôles sont demandés, et quand |
| Organigramme des tâches | La structure du travail |

```
EXG-ANA-006 — DOIT — Les projections sont tracées séparément des courbes de
constat, et chacune porte son nom.
  Motif        `EXG-AVA-010` borne déjà les courbes de constat à la date du jour ;
               ce qui reste à dire est ce qui les distingue de ce qui les
               prolonge. Une projection dont le tracé ne se distingue pas d'un
               constat est une prédiction déguisée en mesure.
  Vérification Les projections portent un tracé distinct de celui des courbes de
               constat, et leur nom est lisible sans survol.
  Source       avancement v0.1, maquette
```

```
EXG-ANA-007 — DOIT — L'évolution de la projection à terminaison est tracée
revue après revue.
  Motif        C'est la seule vue qui réponde à « quand l'a-t-on vu venir ». Elle
               distingue une dérive découverte d'un coup d'une dérive
               progressive, et les deux n'appellent pas la même conclusion sur la
               conduite du projet.
  Vérification Chaque revue mensuelle ajoute un point à cette courbe.
  Source       arbitrage maquette
```

```
EXG-ANA-015 — DOIT — Le tableau de bord d'un projet porte son propre plan de
charge : les heures de ses rôles ventilées dans le temps.
  Motif        Le plan de charge agrégé (chapitre 16) répond à « l'entreprise
               peut-elle tenir » ; il ne répond pas à « de qui ce projet a-t-il
               besoin, et quand ». La seconde question se pose au chef de projet
               bien avant la première, et il n'a pas accès à la section
               Management pour se la poser.
               Il ne porte en revanche **aucune capacité** : une capacité
               n'a de sens que globale. La rapporter à un projet donnerait à
               croire qu'une part en est réservée, ce qu'aucun arbitrage ne
               garantit.
  Vérification Le plan de charge du projet emploie la même ventilation temporelle
               que le plan agrégé (`EXG-CHA-005`), leurs totaux coïncident pour
               ce projet, et aucune ligne de capacité n'y figure.
  Source       arbitrage 2026-09-13
```

```
EXG-ANA-016 — DOIT — Le diagramme de Gantt met en évidence le chemin critique.
  Motif        Sur un planning de plusieurs centaines de tâches, un Gantt sans
               chemin critique ne dit pas où un retard coûte. C'est la seule
               information qui sépare une tâche dont le glissement décale la fin
               d'une tâche qui dispose de marge — et donc la seule qui oriente une
               décision.
  Vérification Les tâches du chemin critique sont distinguées par un encodage qui
               ne repose pas sur la seule couleur (`EXG-ANA-011`).
  Source       arbitrage 2026-09-13
```

Une tâche manuelle ne tient pas ses dates de ses prédécesseurs : elle interrompt
la chaîne, et le chemin critique se calcule sur le réseau des tâches
automatiques. Le cas est marginal — sur les plannings réels mesurés, cinquante-deux
tâches manuelles sur deux mille six cent soixante-six — mais un planning qui en
compterait beaucoup rendrait le chemin partiel, ce qui doit alors être signalé.

```
EXG-ANA-017 — DOIT — Le diagramme de dérive porte en abscisse la date de la
revue et en ordonnée la date prévue de chaque jalon suivi.
  Motif        C'est le seul graphique qui montre non pas le retard mais son
               **rythme**. Une ligne horizontale est un jalon tenu ; une pente de
               quarante-cinq degrés est un jalon qui recule d'autant qu'on
               avance, donc jamais atteint. Cela se lit des mois avant que la
               date elle-même ne devienne alarmante.
  Vérification Chaque revue ajoute un point par jalon suivi, et une échéance
               tenue trace une horizontale.
  Source       arbitrage maquette, 2026-09-13
```

```
EXG-ANA-008 — ABANDONNÉE — sortie du périmètre v1.0 avec la trésorerie
(chapitre 23).
  Motif        Elle décrivait la courbe confrontant encaissements et
               décaissements, et le besoin de financement qu'elle fait
               apparaître. Les encaissements venaient des prix de vente des lots,
               qui quittent la v1.0 avec elle.
```

### 15.4 L'organigramme des tâches

```
EXG-ANA-009 — DOIT — L'organigramme se lit de haut en bas : une tâche de tête,
les tâches de niveau deux alignées horizontalement sous elle, et les niveaux
suivants alignés verticalement sous leur parent, en retrait.
  Motif        C'est la lecture habituelle d'un organigramme de projet, et la
               seule qui tienne sur une page imprimée : un arbre entièrement
               horizontal devient illisible dès le troisième niveau.
  Vérification La disposition est conforme pour un arbre d'au moins quatre
               niveaux.
  Source       arbitrage maquette
```

```
EXG-ANA-010 — DOIT — Un sélecteur borne la profondeur affichée, par numéro de
niveau. Au-delà de la largeur disponible, l'organigramme défile
horizontalement ; il n'est jamais comprimé.
  Motif        Un planning réel fait exploser la page au troisième niveau. Les
               niveaux sont numérotés et non nommés, parce que rien n'impose au
               planning de reproduire le lotissement (`EXG-VOC-006`). Comprimer
               pour faire tenir rendrait les libellés illisibles, ce qui revient
               à ne rien afficher.
  Vérification Le sélecteur propose les niveaux présents ; le contenu déborde en
               défilement et non en réduction.
  Source       arbitrage maquette
```

### 15.5 Règles de représentation

```
EXG-ANA-011 — DOIT — La couleur ne porte jamais une information seule : elle
double toujours un libellé, une position ou une forme.
  Motif        Une information portée par la seule teinte disparaît en vision
               déficiente, à l'impression et en contraste forcé — c'est-à-dire
               précisément quand un graphique est transmis à un tiers.
  Vérification Toute série, tout seuil et tout état distingué par la couleur
               porte un second encodage.
  Source       règles de représentation, maquette
```

```
EXG-ANA-012 — DOIT — Charge et coût ne partagent jamais un axe. Deux grandeurs
de dénominateurs différents ne sont jamais superposées sans que leur base soit
nommée.
  Motif        Reprise d'`EXG-VOC-010` et d'`EXG-VOC-002` sur le terrain où elles
               se violent le plus facilement : un second axe vertical rend
               comparables deux grandeurs qui ne le sont pas, et l'œil conclut
               avant la lecture.
  Vérification Aucun graphique ne porte deux axes verticaux d'unités
               différentes.
  Source       maquette
```

```
EXG-ANA-013 — DOIT — Chaque graphique est exportable en image.
  Motif        Ces analyses servent en revue de projet et en comité. Sans export,
               elles sont recopiées à la main dans une présentation, avec les
               erreurs et l'obsolescence que cela suppose.
  Vérification Chaque graphique porte une commande d'export produisant une image
               lisible hors de l'application.
  Source       arbitrage maquette
```

```
EXG-ANA-014 — DOIT — Un indicateur qui n'est pas calculable est affiché comme
indisponible, avec la raison, et jamais remplacé par une valeur neutre.
  Motif        Un indice affiché à un se lit « tout va bien » (`EXG-AVA-009`).
               Un zéro se lit « rien n'a été fait ». Les deux sont des
               affirmations, là où l'absence de donnée n'en est pas une.
  Vérification Sur un projet sans coût réel importé, les indices concernés
               portent une mention d'indisponibilité nommant ce qui manque.
  Source       avancement v0.1, maquette
```

L'export tabulaire reprend la grille du devis, ses sous-totaux et ses agrégats
par type, catégorie, code comptable et nœud d'organisation, avec la version, le
statut et la date du chiffrage.

---

## 16. Management et portefeuille

**Statut : décidé.**

Tout ce qui précède regarde un projet. Cette section regarde **l'ensemble** — et
change donc de lecteur. On n'y vient pas pour conduire une affaire mais pour
savoir laquelle des vingt demande de l'attention, et si l'on peut en accepter une
de plus.

### 16.1 Une section pour un autre usage

```
EXG-CHA-001 — DOIT — La section Management n'agrège que ce qui traverse
plusieurs projets, et relève d'une habilitation distincte de celle qui donne
accès à un projet.
  Motif        Voir le portefeuille, c'est voir la marge et le retard de projets
               qu'on ne conduit pas. Le droit d'en conduire un n'emporte pas
               celui de tous les regarder.
  Vérification Un utilisateur sans cette habilitation voit la section et se voit
               refuser l'accès avec sa raison (`EXG-NAV-001`), plutôt que de la
               voir disparaître.
  Source       arbitrage 2026-09-13, chapitre 18
```

### 16.2 Le portefeuille

```
EXG-CHA-002 — DOIT — Le portefeuille présente une ligne par projet, portant son
statut, son budget de référence, son projeté à terminaison, son écart, ses deux
indices et son avancement physique.
  Motif        Sans cette vue, savoir lequel de vingt projets dérive suppose de
               les ouvrir un par un. Personne ne le fait chaque semaine ; donc
               personne ne regarde, et les dérives se découvrent tard.
  Vérification Chaque projet accessible y figure avec ces valeurs, et un clic
               mène à son tableau de bord.
  Source       arbitrage 2026-09-13
```

```
EXG-CHA-003 — DOIT — Les valeurs du portefeuille sont celles que chaque projet
calcule, reprises sans recalcul ni recomposition. Un indicateur indisponible sur
un projet l'est aussi dans le portefeuille, avec sa raison.
  Motif        Deux chemins de calcul finissent par diverger, et c'est la
               synthèse qu'on croira. Un projet sans coût réel importé n'a pas
               d'indice de coût : lui en donner un dans le portefeuille, fût-ce
               un, fabriquerait une information (`EXG-ANA-014`).
  Vérification Les valeurs d'une ligne de portefeuille sont identiques à celles
               du tableau de bord du projet, à la même date.
  Source       arbitrage 2026-09-13
```

```
EXG-CHA-004 — DOIT — Le portefeuille se trie et se filtre sur ces colonnes, et
son ordre par défaut fait remonter ce qui va mal.
  Motif        Un tableau trié par nom oblige à lire vingt lignes pour trouver
               les deux qui comptent. L'ordre par défaut d'un écran de
               surveillance est une décision, pas un reste de l'ordre
               d'insertion.
  Vérification À l'ouverture, les projets en dépassement ou en retard figurent en
               tête.
  Source       arbitrage 2026-09-13
```

### 16.3 Le plan de charge

```
EXG-CHA-005 — DOIT — La charge agrégée provient des heures affectées aux rôles
dans les chiffrages, ventilées dans le temps selon les **mêmes règles qu'au
devis** : au prorata des dates de la tâche porteuse (`EXG-DEV-006`), et sur les
années du projet pour une ligne de racine qui n'en a pas (`EXG-DEV-022`).
  Motif        Deux ventilations temporelles différentes pour la même donnée
               produiraient deux vérités, et l'écart serait inexplicable. La
               ligne de racine n'y échappe pas : l'écarter du plan de charge
               rendrait fausse l'égalité vérifiée ci-dessous dès qu'une ligne y
               traîne — cas qu'`EXG-AVA-015` décrit comme fréquent, une ligne de
               support accrochée haut dans l'arbre étant la règle plutôt que
               l'exception.
  Vérification La somme des heures d'un projet dans le plan de charge est égale
               à celle du chiffrage affiché pour ce projet — de référence s'il
               est piloté, courant sinon — y compris lorsque des lignes de
               main-d'œuvre sont à la racine.
  Source       maquette, arbitrage 2026-09-13
```

```
EXG-CHA-006 — DOIT — La charge se ventile par rôle et par nœud d'organisation,
et se filtre sur l'un comme sur l'autre.
  Motif        La question « ai-je les gens » ne se pose jamais globalement : elle
               se pose pour un métier, dans un service. Une charge totale ne dit
               rien d'une pénurie localisée, qui est le cas courant.
  Vérification Le plan de charge se restreint à un rôle, à un nœud
               d'organisation, ou aux deux.
  Source       maquette
```

```
EXG-CHA-007 — DOIT — La capacité est tracée comme un **niveau constant**,
ramené à la maille temporelle affichée. Elle reste tracée quel que soit le
filtre, et l'échelle verticale est calée pour qu'elle demeure visible.
  Motif        La charge ne se lit que contre la capacité : seule, c'est une
               courbe sans seuil. Une capacité qui disparaît au filtrage, ou qui
               sort du cadre parce que l'échelle suit la seule charge, retire à
               l'écran sa raison d'être au moment précis où l'on cherche une
               surcharge.

               Le niveau est constant **à dessein**, et ce n'est pas une
               approximation à corriger plus tard. L'information utile n'est pas
               dans la ligne mais dans ce qui la dépasse : de combien, et pendant
               combien de temps. C'est cela qui commande l'arbitrage — assumer le
               retard, prendre un intérimaire si la surcharge ne dure que
               quelques mois, recruter si c'est une tendance de fond. Un modèle
               de capacité daté demanderait de tenir des effectifs prévisionnels
               sans rien ajouter à cette lecture.
  Vérification Tout filtre laisse la capacité correspondante tracée et dans le
               cadre ; un dépassement se lit en amplitude et en durée.
  Source       arbitrage maquette, précisé le 2026-09-13
```

La capacité tracée ici est produite par le référentiel : elle est portée par le
rôle de ressource, en heures par mois (`EXG-PAR-004`), et le niveau affiché est
la somme des capacités des rôles que le filtre retient.

Charge et coût ne partagent jamais un axe (`EXG-VOC-010`) : cette vue se lit en
heures, et se compare à une capacité, jamais à un budget.

---

## 17. Import et export MS Project

**Statut : décidé.**

MS Project est annexe (2.2) : il sert à qui préfère son interface pour construire
un planning. Ce chapitre décrit le seul lien entre les deux outils — un fichier,
échangé à la demande.

### 17.1 Un échange, pas une synchronisation

```
EXG-MSP-001 — DOIT — L'échange se fait par fichier, sur action explicite.
Waterfall ne surveille aucun fichier et ne se synchronise avec aucune instance
de MS Project.
  Motif        Une synchronisation continue ferait de MS Project une source
               vivante, donc une seconde vérité. Le planning de référence vit
               dans Waterfall, qui seul porte les versions et les chiffrages.
  Vérification Aucun mécanisme d'import ne se déclenche sans qu'un utilisateur
               ait fourni un fichier.
  Source       arbitrage produit
```

Ce que l'import retient — les tâches et les liens de précédence, à l'exclusion
des calendriers et des ressources du fichier — est fixé par `EXG-PLN-001`.

```
EXG-MSP-002 — DOIT — Un import produit une **nouvelle révision**. Il ne modifie
aucune révision existante.
  Motif        Les versions sont l'histoire du projet (`EXG-RAE-009`). Un import
               qui réécrirait la version courante effacerait l'état sur lequel
               une revue a peut-être déjà été faite.
  Vérification Après import, les versions antérieures sont inchangées et
               consultables.
  Source       code existant
```

### 17.2 L'identifiant d'échange

```
EXG-MSP-003 — DOIT — L'identifiant MS Project sert exclusivement à réconcilier
un fichier avec ce que Waterfall connaît déjà. Il est lu à l'import, écrit à
l'export, et n'intervient dans aucune opération de domaine.
  Motif        Reprise d'`EXG-VOC-008` sur son terrain : l'identité d'un élément
               de travail est portée par le domaine, pas par un identifiant venu
               d'un fichier extérieur qu'un autre outil alloue.
  Vérification Aucune requête de domaine ne résout un nœud par cet identifiant.
  Source       E14 (#326, #359)
```

```
EXG-MSP-004 — DOIT — L'identifiant émis par un export est **conservé** et
rattaché à l'élément de travail exporté. Un import de retour réconcilie donc les
tâches au lieu d'en créer des copies.
  Motif        C'est ce qui rend l'aller-retour possible : sans conservation,
               chaque retour serait aveugle et doublerait le planning. C'est le
               mécanisme que `EXG-LOT-012` annonçait sans le décrire.
  Vérification Exporter puis réimporter un fichier inchangé produit une version
               identique à celle exportée : même nombre de tâches, même arbre,
               aucun doublon.
  Source       lotissement v0.1, E14 (#326)
```

```
EXG-MSP-005 — DOIT — L'identifiant de ligne d'un fichier exporté est un **rang
d'affichage**, recalculé à chaque export. Il ne désigne rien.
  Motif        MS Project affiche un numéro de ligne qui suit l'ordre courant.
               Le prendre pour une identité ferait dépendre la réconciliation de
               l'ordre de l'arbre, qu'un simple déplacement change.
  Vérification Réordonner l'arbre change les numéros de ligne exportés sans
               affecter aucune réconciliation.
  Source       E9-02 (#147)
```

### 17.3 Ce qu'un retour modifie

```
EXG-MSP-006 — DOIT — Le contenu du fichier définit la version produite : une
tâche absente du fichier est absente de cette version. Les versions antérieures
la conservent.
  Motif        C'est le comportement additif et idempotent, et il reste légitime
               ici — contrairement au squelette, dont il a été retiré
               (`EXG-LOT-006`). La différence est que l'utilisateur a
               délibérément supprimé la tâche dans MS Project ; son intention est
               explicite, là où corriger un lotissement ne dit rien du planning.
  Vérification Supprimer une tâche dans le fichier puis réimporter produit une
               version sans elle, sans toucher aux versions précédentes.
  Source       code existant
```

```
EXG-MSP-007 — DOIT — La place d'une tâche dans l'arbre est déduite de son
numéro hiérarchique.
  Motif        MS Project ne transporte pas de lien de parenté : la hiérarchie
               n'existe que dans la numérotation. La déduire à l'import est la
               seule façon de retrouver l'arbre.
  Vérification Un fichier dont les numéros hiérarchiques décrivent quatre niveaux
               produit un arbre de quatre niveaux.
  Source       #176, code existant
```

```
EXG-MSP-008 — DOIT — Un écart entre le calendrier du fichier et celui que
Waterfall applique est signalé à l'import, sans bloquer.
  Motif        Waterfall ignore le calendrier du fichier (`EXG-PLN-001`) : les
               durées seront donc recalculées sur le sien, et les dates peuvent
               se déplacer. Sans avertissement, l'utilisateur attribue ce
               déplacement à une erreur d'import.
  Vérification L'import d'un fichier dont le calendrier diffère produit un
               diagnostic nommant les tâches dont les dates changent.
  Source       code existant
```

```
EXG-MSP-012 — DOIT — L'import signale toute tâche dont les dates diffèrent de
celles portées par le fichier, en nommant la cause du recalcul.
  Motif        Rien ne garantit qu'un aller-retour rende les mêmes dates, même à
               données identiques : Waterfall recalcule les tâches automatiques
               sur son propre calendrier (`EXG-PLN-002`), qui ne connaît que des
               heures par jour de semaine — ni jour férié, ni fermeture
               exceptionnelle, là où MS Project en tient compte. L'écart est donc
               structurel, non accidentel. Sans signalement, l'utilisateur
               l'attribue à une erreur d'import et cesse de faire confiance à
               l'aller-retour.
  Vérification Un fichier dont une tâche franchit un jour chômé produit un
               signalement nommant cette tâche, son ancienne et sa nouvelle date.
  Source       arbitrage 2026-09-13
```

Il n'est donc pas un aveu de faiblesse mais le prix d'une convergence : seul le
**premier** import dérive, et une fois le calendrier de Waterfall en place des
deux côtés, l'aller-retour est stable.

```
EXG-MSP-014 — DOIT — Un import présente l'écart qu'il produirait **avant**
d'écrire quoi que ce soit, et n'écrit qu'après confirmation. L'écart nomme
chaque ligne de coût qui disparaîtrait, avec son libellé, sa nature et son
montant courant.
  Motif        Le réimport supprime le sous-arbre d'une tâche absente du fichier,
               lignes de coût comprises (`EXG-MOD-020`). C'est le comportement
               voulu, mais c'est aussi le seul geste du produit qui détruit du
               travail de chiffrage sans que l'utilisateur l'ait demandé
               explicitement : il a demandé un import, pas une suppression. La
               confirmation ne suffit pas si elle porte sur un volume — « cent
               douze tâches modifiées » ne dit pas ce qu'on perd. Nommer les
               montants est ce qui transforme un accord de principe en décision
               prise.
  Vérification Un fichier dont une tâche chiffrée a disparu produit un écart
               nommant cette ligne et son montant, et le brouillon reste
               rigoureusement inchangé tant que la confirmation n'est pas donnée.
  Source       revision v0.1, planning acceptance #14
```

Une conséquence est à connaître, et elle ne concerne pas l'échange. Un calendrier
sans jour chômé rend les dates de Waterfall **légèrement optimistes** : une tâche
qui franchit une période de fermeture se termine en réalité plus tard que ce qui
est affiché.

Ce biais est **systématique**, et c'est ce qui le rend acceptable. Valeur
planifiée, valeur acquise et dates de référence sont toutes calculées sur le même
calendrier : l'erreur est identique au numérateur et au dénominateur, et elle
s'annule dans les indices. Un projet n'apparaît donc ni en avance ni en retard
du fait des jours chômés — seules ses **dates absolues** sont optimistes. C'est
une raison de fond, et non une tolérance : ce que le produit sert à mesurer n'est
pas affecté.

Il faut simplement ne pas lire une date de fin comme un engagement au jour près.
Un calendrier porteur de jours d'exception reste hors périmètre, et pour une
raison qui n'est pas la difficulté : il n'existe pas de source fiable. Les
calendriers des fichiers importés sont rarement paramétrés, donc variables d'un
fichier à l'autre, ce qui échangerait une erreur connue et constante contre une
erreur variable et invisible ; et les absences individuelles supposeraient un
modèle de personnes que Waterfall n'a pas, ses calendriers étant attachés à des
rôles.

Ce signalement est aussi le filet de sécurité d'`EXG-MSP-011`. MS Project peut
replanifier à partir des ressources — une affectation modifiée y déplace des
dates. Ces dates-là, elles, reviennent. Une décision prise sur les ressources
influencerait donc le planning par ce canal, alors même que l'affectation est
ignorée ; c'est ce rapport de dates qui le rend visible.

### 17.4 Ce que l'export produit

```
EXG-MSP-009 — DOIT — L'export porte les tâches, leurs liens de précédence et le
calendrier que Waterfall applique.
  Motif        L'asymétrie du calendrier — exporté mais jamais importé — est la
               décision qui fait **converger** l'aller-retour. Au premier import,
               les dates sont recalculées sur le calendrier de Waterfall et
               l'écart est signalé (`EXG-MSP-012`). Dès le premier export, MS
               Project reçoit ce calendrier et planifie dessus : les deux outils
               calculent alors la même chose, et les passes suivantes ne
               déplacent plus aucune date, les écarts résiduels portant sur la
               conversion des durées en minutes. Importer le calendrier du
               fichier produirait l'effet inverse — deux référentiels vivants,
               divergeant à chaque échange.
  Vérification Un fichier exporté s'ouvre dans MS Project en affichant les mêmes
               dates que Waterfall ; un aller-retour ultérieur ne déplace aucune
               date.
  Source       code existant, arbitrage 2026-09-13
```

```
EXG-MSP-013 — DOIT — La description d'une tâche est exportée dans les notes du
fichier. À l'import, une note alimente la description d'une tâche qui n'en a
pas ; elle n'écrase jamais une description existante.
  Motif        Exporter la description sert à qui lit le planning dans MS
               Project, et l'importer au premier passage évite de perdre le
               travail documentaire de celui qui a construit le fichier — c'est le
               moment où l'accepter ne coûte rien. Ne jamais écraser ensuite,
               parce que la description est une donnée de projet
               (`EXG-MOD-024`) : un réimport la réécrirait à partir d'un fichier
               qui, lui, n'a pas suivi les corrections faites dans Waterfall.
  Vérification Une tâche sans description reçoit la note du fichier ; une tâche
               qui en a une la conserve après réimport, même si le fichier en
               porte une autre.
  Source       arbitrage 2026-09-13
```

```
EXG-MSP-010 — DOIT — L'export porte la **charge** — les rôles et leurs heures —
et jamais la **valorisation** : ni taux, ni montant, ni rattachement à un
sous-projet.
  Motif        La coupe est celle que fait déjà le vocabulaire (`EXG-VOC-010`) :
               la charge se raisonne en heures, le coût en euros, et seule la
               première a un équivalent dans le format. Exporter une valorisation
               inviterait à la modifier là où elle ne peut pas revenir, et le
               détail financier relève de Waterfall.
  Vérification Un fichier exporté porte les affectations en heures et aucun
               montant.
  Source       devis v0.1, arbitrage 2026-09-13
```

Deux précisions sur ce que l'utilisateur verra, pour que l'écart ne soit pas pris
pour une anomalie. Les ressources exportées sont des **rôles**, non des
personnes : le fichier montre « un développeur, quatre cents heures », et non un
nom. Et les colonnes de coût de MS Project afficheront zéro, faute de taux — ce
zéro ne dit rien du projet.

```
EXG-MSP-011 — DOIT — Les affectations exportées ne sont jamais réimportées. Une
modification faite dans MS Project sur une ressource ou une affectation est
ignorée, et l'import le signale — **seulement** lorsqu'elle diffère de ce qui
avait été exporté.
  Motif        Exporter la charge sert à qui travaille surtout dans MS Project ;
               la réimporter ferait de MS Project la source des affectations, que
               le devis seul détermine. Restreindre le signalement aux écarts
               réels est ce qui le distingue d'une clause de style : un message
               affiché à chaque import cesse d'être lu, et n'avertit donc plus
               personne le jour où il aurait fallu.
  Vérification Un aller-retour sans modification n'émet aucun signalement ; une
               affectation modifiée dans le fichier en produit un, la nommant.
  Source       arbitrage 2026-09-13
```

---

## 18. Droits, partage et organisation

**Statut : partiel.** Deux précisions du tableau des rôles restent à confirmer
(18.6).

Ce chapitre relève de la v1.0 (1.3) : un produit multi-utilisateurs sans
habilitations n'est pas exploitable. Le report décidé le 2026-09-06 portait sur
l'implémentation avant le MVP, pas sur le périmètre de la première version
utilisable.

Le modèle tient en une phrase : **les droits s'additionnent, ils ne se
retranchent jamais**.

### 18.1 Trois portées, additives

```
EXG-DRO-001 — DOIT — Un droit s'accorde selon trois portées : la **plateforme**,
un **nœud d'organisation** avec cascade à ses descendants, et l'**appartenance
explicite à un projet**. Les droits obtenus par ces trois voies s'additionnent ;
aucune ne retire ce qu'une autre accorde.
  Motif        L'addition seule rend le système explicable. Avec des refus, la
               question « pourquoi cette personne ne peut-elle pas ? » exige de
               chercher une interdiction qui peut être n'importe où ; sans eux,
               elle se répond en énumérant ce qui a été accordé. Un modèle
               d'habilitation qu'on ne sait pas expliquer finit par être
               contourné, et c'est ainsi qu'on accorde trop.
  Vérification Retirer un droit se fait en retirant une attribution, jamais en
               ajoutant une exception.
  Source       analyse du 2026-09-06
```

```
EXG-DRO-002 — DOIT — L'appartenance explicite à un projet est la voie ouverte
aux intervenants transverses, qui travaillent hors de leur branche
d'organisation.
  Motif        Sans elle, faire participer un expert d'un autre service
               obligerait à lui accorder toute sa branche d'origine ou toute la
               plateforme. C'est exactement le mécanisme par lequel un modèle
               trop rigide produit des droits trop larges.
  Vérification Un utilisateur sans droit sur le nœud d'organisation d'un projet y
               accède si et seulement s'il y est explicitement rattaché.
  Source       analyse du 2026-09-06
```

### 18.2 L'arbre d'organisation

```
EXG-DRO-003 — DOIT — L'arbre qui porte les habilitations est le **même** que
celui qui structure les rôles de ressource. Il n'existe pas deux arbres
d'organisation.
  Motif        Deux arbres décrivant la même entreprise divergent, et l'on ne
               sait alors plus lequel fait foi. L'arbre des ressources existe
               déjà et sert de rattachement aux rôles ; il suffit.
  Vérification Créer un service dans l'organisation le rend disponible aux deux
               usages, sans seconde saisie.
  Source       analyse du 2026-09-06
```

```
EXG-DRO-004 — DOIT — Un droit accordé sur un nœud vaut pour tous ses
descendants, présents et à venir.
  Motif        Sans cascade, un responsable de département perdrait la visibilité
               sur chaque sous-service créé après son habilitation, et le manque
               ne se verrait qu'au moment où il chercherait un projet absent de
               sa liste.
  Vérification Créer un sous-service sous un nœud habilité n'exige aucune
               nouvelle attribution.
  Source       analyse du 2026-09-06
```

Le mot **rôle** désigne ici un ensemble de permissions, à ne pas confondre avec
le rôle de ressource qui porte un taux horaire (`EXG-VOC-009`). Les deux
coexistent dans les mêmes écrans, et leur homonymie est le premier piège du
chapitre.

### 18.3 Permissions et rôles

```
EXG-DRO-005 — DOIT — Le catalogue des permissions est **figé dans le code**. Les
rôles d'habilitation, qui les combinent, sont configurables.
  Motif        Une permission est un point du code où une action est contrôlée :
               en inventer une à l'exécution ne contrôlerait rien, puisque aucun
               code ne la consulterait. Un rôle, au contraire, est une convention
               d'organisation qui varie d'une entreprise à l'autre et doit se
               définir sans livraison.
  Vérification Aucun écran ne permet de créer une permission ; tout écran de
               rôle permet d'en composer une combinaison.
  Source       analyse du 2026-09-06
```

```
EXG-DRO-006 — DOIT — Un projet n'a pas de propriétaire unique. L'accès résulte
des attributions, et la disparition d'un utilisateur ne rend aucun projet
inaccessible.
  Motif        Un propriétaire unique rend le projet invisible à tous les autres
               et orphelin lorsque la personne quitte l'entreprise — sur un outil
               dont les projets vivent six ans, le cas n'est pas rare, il est
               certain.
  Vérification Désactiver un utilisateur ne retire l'accès à aucun projet pour
               les autres.
  Source       analyse du 2026-09-06
```

### 18.4 Le rattachement d'un utilisateur

```
EXG-DRO-011 — DOIT — Un utilisateur peut être rattaché à l'organisation : à
aucun nœud, à un, ou à plusieurs, et il porte le ou les rôles de ressource qu'il
exerce.
  Motif        Sans ce rattachement, rien de ce chapitre ne fonctionne. « Les
               projets qui concernent un manager », « le service dont dépend une
               personne », « les ressources d'une équipe » supposent toutes un
               lien qui n'existe nulle part aujourd'hui : un compte est une
               adresse et un mot de passe, à côté de l'arbre plutôt que dedans.

               Le rattachement est **facultatif** parce qu'un compte existe avant
               d'être placé — un administrateur, un prestataire — et **multiple**
               parce qu'une organisation matricielle place les gens à plusieurs
               endroits à la fois. L'imposer unique reproduirait dans les droits
               une hiérarchie que l'entreprise n'a pas.
  Vérification Un compte sans rattachement est valide ; un compte rattaché à deux
               nœuds l'est aussi, et on peut énumérer les utilisateurs d'un nœud
               ainsi que les rôles de chacun.
  Source       arbitrage 2026-09-13
```

```
EXG-DRO-013 — DOIT — Le rattachement à un nœud ne confère par lui-même aucun
droit. Il délimite la **portée** d'un rôle d'habilitation accordé par ailleurs.
  Motif        C'est ce qui permet à un compte d'exister dans l'organisation sans
               rien voir. Un administrateur est une personne, donc un membre d'un
               service ; si l'appartenance valait accès, il hériterait
               automatiquement de tout ce que son service touche, et la
               séparation entre administrer la plateforme et lire les affaires
               serait impossible à tenir.
  Vérification Rattacher un utilisateur à un nœud ne lui donne accès à rien tant
               qu'aucun rôle ne lui est accordé sur cette portée.
  Source       arbitrage 2026-09-13
```

### 18.5 Le projet déclare les services qu'il mobilise

```
EXG-DRO-012 — DOIT — Un projet déclare, dans son onglet Général, les nœuds
d'organisation dont il a besoin. Cette déclaration ouvre l'accès aux
utilisateurs rattachés à ces nœuds, selon leur rôle d'habilitation.
  Motif        C'est une quatrième voie d'accès, et elle résout un cercle que les
               trois autres laissent entier. Un manager doit pouvoir saisir les
               charges de son service au chiffrage ; s'il fallait pour cela qu'une
               de ses ressources y soit déjà affectée, personne ne pourrait faire
               la première affectation. La déclaration précède l'affectation et la
               rend possible.

               Elle convient aussi à une organisation **matricielle**, où un chef
               de projet puise dans plusieurs services : le projet en nomme
               plusieurs, sans que personne ait à administrer un droit
               utilisateur par utilisateur.
  Vérification Ajouter un service aux besoins d'un projet donne accès à ses
               managers ; l'en retirer le referme, sans toucher aux appartenances
               explicites.
  Source       arbitrage 2026-09-13
```

### 18.6 Les rôles d'habilitation

Quatre rôles couvrent l'usage courant. Ils composent les permissions du
catalogue ; ils ne sont pas des portées, mais ce qu'on accorde sur une portée.

**Ce tableau est une configuration livrée, non le modèle.** Ces règles évolueront
et différeront d'une entreprise à l'autre : une installation neuve les trouve en
place, et rien n'empêche de les modifier ou d'en définir d'autres. C'est la
raison d'être d'`EXG-DRO-005` — le catalogue de permissions est figé, leurs
combinaisons ne le sont pas.

| Rôle | Administration | Management et paramétrage métier | Projets |
|---|---|---|---|
| **Administrateur** | lecture et écriture | — | — |
| **Manager** | — | lecture et écriture | lecture sur les projets qui mobilisent son service ; écriture sur le chiffrage pour y porter ses charges |
| **Chef de projet** | — | — | lecture et écriture sur les siens |
| **Contributeur** | — | — | lecture sur les projets qui mobilisent son service |

Deux points de ce tableau restent à confirmer, et ils sont signalés plutôt que
tranchés.

**L'écriture du manager sur le chiffrage est-elle bornée à sa part ?** Sur un
projet matriciel, un accès non borné laisserait le responsable d'un service
modifier les charges d'un autre. Le borner est souhaitable, mais moins simple
qu'il n'y paraît : un manager peut tenir plusieurs nœuds répartis n'importe où
dans l'arbre, si bien que sa portée est une **réunion de sous-arbres** et non un
sous-arbre. Le test n'est donc pas une comparaison d'ascendance, et c'est ce coût
qu'il faut peser.

**Dépend-elle du statut du projet ?** Elle a été formulée « en phase de
chiffrage ». Peut-être n'est-ce pas nécessaire : un devis validé est de toute
façon immuable pour tous (`EXG-DEV-009`). Mais chaque revue mensuelle crée un
nouveau chiffrage à l'état de brouillon, et il faut dire si le manager y écrit
aussi.

```
EXG-DRO-014 — DOIT — Aucun contrôle d'accès ne teste un rôle. Tout contrôle
teste une permission.
  Motif        C'est ce qui rend la configurabilité réelle plutôt que déclarée.
               Un seul test de rôle écrit dans le code — « si l'utilisateur est
               manager » — fige ce rôle dans le produit : le renommer, le
               scinder, ou en créer un autre cesse alors de fonctionner, et rien
               ne le signale avant qu'un client ne s'en plaigne.
  Vérification Aucune expression du code ne compare un rôle d'habilitation à une
               valeur littérale.
  Source       arbitrage 2026-09-13
```

**L'exclusivité de l'administrateur** n'appelle pas de règle : la convention
suffit, `EXG-DRO-013` la rendant tenable. Un administrateur figure dans l'arbre
comme tout le monde, mais son appartenance ne lui donne rien tant qu'aucun rôle
métier ne lui est accordé.

### 18.7 Ce que voit celui qui n'a pas le droit

```
EXG-DRO-007 — DOIT — Un refus est explicite et nommé. Aucune section, aucune
commande ne disparaît silencieusement faute de droit.
  Motif        Une entrée escamotée laisse l'utilisateur sans moyen de savoir que
               la fonction existe, ni à qui la demander (`EXG-NAV-001`). Elle
               transforme un problème d'habilitation, qui se règle en une
               minute, en un manque supposé du produit.
  Vérification Une section ou une action interdite reste visible et énonce, au
               clic, le droit qui manque.
  Source       arbitrage maquette, analyse du 2026-09-06
```

```
EXG-DRO-008 — DOIT — Tout contrôle de droit est appliqué par le serveur, sur
chaque requête. Le masquage dans l'interface est un confort, jamais une
protection.
  Motif        Même raison qu'`EXG-CYC-009` : une garde d'interface protège
               l'utilisateur attentif, pas un appel direct. Et ici l'enjeu n'est
               pas la cohérence des données mais la confidentialité — voir un
               portefeuille, c'est voir la marge de projets qu'on ne conduit pas.
  Vérification Toute requête sur une ressource interdite est refusée, quel que
               soit le point d'entrée.
  Source       analyse du 2026-09-06
```

### 18.8 Rendre les droits vérifiables

```
EXG-DRO-009 — DOIT — Pour un projet donné, l'application sait dire qui y a accès
et **par quelle voie** : plateforme, nœud d'organisation, appartenance explicite,
ou déclaration de besoin du projet (`EXG-DRO-012`).
  Motif        Avec quatre portées additives et une cascade, le droit effectif
               d'une personne ne se lit dans aucune attribution prise isolément.
               Sans cette vue, personne ne peut vérifier qu'un projet sensible
               n'est pas visible de toute l'entreprise — et la question se pose
               toujours après coup, lorsqu'il est trop tard pour la poser.
  Vérification L'écran d'un projet énumère les utilisateurs qui y accèdent et
               l'origine de chaque accès.
  Source       arbitrage 2026-09-13
```

```
EXG-DRO-010 — DOIT — Réciproquement, pour un utilisateur donné, l'application
sait dire à quoi il accède et par quelle voie.
  Motif        C'est la question que pose un départ, une mutation ou un audit.
               La reconstituer à la main suppose de parcourir l'arbre
               d'organisation et toutes les appartenances, ce que personne ne
               fait.
  Vérification La fiche d'un utilisateur énumère ses attributions et leur portée.
  Source       arbitrage 2026-09-13
```

```
EXG-DRO-015 — DOIT — Une permission porte sur un **domaine** et sur la **lecture
ou l'écriture** de ce domaine. Aucune ne porte sur un acte isolé : un acte
irréversible relève de l'écriture sur son domaine, et sa protection est une
**confirmation explicite** qui nomme ce que l'acte rend définitif et ce qu'il
fait perdre.
  Motif        La maille par domaine est ce qui rend le catalogue composable :
               un rôle se définit en accordant des domaines, non en cochant des
               gestes. Une permission par action serait complète et
               incomposable — il faudrait la revoir à chaque geste ajouté, et
               aucune organisation ne saurait décrire ses rôles avec.

               Séparer les actes irréversibles de l'écriture ordinaire ne
               protégerait rien de plus. Qui écrit sur un domaine finit toujours
               par recevoir le droit d'y conclure, et la combinaison « écrire
               sans pouvoir clore » n'a pas d'usage identifié ; on aurait doublé
               le catalogue pour une distinction que personne ne configure.

               Le risque réel n'est pas qu'une personne non autorisée agisse,
               c'est qu'une personne autorisée agisse sans avoir vu ce qu'elle
               engageait. C'est une affaire d'écran et non d'habilitation, et la
               confirmation la traite là où elle se pose — à condition de nommer
               les conséquences : une question qui se borne à demander si l'on
               est sûr s'acquitte sans être lue, et ne protège de rien.
  Vérification Le catalogue compte quatorze permissions et aucune ne désigne un
               acte isolé. Chaque acte irréversible — clôture d'un projet,
               validation d'une révision — demande une confirmation qui énonce ce
               qui devient définitif.
  Source       arbitrage 2026-09-15
```

**Les domaines sont ceux de l'architecture d'information** (chapitre 7), et le
catalogue n'en invente aucun : trois pour les sections qui ne sont pas un projet,
cinq pour les onglets d'un projet.

| Domaine | Ce qu'il couvre | Chapitre |
|---|---|---|
| **Administration** | Comptes, sauvegarde et restauration, trace, santé du système | 20 |
| **Paramètres** | Le référentiel métier | 19 |
| **Management** | Portefeuille et plan de charge agrégé | 16 |
| **Structure du projet** | Identité, statut, sous-projets, lotissement, déclaration des nœuds d'organisation | 6, 8, 9 |
| **Planning** | L'arbre et ses facettes de planification | 10 |
| **Chiffrage** | Le devis et le reste à engager | 11, 12 |
| **Coûts réels** | L'import, les pièces et le périmètre | 13 |
| **Analyse** | Les restitutions du projet | 15 |

Deux domaines ne portent qu'un sens d'accès. **Analyse** ne se lit que : une
restitution ne se modifie pas. **Management** non plus : la section n'agrège que
ce que les projets produisent et le reprend sans recalcul (`EXG-CHA-003`), et la
seule donnée propre qu'elle affiche — la capacité d'un rôle — s'écrit aux
Paramètres (`EXG-PAR-004`). Leur écriture n'existe donc pas dans le catalogue,
qui compte **quatorze permissions** : huit domaines, deux sens, moins ces deux
écritures.

**La portée est une dimension distincte de la permission.** Un domaine dit *quoi*,
la portée dit *sur quels objets* : plateforme, nœud d'organisation, appartenance
explicite, déclaration de besoin (`EXG-DRO-009`). Le bornage demandé en 18.6 —
l'écriture d'un manager sur le chiffrage limitée à sa part — relève de la portée
et non d'une permission plus fine ; il ne contredit donc pas la maille
ci-dessus.

### 18.9 Ce qui reste ouvert

**Les deux points du tableau des rôles** énumérés en 18.6.

---

## 19. Paramètres

**Statut : décidé.** Chapitre rédigé d'après l'implémentation existante et
soumis à relecture (1.4).

Paramètres porte le **référentiel métier** : ce qui est commun à tous les
projets et qu'aucun projet ne redéfinit pour lui-même. C'est la contrepartie de
tout ce qui précède. Un chiffrage ne se compare d'un projet à l'autre que si les
taux, les calendriers et les natures de coût sont les mêmes ; un plan de charge
agrégé (chapitre 16) n'a de sens que si les rôles le sont aussi. Le référentiel
est ce qui fait d'un ensemble de projets un portefeuille.

`EXG-NAV-002` lui attribue l'organisation, les coûts et les calendriers, et lui
refuse la gestion des utilisateurs, qui relève d'Administration (chapitre 20).
Son administration relève de la permission de paramétrage métier, portée par le
rôle de manager dans la configuration livrée (18.6).

### 19.1 Ce que Paramètres porte

```
EXG-PAR-001 — DOIT — Paramètres porte cinq référentiels, et eux seuls : l'arbre
d'organisation, les rôles de ressource, les natures et catégories de coût, les
taux horaires et les calendriers. Aucun n'est redéfini au niveau d'un projet.
L'inflation n'en fait pas partie : elle est une hypothèse de projet
(`EXG-DEV-020`).
  Motif        Un référentiel qu'un projet pourrait redéfinir cesse d'être un
               référentiel : deux projets chiffrés au même rôle ne seraient plus
               comparables, et le plan de charge agrégé additionnerait des heures
               de natures différentes sans que rien ne le signale. La liste est
               close pour la même raison : tout ce qui s'ajouterait ici sans y
               être nommé échapperait au contrôle de complétude d'`EXG-CYC-015`.
  Vérification Aucun écran de projet ne permet de créer ni de modifier l'un de
               ces cinq objets ; tous s'y choisissent dans une liste. Le
               coefficient d'inflation, lui, se saisit sur le projet.
  Source       EXG-NAV-002, models/resources.py
```

### 19.2 L'organisation

```
EXG-PAR-002 — DOIT — L'organisation est un arbre de nœuds portant chacun un code
unique et un libellé. Un nœud en porte d'autres, sans limite de profondeur.
  Motif        Le même arbre sert à trois choses : rattacher les rôles de
               ressource (`EXG-PAR-003`), porter les habilitations et leur
               cascade (chapitre 18), et recevoir la déclaration de besoin d'un
               projet (`EXG-DRO-012`). Un arbre unique est ce qui rend ces trois
               lectures cohérentes ; trois arbres parallèles divergeraient dès la
               première réorganisation, et c'est le droit d'accès qui en
               souffrirait le premier.
  Vérification Un nœud accepte des enfants à toute profondeur, et son code est
               refusé s'il est déjà porté par un autre nœud.
  Source       models/resources.py, chapitre 18
```

### 19.3 Les rôles de ressource et leur capacité

```
EXG-PAR-003 — DOIT — Un rôle de ressource se rattache à un nœud d'organisation,
à une catégorie de coût et à un calendrier. Les trois rattachements sont
obligatoires.
  Motif        Chacun répond à une question que le chiffrage pose. Le nœud dit
               quel service fournit le travail : c'est par lui que le plan de
               charge se ventile et que la déclaration de besoin ouvre l'accès.
               La catégorie dit combien l'heure coûte, le taux y étant attaché
               (`EXG-PAR-006`). Le calendrier dit quand le travail est possible.
               Un rôle privé de l'un des trois produirait une ligne de devis
               incalculable, et l'échec se manifesterait au chiffrage, loin de sa
               cause.
  Vérification Créer un rôle sans nœud, sans catégorie ou sans calendrier est
               refusé, et le refus nomme le rattachement manquant.
  Source       models/resources.py
```

```
EXG-PAR-004 — DOIT — Un rôle porte une **capacité** : un nombre d'heures
disponibles **par mois**, et l'effectif auquel il correspond. Un rôle ne porte
qu'une capacité, et elle ne varie pas dans le temps.
  Motif        C'est la grandeur qu'`EXG-CHA-007` trace comme niveau constant, et
               qu'aucun chapitre ne produisait. Elle est détenue au rôle parce
               que c'est le niveau auquel l'arbitrage se prend — on recrute un
               rôle, on ne recrute pas un projet ; `EXG-ANA-015` refuse d'ailleurs
               de la rapporter à un projet, qui n'en réserve aucune part.

               Son invariance est délibérée et non une approximation. Une
               capacité mensualisée sur dix ans serait une prévision d'effectif :
               il faudrait la tenir à jour, personne ne le ferait, et un plan de
               charge tracé contre une capacité périmée serait pire qu'un plan
               tracé sans capacité. L'unité mensuelle est ce qui permet d'en
               déduire toutes les mailles d'affichage sans en saisir aucune
               autre.
  Vérification Le niveau tracé par le plan de charge est la somme des capacités
               des rôles retenus par le filtre, ramenée à la maille affichée
               (`EXG-CHA-007`) ; il ne varie pas d'une période à l'autre.
  Source       models/resources.py, arbitrage 2026-09-13
```

### 19.4 Natures, catégories et taux

Le chapitre 11 énumère quatre natures de ligne — main-d'œuvre, fourniture,
frais, unité d'œuvre (11.2). Le référentiel les porte sur deux niveaux.

```
EXG-PAR-005 — DOIT — Un **type de coût** porte un code, un libellé et sa nature.
Une **catégorie de coût** se rattache à un type et porte un **code comptable
unique**.
  Motif        Les deux niveaux ne sont pas un raffinement. Le type est ce que le
               devis ventile et affiche (`EXG-DEV-018`) ; la catégorie est ce qui
               porte le taux, et ce par quoi la comptabilité nomme la dépense. Un
               niveau unique obligerait à choisir entre une ventilation lisible et
               un plan comptable fidèle, et c'est la fidélité qui céderait, le
               plan comptable n'étant pas négociable du côté de Waterfall
               (`EXG-CRE-003`).
  Vérification Un code comptable déjà employé est refusé ; chaque catégorie
               relève d'exactement un type de coût.
  Source       models/resources.py
```

```
EXG-PAR-006 — DOIT — Un taux horaire est donné par catégorie de coût, par année
et dans une devise. Un couple catégorie-année ne porte qu'un taux.
  Motif        Le chiffrage n'emploie que le taux de son année de référence
               (`EXG-DEV-005`) ; les années suivantes sont atteintes par
               l'inflation, non par un taux futur que personne ne saisira. Le taux
               reste néanmoins annuel : un chiffrage créé l'année suivante doit
               partir d'une base constatée, et non d'une base que l'inflation
               aurait projetée depuis une année de plus en plus lointaine.
  Vérification Un devis créé en une année donnée ne réclame aucun taux d'une
               année postérieure à la sienne.
  Source       models/resources.py, EXG-DEV-005
```

```
EXG-PAR-007 — ABANDONNÉE — l'inflation n'est pas un référentiel commun.
  Motif        Elle plaçait le coefficient dans Paramètres, par année et pour
               toute l'installation. La question 12 est tranchée dans l'autre
               sens : l'inflation est une hypothèse d'affaire, portée par le
               projet, et c'est un coefficient unique et non une série
               (`EXG-DEV-020`). Ce que cette exigence protégeait — une seule
               vérité pour un même fait — reste vrai à l'échelle où le fait
               existe désormais, celle du projet.
```

### 19.5 Les calendriers

```
EXG-PAR-008 — DOIT — Un calendrier donne, pour chacun des sept jours de la
semaine, un nombre d'heures travaillées, et un nombre de semaines travaillées par
an. Un calendrier de l'installation est désigné par défaut, et un seul.
  Motif        C'est par le calendrier qu'une durée devient des heures, et des
               heures un coût. Le défaut unique est ce qui rend `EXG-CYC-015`
               vérifiable : « le calendrier par défaut porte au moins un jour
               ouvré » n'a de sujet que s'il n'en existe qu'un. Le nombre de
               semaines travaillées par an est une donnée distincte du détail
               hebdomadaire, et non sa conséquence : les congés et les jours
               fériés n'y figurent pas, et cinquante-deux semaines pleines
               surestimeraient l'année d'environ un dixième.
  Vérification Désigner un calendrier par défaut retire cette qualité au
               précédent ; il n'en existe jamais deux, ni aucun.
  Source       models/resources.py, EXG-CYC-015
```

```
EXG-PAR-009 — DOIT — Aucun calendrier n'est créé ni modifié par un import.
  Motif        Corollaire d'`EXG-PLN-001`. Le calendrier d'un fichier MS Project
               décrit l'organisation de celui qui l'a produit ; l'écrire dans le
               référentiel commun le propagerait à tous les projets, dont ceux qui
               n'ont rien à voir avec ce fichier. Un import est le seul geste du
               produit qui apporte des données d'origine étrangère, et le
               référentiel est le seul endroit où une erreur se propage à tout le
               portefeuille : leur rencontre est interdite.
  Vérification Après un import portant un calendrier, le référentiel compte les
               mêmes calendriers qu'avant, inchangés.
  Source       EXG-PLN-001
```

### 19.6 Règles communes au référentiel

```
EXG-PAR-010 — DOIT — Tout objet du référentiel se désactive, jamais ne se
supprime. Un objet désactivé cesse d'être proposé à la saisie et reste lisible
partout où il est déjà employé.
  Motif        Fermer l'avenir sans falsifier le passé. C'est la règle
               qu'`EXG-SPR-005` applique aux sous-projets, `EXG-DEV-011` aux
               catégories de coût et `EXG-ADM-001` aux comptes ; elle vaut ici
               pour toute la famille. Supprimer un rôle rendrait illisibles les
               devis qui l'emploient, y compris ceux qui sont validés et que
               personne ne peut donc corriger (`EXG-DEV-009`).
  Vérification Aucun écran ni aucun service ne supprime un objet du référentiel ;
               désactivé, il disparaît des listes de saisie sans changer aucun
               montant déjà calculé.
  Source       arbitrage 2026-09-13
```

```
EXG-PAR-011 — DOIT — Modifier le référentiel ne modifie aucune révision validée.
  Motif        C'est la condition pour qu'un budget de référence reste une
               référence. Un taux corrigé en cours d'année déplacerait sinon le
               budget de tous les projets déjà pilotés, et l'écart constaté le
               mois suivant ne se distinguerait pas d'une dérive réelle. Une
               révision validée est immuable (`EXG-DEV-009`) : elle porte les
               valeurs qui ont servi à la calculer — taux horaire et coefficient
               d'inflation compris — et non un renvoi vers elles.
  Vérification Changer un taux ne change aucun montant d'une révision validée ; le
               même changement est pris en compte au calcul suivant d'un
               brouillon.
  Source       arbitrage 2026-09-13
```

### 19.7 Ce qui reste ouvert

Rien. La seule question qui portait sur ce chapitre — où l'inflation est détenue
— est tranchée : elle ne l'est pas ici, mais par le projet (`EXG-DEV-020`).

---

## 20. Administration

**Statut : décidé.** Chapitre rédigé sans séance de cadrage et soumis à
relecture (1.4).

L'administration ne fait pas partie du métier, et c'est sa difficulté : elle n'a
pas d'utilisateur qui la réclame, et se découvre le jour où elle manque. Le
critère d'inclusion de la v1.0 (1.3) tranche à sa place — on n'exploite pas un
système dont on ne sait pas restaurer les données, ni dont on ne peut pas retirer
l'accès à quelqu'un qui est parti.

Elle recouvre quatre choses : les **comptes**, les **habilitations** définies au
chapitre 18, la **sauvegarde et la restauration**, et ce que le système dit de
lui-même. Le référentiel métier — organisation, coûts, calendriers — n'en fait
pas partie : il relève de Paramètres, et le chapitre 19 le spécifie
(`EXG-NAV-002`).

### 20.1 Les comptes

```
EXG-ADM-001 — DOIT — Un compte se désactive, jamais ne se supprime.
  Motif        C'est la même règle que pour le référentiel (`EXG-PAR-010`), les
               sous-projets (`EXG-SPR-005`) et les catégories de coût
               (`EXG-DEV-011`) : fermer l'avenir sans falsifier le passé. Ici
               s'ajoute une raison propre — un compte supprimé laisserait
               orphelines toutes les traces qui le nomment, et la question « qui
               a fait cela » deviendrait sans réponse au moment précis où elle se
               pose.
  Vérification Désactiver un compte lui retire tout accès et ne modifie aucune
               trace ni aucune donnée qu'il a produite.
  Source       arbitrage 2026-09-13
```

```
EXG-ADM-002 — DOIT — L'administration peut débloquer un compte verrouillé et
mettre fin aux sessions ouvertes d'un utilisateur.
  Motif        Le verrouillage après échecs répétés protège des tentatives
               d'intrusion ; sans déblocage, il devient une panne que personne ne
               sait réparer. Et l'on doit pouvoir couper l'accès immédiatement,
               sans attendre l'expiration naturelle d'une session — c'est ce
               qu'on cherche à faire lors d'un départ contraint.
  Vérification Un compte verrouillé redevient utilisable sur action
               d'administration ; une fin de session forcée invalide les jetons
               en cours.
  Source       arbitrage 2026-09-13
```

### 20.2 Sauvegarde et restauration

```
EXG-ADM-011 — DOIT — La sauvegarde et la restauration sont des **fonctions du
produit**. Waterfall produit lui-même une archive cohérente et sait la restaurer.
  Motif        Les données vivent dans deux systèmes indépendants. Les prendre au
               même instant ne s'obtient pas en enchaînant deux commandes, et
               c'est l'erreur qu'une procédure documentée laisse commettre sans
               rien signaler, chaque sauvegarde paraissant réussie. Waterfall est
               le seul à savoir ce qui doit être cohérent avec quoi.
  Vérification Une sauvegarde se déclenche et se restaure depuis l'application,
               sans accès au serveur.
  Source       arbitrage 2026-09-13
```

```
EXG-ADM-012 — DOIT — L'archive est récupérable hors de l'instance qui l'a
produite : téléchargeable, ou déposée sur une destination configurée.
  Motif        Une sauvegarde qui ne vit que sur le serveur sauvegardé disparaît
               avec lui. Or c'est exactement le scénario contre lequel une
               sauvegarde protège — la perte de la machine, pas la maladresse
               d'un utilisateur, qui relève de la trace et de l'immuabilité.
               Sans sortie, la fonction donne une assurance qu'elle ne couvre
               pas.
  Vérification Une archive produite est obtenue sur un autre support, et une
               instance vierge la restaure.
  Source       arbitrage 2026-09-13
```

```
EXG-ADM-003 — DOIT — Une sauvegarde couvre la base de données **et le stockage
objet** où vivent les fichiers sources des imports. Les deux sont pris au même
instant.
  Motif        L'import conserve le fichier source et son empreinte
               (`EXG-CRE-011`) dans un stockage distinct de la base. Sauvegarder l'une sans l'autre
               restituerait des références vers des objets absents, et la
               vérification d'empreinte échouerait au réimport — incomplétude qui
               ne se découvrirait qu'à la restauration, au pire moment. La
               simultanéité n'est pas un raffinement : deux sauvegardes
               indépendantes prises à quelques minutes d'écart contiennent des
               imports que l'autre ignore.
  Vérification Une restauration sur une instance vierge rend les fichiers sources
               consultables et leurs empreintes vérifiables, sans référence
               orpheline dans un sens ni dans l'autre.
  Source       E13-02 (#299), arbitrage 2026-09-13
```

```
EXG-ADM-004 — DOIT — Une sauvegarde porte sa date, la version applicative qui
l'a produite et son empreinte.
  Motif        Restaurer une sauvegarde dans une version de schéma différente est
               la façon classique de perdre les données une seconde fois. La
               version permet de refuser ; l'empreinte permet de savoir si le
               fichier est intact avant d'y engager quoi que ce soit.
  Vérification La restauration d'une sauvegarde produite par une version
               incompatible est refusée, en nommant les deux versions.
  Source       arbitrage 2026-09-13
```

```
EXG-ADM-005 — DOIT — La procédure de restauration est **éprouvée**, et la
vérification consiste à l'exécuter.
  Motif        Une sauvegarde que personne n'a jamais restaurée est une
               hypothèse, pas une garantie. C'est l'exigence la plus facile à
               satisfaire sur le papier et la seule qui compte le jour venu ;
               elle n'est donc pas tenue par un document mais par un essai.
  Vérification Une restauration est exécutée sur une instance vierge et son
               résultat comparé à l'original, avant que la v1.0 ne soit déclarée
               livrable.
  Source       arbitrage 2026-09-13
```

```
EXG-ADM-006 — DOIT — Une restauration est un acte explicite, confirmé, et tracé.
  Motif        C'est la seule opération qui remplace l'intégralité des données
               par un état antérieur. Tout ce qui a été saisi depuis la
               sauvegarde disparaît, et cela doit être énoncé avant, pas constaté
               après.
  Vérification Le dialogue de confirmation nomme la date de la sauvegarde et la
               quantité de données postérieures qui seront perdues.
  Source       arbitrage 2026-09-13
```

### 20.3 La trace

```
EXG-ADM-007 — DOIT — Le système conserve une trace datée et nominative des actes
irréversibles et des changements d'habilitation.
  Motif        Plusieurs chapitres s'appuient déjà sur elle sans l'avoir définie :
               la clôture d'un projet est définitive (`EXG-CYC-008`), un retour
               en arrière sur un achèvement « est tracé, pas absorbé
               silencieusement » (`EXG-AVA-011`), l'exclusion d'une ligne de coût
               conserve son motif et son auteur (`EXG-CRE-006`). Ces exigences
               supposent un registre qui n'existe nulle part.
  Vérification Chacun de ces actes produit une entrée nommant l'auteur, la date
               et l'objet.
  Source       arbitrage 2026-09-13
```

Cette trace ne se confond pas avec les **horodatages de ligne** — qui a créé,
qui a modifié en dernier — que le modèle de données porte par ailleurs
(chapitre 21). Les deux sont complémentaires et ne répondent pas à la même
question. Un horodatage dit qui a touché une ligne en dernier, et **efface** ceux
qui l'ont précédé ; il ne porte ni l'état antérieur, ni le motif. Or les
exigences citées plus haut demandent exactement cela : ce qu'un achèvement valait
avant qu'on y revienne, pourquoi une ligne de coût a été sortie du périmètre. Un
horodatage partout donnerait l'impression d'un registre sans en tenir lieu, et
c'est ainsi que le vrai registre ne se construit jamais.

```
EXG-ADM-008 — DOIT — La trace n'est ni modifiable ni supprimable depuis
l'application.
  Motif        Une trace qu'on peut réécrire ne prouve rien, et son existence
               donnerait une confiance que rien ne justifie. Sa purge éventuelle
               relève de l'exploitation de la base, pas d'un écran.
  Vérification Aucun endpoint ne permet de modifier ou de supprimer une entrée de
               trace.
  Source       arbitrage 2026-09-13
```

### 20.4 Ce que le système dit de lui-même

```
EXG-ADM-009 — DOIT — L'état du système distingue ce qui fonctionne de ce qui ne
fonctionne pas, en nommant la dépendance en cause.
  Motif        « Le service est indisponible » n'oriente vers aucune action.
               Savoir que c'est la base, ou le stockage des fichiers, désigne qui
               appeler. Sur un produit exploité sans équipe dédiée, c'est la
               différence entre une panne d'une heure et une panne d'une journée.
  Vérification Une dépendance interrompue est nommée dans l'état du système, et
               le rétablissement s'y voit.
  Source       code existant
```

```
EXG-ADM-010 — DOIT — L'historique des imports est consultable, avec pour chacun
sa date, son auteur, son fichier source, son issue et son rapport.
  Motif        L'import est la principale porte d'entrée des données et la
               principale source d'incompréhension : « pourquoi ce coût
               n'apparaît-il pas » se résout presque toujours en relisant le
               rapport de l'import concerné. Sans historique, la question se
               reporte sur celui qui a construit le produit.
  Vérification Chaque import figure dans l'historique avec son rapport de rejets,
               consultable après coup.
  Source       code existant
```

### 20.5 Ce qui n'en fait pas partie

Le critère d'inclusion écarte de la v1.0 la supervision continue, les alertes,
les mesures de performance et tout tableau de bord d'exploitation. Leur absence
rend l'exploitation moins confortable, non impossible : c'est la définition même
de ce qui relève d'une version ultérieure (1.3).

---

## 21. Modèle de données cible

**Statut : partiel.** Le cœur est arrêté et ce chapitre l'absorbe. Ce que le
modèle doit encore recevoir est recensé à l'annexe C, avec le reste des écarts —
l'attribut d'inflation du projet en fait partie.

Ce chapitre absorbe les décisions de `revision-v0.1-specification.md`, sans en
reprendre le schéma : les tables et leurs colonnes relèvent de l'implémentation,
que ce document ne décrit pas (annexe A). Ce qui figure ici est ce dont dépend le
comportement décrit par les chapitres précédents.

Ce document-là reste vivant tant qu'E14 se livre : il porte le détail dont
l'implémentation a besoin, et sa mise à jour suit les livraisons. Le présent
chapitre porte ce qui doit survivre à cette clôture.

### 21.1 Une révision porte tout

```
EXG-MOD-001 — DOIT — Une **révision** est une version complète du projet : son
arbre, sa planification et son chiffrage. Il n'existe pas de version de planning
séparée d'un devis.
  Motif        Deux objets versionnés séparément autorisent qu'un chiffrage
               désigne un planning autre que le sien, et obligent à maintenir
               leur cohérence par des gardes. Un objet unique rend l'incohérence
               inexprimable plutôt que surveillée.
  Vérification Aucun chiffrage ne référence une structure de tâches autre que la
               sienne.
  Source       E14 (#326)
```

```
EXG-MOD-002 — DOIT — Une variante de chiffrage est une **variante complète de
révision**, donc un second arbre.
  Motif        Deux chiffrages sur un même arbre supposeraient que l'arbre ne
               change pas d'une variante à l'autre, ce qui est rarement le cas :
               chiffrer autrement, c'est presque toujours découper autrement.
  Vérification Créer une variante produit une révision entière, et modifier son
               arbre ne touche pas l'original.
  Source       E14 (#326)
```

```
EXG-MOD-023 — DOIT — Une révision porte un **nom** donné par l'utilisateur, et
une description facultative. Le nom est proposé par défaut et modifiable ; il ne
remplace jamais le numéro de version comme identifiant.
  Motif        Un projet de six ans accumule des dizaines de révisions, et
               « révision 47 » ne désigne rien. Le besoin est le plus aigu sur les
               variantes, qui coexistent à l'état de brouillon (`EXG-MOD-002`) :
               choisir entre deux variantes distinguées par leur seul numéro,
               c'est choisir à l'aveugle. Le nom est proposé — la date de la revue
               suffit le plus souvent — parce qu'un nom obligatoire mais vide à
               remplir soixante-dix fois finirait par être expédié, et un nom
               facultatif finirait par rester vide.
  Vérification Toute vue qui fait choisir une révision — désignation d'un couple
               de référence, historique des revues, copie — affiche son nom ; le
               numéro de version reste la référence stable.
  Source       arbitrage 2026-09-13
```

### 21.2 L'identité traverse les versions

```
EXG-MOD-003 — DOIT — L'élément de travail est le **seul** lien d'identité entre
deux révisions. Comparer un reste à engager à son budget de référence, ou
retrouver dans une révision ce qui correspond à un nœud d'une autre, se fait par
lui et par rien d'autre.
  Motif        Toute autre clé — position, libellé, identifiant d'échange — varie
               d'une révision à l'autre, et un rapprochement fondé dessus se rompt
               au premier remaniement (`EXG-RAE-005`).
  Vérification Renommer, déplacer ou réindenter un nœud dans un brouillon ne rompt
               aucun rapprochement avec une révision validée.
  Source       E14 (#326)
```

```
EXG-MOD-004 — DOIT — L'élément de travail ne porte pas de libellé : le nom d'une
tâche appartient à la révision.
  Motif        Sinon renommer une tâche dans un brouillon modifierait ce que
               montre une révision validée, et l'immuabilité ne serait plus qu'une
               façade.
  Vérification Renommer dans un brouillon laisse inchangé l'affichage de toute
               révision validée.
  Source       E14 (#326)
```

```
EXG-MOD-024 — DOIT — Une tâche porte une **description** libre. C'est un attribut
du projet, commun à toutes ses révisions, et il échappe délibérément à
l'immuabilité d'une révision validée.
  Motif        Une description documente le travail, elle ne chiffre rien : ce
               n'est pas une pièce du document financier. La figer à la
               validation interdirait de compléter une explication six mois plus
               tard, et la porter par révision obligerait à la recopier à chaque
               revue mensuelle — où elle serait perdue à la première qu'on oublie.
               Même raisonnement que pour le lotissement (`EXG-LOT-004`).
  Vérification Modifier la description d'une tâche est possible quel que soit le
               statut des révisions où elle figure, et la modification est
               visible depuis toutes.
  Source       E14 (#326)
```

### 21.3 L'immuabilité est la seule garde

```
EXG-MOD-005 — DOIT — Une révision validée refuse toute écriture. Un brouillon
n'en refuse aucune.
  Motif        C'est la seule protection du travail chiffré, et elle suffit parce
               qu'elle est totale. Les gardes qui protégeaient les brouillons —
               empêcher de supprimer un nœud chiffré ailleurs — protégeaient
               précisément l'endroit où l'utilisateur doit avoir tous les droits,
               et rendaient l'import incapable de faire ce pour quoi il existe.
  Vérification Aucune opération de brouillon n'est refusée au motif qu'une autre
               révision référencerait le même élément de travail.
  Source       E14 (#326)
```

```
EXG-MOD-006 — DOIT — On ne revient pas d'une révision validée à un brouillon :
on en obtient une copie, qui est une révision nouvelle.
  Motif        Rouvrir une révision validée invaliderait rétroactivement tout ce
               qui s'y réfère — une revue, un écart, une analyse déjà lue. La
               copie laisse l'original intact et rend le changement visible comme
               un changement.
  Vérification Copier une révision validée produit un brouillon distinct et ne
               modifie pas la source.
  Source       E14 (#326)
```

### 21.4 Ce qui disparaît

```
EXG-MOD-007 — DOIT — Le même planning n'est plus stocké deux fois. Les tables de
projet et leurs jumelles de version fusionnent dans la révision.
  Motif        Deux copies tenues en parallèle divergent : cinq incidents l'ont
               établi pour E14, et un sixième a été trouvé depuis : les liens
               de précédence ne sont écrits que d'un côté. La
               fusion supprime la classe entière.
  Vérification Une seule table porte l'arbre d'une révision ; aucune écriture
               n'est dupliquée.
  Source       E14 (#326)
```

```
EXG-MOD-008 — DOIT — Le compteur de concurrence s'appelle `lock_version`.
  Motif        Il s'appelle aujourd'hui `revision`, sur le planning comme sur le
               devis, au moment précis où le modèle introduit un objet nommé
               révision. C'est l'homonymie que proscrit `EXG-VOC-007`, déjà
               installée dans le schéma.
  Vérification Aucune colonne, aucun champ de contrat ne nomme `revision` un
               compteur de concurrence.
  Source       E14 (#326)
```

```
EXG-MOD-009 — DOIT — Le niveau et le numéro hiérarchiques ne sont pas stockés :
ils se calculent depuis le parent et le rang.
  Motif        Stockés, ils doivent être maintenus à chaque déplacement, et c'est
               leur dérive qui obligeait à corriger libellés et positions à la
               lecture. Calculés, ils ne peuvent pas mentir.
  Vérification Déplacer un nœud change sa numérotation affichée sans aucune
               écriture de renumérotation.
  Source       E14 (#326)
```

### 21.5 L'arbre et ses facettes

```
EXG-MOD-012 — DOIT — Un nœud porte une position et une identité, et exactement
**une** facette : planification, ou coût. Toute donnée métier appartient à la
facette.
  Motif        Un arbre unique où tâches et lignes de coût sont des nœuds de même
               nature rend impossible la divergence entre deux structures
               parallèles. La facette dit ce qu'un nœud est ; le nœud dit
               seulement où il est.
  Vérification Aucun nœud ne porte deux facettes, ni aucune.
  Source       E14 (#326)
```

```
EXG-MOD-025 — DOIT — Les nœuds de planification forment la couche supérieure de
l'arbre : le parent d'une tâche est une tâche, ou la racine. Une tâche n'est
jamais placée sous une ligne de coût.
  Motif        Une tâche doit rester exportable comme une tâche MS Project et
               ordonnançable par le calcul de dates. Une ligne de coût n'a ni
               date, ni durée, ni image dans le fichier : une tâche placée sous
               elle n'aurait pas de parent exportable, et l'export devrait la
               remonter silencieusement au premier ancêtre de planification —
               donc afficher dans Waterfall un arbre que le fichier exporté
               contredit. Le calcul des dates récapitulatives (`EXG-PLN-007`)
               devrait par ailleurs traverser un nœud dépourvu de dates.
  Vérification Un déplacement dont le parent cible porte une facette de coût est
               refusé lorsque le nœud déplacé porte une facette de planification,
               et le refus nomme la règle (`EXG-PLN-017`).
  Source       revision v0.1
```

```
EXG-MOD-026 — DOIT — La nature d'un élément de travail — tâche ou ligne de coût
— est la même dans toutes les révisions où il apparaît, et c'est elle qui
détermine la facette portée par son nœud.
  Motif        L'élément de travail est le seul lien d'identité entre versions
               (`EXG-MOD-003`). S'il pouvait changer de nature, comparer deux
               révisions reviendrait à comparer une tâche à une ligne de coût
               sous prétexte qu'elles portent la même identité, et l'avancement
               d'une tâche se lirait contre le montant d'une fourniture.
  Vérification Aucune opération ne change la nature d'un élément de travail ;
               dans toute révision, la facette d'un nœud est celle qu'annonce son
               élément de travail.
  Source       revision v0.1
```

```
EXG-MOD-013 — DOIT — Supprimer un nœud supprime son sous-arbre entier et les
facettes de tous les nœuds supprimés.
  Motif        Remonter les enfants au parent produirait un arbre que
               l'utilisateur n'a pas demandé, et laisser subsister la facette de
               coût d'un descendant supprimé produirait un montant que plus
               aucune tâche ne porte.
  Vérification Après suppression, aucune facette ni aucun lien ne référence le
               sous-arbre disparu, et la fratrie est renumérotée.
  Source       E14 (#326)
```

```
EXG-MOD-014 — DOIT — Les positions d'une fratrie sont des entiers contigus
commençant à un, y compris pour les nœuds racine.
  Motif        C'est ce qui rend l'ordre d'affichage déductible sans tri de
               rattrapage. Des positions à trous obligeraient chaque lecture à
               réordonner, et deux lectures pourraient différer.
  Vérification Supprimer un nœud du milieu renumérote ses frères.
  Source       E14 (#326)
```

```
EXG-MOD-015 — DOIT — Un élément de travail apparaît au plus une fois dans une
révision.
  Motif        Deux nœuds désignant la même identité rendraient tout
               rapprochement ambigu : comparer un reste à engager à son budget de
               référence n'aurait plus de réponse unique.
  Vérification Aucune révision ne porte deux nœuds de même élément de travail.
  Source       E14 (#326)
```

```
EXG-MOD-016 — DOIT — L'immuabilité d'une révision validée porte sur ses **deux
facettes à la fois**. Aucune écriture n'est possible sur l'une sans l'autre.
  Motif        Autoriser un déplacement de nœud au motif qu'il ne touche « que »
               la planification déplacerait la tâche porteuse de lignes de coût
               figées, donc modifierait le document financier par un chemin
               détourné.
  Vérification Toute écriture sur une révision validée est refusée avec la même
               erreur, quelle que soit la facette visée.
  Source       E14 (#326)
```

### 21.6 Le calendrier appartient à la planification

Rappel préalable, parce que la suite se lit mal sans lui : **aucun calendrier
n'est jamais importé** (`EXG-PLN-001`). Il s'agit ici du calendrier du
référentiel de Waterfall, et de l'endroit où il est inscrit.

```
EXG-MOD-017 — DOIT — Le calendrier applicable à une tâche est un attribut de sa
facette de planification. Il n'est **jamais** dérivé en lecture depuis les rôles
affectés.
  Motif        Le flux réel est planning d'abord, chiffrage ensuite. Une
               dérivation en lecture rendrait les dates incalculables sur toute
               tâche non encore chiffrée — c'est-à-dire sur tout planning qu'on
               vient d'importer.
  Vérification Le calendrier d'une tâche est lisible sans consulter aucun rôle.
  Source       E14 (#326)
```

```
EXG-MOD-018 — DOIT — La provenance du calendrier est enregistrée, et elle seule
détermine ce qui peut l'écraser : un choix explicite de l'utilisateur n'est
jamais réécrit par une affectation de rôle ni par le calendrier du projet.
  Motif        Sans provenance, une resynchronisation automatique effacerait un
               choix délibéré. Le moment où cela se produirait est le pire :
               un réimport, qui reconstruit l'arbre et réapplique donc la règle
               d'initialisation — alors même que le fichier n'apporte aucun
               calendrier et que l'utilisateur n'attend aucun changement.
  Vérification Affecter un rôle ne modifie pas un calendrier fixé à la main ;
               effacer ce choix rend la tâche à la resynchronisation.
  Source       E14 (#326)
```

Le calendrier que MS Project porte par tâche n'est pas honoré : c'est un
identifiant externe sans correspondance dans le référentiel, et lui en donner une
supposerait une table que le modèle ne porte pas. Cela ne contredit pas le
chapitre 17 — le calendrier **du projet** est bien exporté (`EXG-MSP-009`) ; c'est
la surcharge par tâche qui est ignorée.

### 21.7 Le document financier ne référence rien de mutable

```
EXG-MOD-019 — DOIT — Une ligne figée d'un chiffrage validé porte des identités
d'éléments de travail et des valeurs recopiées. Elle ne référence aucun nœud,
aucune facette, aucune ligne d'une autre révision.
  Motif        C'est ce qui rend un devis validé lisible et comparable même si
               toutes les révisions brouillon du projet ont été supprimées
               depuis. Une chaîne de pointeurs entre versions se romprait au
               premier remaniement, et c'est elle que `EXG-RAE-005` écarte.
  Vérification Supprimer tous les brouillons d'un projet laisse ses chiffrages
               validés intacts et comparables.
  Source       E14 (#326)
```

```
EXG-MOD-027 — DOIT — Les lignes figées sont produites **à la validation** d'une
révision, et n'existent que pour une révision validée. Un brouillon n'en porte
aucune.
  Motif        C'est le moment où les valeurs cessent de bouger : les produire
               plus tôt les exposerait à devenir fausses au premier changement du
               brouillon, et il faudrait alors les tenir à jour, c'est-à-dire
               refaire à chaque saisie le travail qu'elles existent pour éviter.
               C'est aussi ce qui rend `EXG-PAR-011` effectif — une révision
               validée porte les taux qui l'ont calculée parce qu'ils ont été
               recopiés là, à cet instant.
  Vérification Un brouillon ne porte aucune ligne figée ; sa validation en
               produit une par facette de coût existante à ce moment.
  Source       revision v0.1
```

```
EXG-MOD-020 — DOIT — Réimporter un fichier dans un brouillon fait disparaître,
pour une tâche absente du fichier, son nœud et tout son sous-arbre — donc ses
lignes de coût, qui en sont des nœuds.
  Motif        C'est la lecture cohérente d'« un seul arbre, deux facettes ». Le
               réimport est une action délibérée sur un brouillon, et aucune
               révision validée n'en est affectée. Remonter les orphelins à la
               racine ou refuser l'import protégerait l'endroit où l'utilisateur
               doit avoir tous les droits (`EXG-MOD-005`).
  Vérification Une tâche retirée du fichier disparaît du brouillon avec les
               nœuds de son sous-arbre, lignes de coût comprises ; les révisions
               validées sont inchangées.
  Source       E14 (#326)
```

### 21.8 Ce que la facette coût porte en propre

```
EXG-MOD-021 — DOIT — Une ligne de coût **peut** porter une date prévisionnelle
de décaissement, indépendante des dates de la tâche porteuse.
  Motif        Une fourniture se commande longtemps avant la tâche qui la
               consomme, et se règle selon ses propres échéances : les dates de
               la tâche ne les décrivent pas. Le modèle rend donc la date
               exprimable. Aucun calcul de la v1.0 ne la consomme, la trésorerie
               étant différée (chapitre 23) et le traitement des fournitures
               restant ouvert (question 11) ; l'attribut reste parce que le
               supprimer puis le recréer coûterait plus qu'il ne rapporte.
  Vérification La date de décaissement d'une ligne se saisit dans la grille du
               devis (11.6) et se lit indépendamment des dates de sa tâche.
  Source       E14 (#326)
```

```
EXG-MOD-022 — DOIT — Une fourniture porte un **état d'approvisionnement** :
prévue, commandée, reçue, annulée.
  Motif        Une commande passée et non livrée n'est ni du travail produit ni
               une dépense constatée. L'état est ce qui permet de la distinguer,
               indépendamment de la réponse qu'on donnera à la question 11 — qui
               porte sur le rattachement de ces lignes, sur leur poids dans le
               reste à engager et sur la mesure de leur avancement, et non sur la
               façon de les représenter.
  Vérification L'état d'une fourniture se saisit dans la grille du devis (11.6),
               et reste modifiable tant que la révision est un brouillon.
  Source       E14 (#326)
```

### 21.9 Conventions de table

```
EXG-MOD-010 — DOIT — Toute table porte sa date de création et sa date de
dernière modification. L'auteur de l'une et de l'autre n'est porté que par les
tables dont les lignes sont éditées individuellement par une personne.
  Motif        Les lignes produites par lot — pièces comptables importées,
               nœuds d'une révision copiée — tiennent leur auteur du lot ou de la
               révision qui les a produites ; répéter la colonne des milliers de
               fois y ajouterait du volume sans ajouter d'information. Ces
               horodatages ne remplacent pas la trace (`EXG-ADM-007`) : ils disent
               qui a touché une ligne en dernier, jamais ce qu'elle valait avant
               ni pourquoi elle a changé.
  Vérification Toute table porte les deux dates ; celles qui portent un auteur
               sont celles dont un écran permet d'éditer une ligne à l'unité.
  Source       arbitrage 2026-09-13
```

```
EXG-MOD-011 — DOIT — Une valeur d'énumération persistée décrit le travail qu'elle
désigne, et non le contexte où ce travail a lieu.
  Motif        Le troisième statut de projet s'appelle aujourd'hui d'après un
               appel d'offres que tous les projets ne connaissent pas
               (`EXG-CYC-002`). Renommer une énumération persistée coûte une
               migration ; le faire une fois vaut mieux que de vivre avec un nom
               qui trompe.
  Vérification Aucune valeur d'énumération ne nomme un contexte commercial.
  Source       arbitrage 2026-09-12
```

---

## 22. Exigences non fonctionnelles

**Statut : décidé.**

Ces exigences n'appartiennent à aucun écran, et c'est pourquoi elles se perdent.
Elles sont ici parce qu'aucun chapitre ne les réclamerait.

### 22.1 Volumétrie

```
EXG-NFO-001 — DOIT — La tenue des limites d'`EXG-NFO-013` est vérifiée par un
banc de performance exécuté à chaque intégration. Le banc compare ses mesures à
l'historique des exécutions précédentes de la branche d'intégration et échoue
lorsqu'elles s'en écartent significativement. Il ne les compare à aucun seuil
absolu.
  Motif        Une exigence de performance qu'aucune mesure ne garde se dégrade
               sans que personne ne le voie : chaque livraison coûte quelques
               millisecondes, et l'on découvre le problème lorsqu'il est devenu
               structurel. Le banc transforme l'intention en garde — mais
               seulement s'il peut échouer, faute de quoi il n'est qu'un
               thermomètre dont personne ne lit la valeur.

               La référence est l'historique et non un seuil parce que la mesure
               est prise sur une machine mutualisée, dont les temps varient du
               simple au triple selon ce qu'y font les autres. Un seuil absolu y
               produirait des échecs sans rapport avec le code livré, et une
               vérification qui échoue au hasard finit désactivée : on aurait
               alors perdu la garde **et** la mesure. Une référence qui dérive
               avec la machine absorbe ce bruit tout en laissant voir une
               régression structurelle, qui, elle, ne s'efface pas d'une
               exécution à l'autre.
  Vérification Le banc s'exécute sur un planning de l'ordre de grandeur des
               limites hautes. Une régression introduite délibérément — doubler
               le temps d'une lecture — le fait échouer ; deux exécutions
               successives du même code sur le runner partagé ne le font pas.
  Source       code existant, arbitrage 2026-09-13
```

```
EXG-NFO-013 — DOIT — Le produit tient les limites hautes suivantes sans
dégradation de service : **deux cents projets**, **mille tâches** et **cinq
lignes de coût par tâche**, un horizon d'**au moins dix ans**, et **mille
utilisateurs**. Au-delà, il a le droit de dégrader, mais il le signale.
  Motif        Une limite écrite se dimensionne ; une limite tacite se découvre
               en production. Et la dire permet de refuser explicitement plutôt
               que de ralentir jusqu'à l'inutilisable, ce qui est la seule façon
               de dégrader honnêtement.
  Vérification Le banc d'`EXG-NFO-001` s'exécute à ces ordres de grandeur.
  Source       arbitrage 2026-09-13
```

**Ce que ces limites impliquent.** Le nombre dimensionnant n'est aucune de ces
grandeurs prise seule : c'est leur produit avec le nombre de **révisions**. Une
révision copie l'arbre entier (`EXG-MOD-002`), et une revue mensuelle en produit
douze par an.

Pour un projet à la limite haute, sur une année :

| Grandeur | Par projet et par an | Pour deux cents projets |
|---|---:|---:|
| Nœuds de tâche | 12 000 | 2 400 000 |
| Nœuds de coût | 60 000 | 12 000 000 |
| Liens de précédence | 24 000 | 4 800 000 |
| Lignes figées | 72 000 | 14 400 000 |

Soit, en ordre de grandeur et en comptant les index, **près de 90 Mo par projet
et par an**, donc **une vingtaine de gigaoctets par an** pour le parc entier, et
**de l'ordre de 175 Go sur dix ans** sans rétention. S'y ajoutent les fichiers
sources conservés, environ **5 Go par an** dans le stockage objet.

**Ce volume n'est pas un problème en soi.** Deux cents gigaoctets sur dix ans
est une taille ordinaire pour une base relationnelle. Ce qui mérite attention
n'est pas l'espace occupé mais le nombre de lignes qu'une requête traverse, et de
ce point de vue la plupart des chemins sont naturellement bornés : une analyse
porte sur une révision, le portefeuille ne lit que la révision de référence de
chaque projet.

Un seul chemin échappe à cette borne, et c'est la courbe d'évolution de la
projection à terminaison (`EXG-ANA-007`) : elle porte un point par revue, donc
cent vingt sur dix ans, chacun exigeant un agrégat sur les quelque six mille
lignes figées de sa révision.

```
EXG-NFO-014 — DOIT — Les agrégats d'une révision validée sont calculés une fois,
à la validation, et conservés.
  Motif        Une révision validée ne change plus (`EXG-MOD-005`) : ses
               agrégats non plus. Les recalculer à chaque affichage revient à
               relire tout l'historique d'un projet pour tracer une courbe dont
               tous les points sauf le dernier sont acquis depuis des mois. C'est
               le seul chemin de lecture qui croît avec l'âge du projet, et
               l'immuabilité offre le moyen de l'en empêcher gratuitement.
  Vérification Tracer l'évolution d'un projet de dix ans ne lit aucune ligne
               figée.
  Source       arbitrage 2026-09-13
```

Reste que **le coût domine le volume** : les nœuds de coût et les lignes figées
en font plus de quatre cinquièmes. C'est le facteur cinq par tâche qui commande,
non le millier de tâches — utile à savoir si l'un des deux devait être revu.

Ces chiffres sont des ordres de grandeur, établis sur des tailles de ligne
estimées. Ils servent à dimensionner, non à provisionner un disque au gigaoctet
près.

Ces limites sont nettement supérieures à ce qui a été observé sur les fichiers
d'exemple — des plannings de cinq cent cinquante tâches, sur six ans — et c'est
voulu : on dimensionne pour ce que le produit doit tenir, non pour ce qu'il a
rencontré.

### 22.2 Accessibilité

```
EXG-NFO-002 — DOIT — Le focus clavier est visible en permanence, sur tout
élément qui peut le recevoir.
  Motif        Une table de plusieurs centaines de lignes se parcourt au clavier
               (`EXG-PLN-021`). Un focus invisible y fait perdre sa place à
               chaque frappe, ce qui revient à interdire le clavier sans
               l'annoncer.
  Vérification Chaque élément focalisable porte un état de focus distinct de son
               état de survol.
  Source       arbitrage 2026-09-13
```

```
EXG-NFO-003 — DOIT — Le contraste du texte et des éléments actifs satisfait le
seuil AA du référentiel d'accessibilité, dans les deux thèmes.
  Motif        Nommer un seuil est ce qui distingue une exigence d'une intention.
               « Lisible » se discute, un rapport de contraste se mesure — et se
               mesure aussi sur le thème sombre, où les régressions passent le
               plus souvent inaperçues faute d'être relues.
  Vérification Le contraste est mesuré sur les deux thèmes, y compris sur les
               couleurs de statut et de série graphique.
  Source       arbitrage 2026-09-13
```

Deux règles déjà posées relèvent aussi de l'accessibilité et ne sont pas répétées
ici : la couleur ne porte jamais seule une information (`EXG-ANA-011`), et tout
ce que la souris permet sur la table, le clavier le permet aussi
(`EXG-PLN-021`).

### 22.3 Thèmes

```
EXG-NFO-004 — DOIT — Le produit rend correctement en thème clair et en thème
sombre. Aucun encodage d'information ne dépend du thème choisi.
  Motif        Un graphique dont les séries se distinguent en clair et se
               confondent en sombre est faux la moitié du temps, et personne ne
               s'en aperçoit tant que l'auteur travaille dans un seul thème.
  Vérification Toute vue porteuse d'information encodée est relue dans les deux
               thèmes ; aucune couleur n'est définie hors du jeu de jetons
               partagé.
  Source       arbitrage 2026-09-13
```

### 22.4 Le contrat d'échange

```
EXG-NFO-005 — DOIT — Le contrat d'API est vérifié contre les routes réellement
servies, et l'écart fait échouer l'intégration.
  Motif        Un contrat qui décrit autre chose que le service est pire
               qu'aucun contrat : il est cru. La vérification automatique est ce
               qui le maintient vrai sans discipline.
  Vérification Ajouter une route sans l'inscrire au contrat fait échouer la
               vérification.
  Source       code existant
```

```
EXG-NFO-006 — DOIT — Les types échangés par l'interface sont **générés** depuis
le contrat, jamais réécrits à la main.
  Motif        Un type recopié diverge au premier changement, et la divergence ne
               se manifeste qu'à l'exécution, sur un champ absent ou renommé.
               La génération fait de cette classe d'erreurs une erreur de
               compilation.
  Vérification Le client généré est reproductible depuis le contrat, et sa
               régénération ne produit aucune différence non commise.
  Source       code existant
```

### 22.5 Les gardes de qualité

```
EXG-NFO-007 — DOIT — Les gardes de qualité sont bloquantes et identiques en
local et en intégration.
  Motif        Une garde qui n'existe qu'en intégration se découvre après coup,
               quand la correction coûte un aller-retour ; une garde qui n'existe
               qu'en local se contourne. Les deux doivent porter le même verdict
               sur le même code.
  Vérification Le même ensemble de vérifications s'exécute avant commit et à
               l'intégration, et un échec bloque dans les deux cas.
  Source       code existant
```

```
EXG-NFO-008 — DOIT — La complexité cyclomatique est bornée au même seuil des
deux côtés du produit.
  Motif        Deux seuils différents feraient de la limite une propriété du
               langage plutôt que du produit, et l'on finirait par écrire dans
               celui qui pardonne. Un seuil commun dit ce que l'équipe accepte de
               relire, indépendamment de l'outil.
  Vérification Le même seuil est déclaré des deux côtés, et tout dépassement
               échoue.
  Source       #58, #157
```

```
EXG-NFO-009 — DOIT — Le schéma de base se met à jour par migrations
versionnées, sans intervention manuelle.
  Motif        Une migration appliquée à la main est une migration qu'un
               environnement n'aura pas reçue, et l'écart se découvre à
               l'exécution sur une colonne absente. C'est aussi la condition
               d'`EXG-ADM-004` : une sauvegarde ne se restaure dans une version
               que si les versions se nomment.
  Vérification Une base vierge et une base existante atteignent le même schéma
               par la seule exécution des migrations.
  Source       code existant
```

### 22.6 Langue et internationalisation

```
EXG-NFO-010 — DOIT — Tout ce que l'utilisateur lit est en français : libellés,
messages d'erreur, exports et rapports.
  Motif        Un message d'erreur en anglais au milieu d'une interface française
               est lu comme une panne technique plutôt que comme une information,
               et l'utilisateur cesse d'y chercher la cause.
  Vérification Aucun texte destiné à l'utilisateur n'est en anglais, y compris
               dans les rapports d'import et les messages de refus.
  Source       arbitrage 2026-09-13
```

```
EXG-NFO-011 — DOIT — Un refus du serveur porte un **code** et les données
nécessaires à sa formulation. L'interface produit le message ; le serveur ne
renvoie jamais une phrase destinée à être affichée telle quelle.
  Motif        Deux problèmes en un. Le serveur répond aujourd'hui par des
               phrases anglaises que l'interface finit par afficher faute de
               mieux, ce qui viole `EXG-NFO-010` à chaque refus. Et une phrase ne
               se traduit pas chez celui qui la reçoit : tant que le message est
               fabriqué à l'émission, aucune autre langue n'est possible, quelle
               que soit la qualité du reste.
  Vérification Aucune réponse d'erreur ne contient de phrase rédigée ; chaque cas
               de refus est identifié par un code que l'interface sait rendre.
  Source       arbitrage 2026-09-13
```

```
EXG-NFO-012 — DOIT — Les textes de l'interface sont externalisés, et les formats
— dates, nombres, montants — passent par une locale. Le produit n'est pas
multilingue en v1.0, mais rien n'y rend coûteux de le devenir.
  Motif        Le coût d'une internationalisation tardive n'est pas la
               traduction : c'est de retrouver les milliers d'endroits où une
               chaîne a été écrite dans un composant et une date formatée à la
               main. Ce coût se paie une fois, à l'écriture, ou dix fois plus tard.
               Le besoin n'existe pas encore ; il existera, et c'est maintenant
               qu'il ne coûte rien de s'y préparer.
  Vérification Aucun texte destiné à l'utilisateur n'est écrit dans un composant ;
               aucun format de date ou de nombre n'est codé en dur.
  Source       arbitrage 2026-09-13
```

### 22.7 Montée en charge et cache

Mille utilisateurs ne se servent pas comme dix, et la différence ne se rattrape
pas après coup : elle tient à des propriétés qu'on a ou qu'on n'a pas.

```
EXG-NFO-015 — DOIT — L'application ne conserve aucun état de session en mémoire.
Toute instance sert n'importe quelle requête de n'importe quel utilisateur.
  Motif        C'est la condition de tout le reste : tant qu'une instance détient
               quelque chose que les autres ignorent, en ajouter une seconde
               produit des réponses différentes selon celle qui répond, et le
               défaut est intermittent donc très coûteux à trouver.
  Vérification Arrêter une instance en cours d'utilisation n'interrompt aucune
               session ; deux instances servent indifféremment le même
               utilisateur.
  Source       code existant
```

```
EXG-NFO-016 — DOIT — Une opération longue — import d'un fichier, production d'une
archive de sauvegarde — est enregistrée, exécutée hors de la requête, et son
avancement est consultable.
  Motif        Une opération tenue dans la requête immobilise un serveur pendant
               toute sa durée et meurt au premier délai d'attente d'un
               intermédiaire réseau, sans que l'utilisateur sache si elle a
               abouti. Un fichier de planning atteint dix mégaoctets, et une
               archive de sauvegarde des dizaines de gigaoctets : le cas n'est
               pas marginal, il est le cas courant de ces deux fonctions.
  Vérification Le déclenchement répond immédiatement avec de quoi suivre
               l'opération ; fermer l'onglet ne l'interrompt pas.
  Source       arbitrage 2026-09-13
```

```
EXG-NFO-017 — DOIT — Une tâche exécutée hors requête tolère d'être lancée par
plusieurs instances : soit elle est idempotente, soit elle prend un verrou.
  Motif        Dès qu'il y a plus d'une instance, rien ne garantit laquelle
               traitera quoi. Une tâche qui suppose l'unicité produit des
               doublons — deux archives, deux imports de la même pièce — et le
               défaut n'apparaît qu'en charge, jamais en développement.
  Vérification La même tâche lancée deux fois en parallèle produit le même
               résultat qu'une seule.
  Source       arbitrage 2026-09-13
```

```
EXG-NFO-018 — DOIT — Le cache n'est jamais source de vérité. Le vider ne change
aucun résultat, seulement le temps de réponse.
  Motif        C'est la règle qui rend un cache sûr, et celle qu'on enfreint sans
               s'en apercevoir dès qu'une donnée n'existe plus qu'en cache. Un
               cache est un magasin dont on doit pouvoir se passer à tout instant
               — il se vide, il expire, il tombe.
  Vérification Vider le cache en service ne produit aucune différence observable
               hors latence.
  Source       arbitrage 2026-09-13
```

```
EXG-NFO-019 — DOIT — On met en cache ce qui ne peut plus changer. Les données
d'une révision en brouillon ne sont pas mises en cache.
  Motif        Le modèle offre ici un avantage qu'il serait dommage de gâcher :
               une révision validée est immuable (`EXG-MOD-005`), donc ses
               agrégats aussi (`EXG-NFO-014`), et tout ce qui en dérive se met en
               cache sans invalidation — le problème le plus difficile du cache
               ne se pose pas. Mettre en cache un brouillon échange cette
               tranquillité contre un gain qui dure jusqu'à la prochaine frappe,
               et contre une classe de défauts où l'utilisateur voit un état qui
               n'existe plus.
  Vérification Aucune entrée de cache ne porte sur une révision en brouillon.
  Source       arbitrage 2026-09-13
```

### 22.8 Ce qui n'est pas un point ouvert

Le **multilinguisme** est un hors-périmètre assumé (chapitre 23) : la v1.0 est en
français, et `EXG-NFO-011` et `EXG-NFO-012` se bornent à ne pas en fermer la
porte.

La **rétention** des révisions anciennes n'en est pas un non plus. Le volume ne
l'impose pas, et le seul chemin de lecture qui croissait avec l'âge d'un projet
est traité par `EXG-NFO-014`. Elle pourra se poser plus tard, pour la taille
d'une archive de sauvegarde (`EXG-ADM-012`) ou par hygiène — pas pour tenir les
limites de ce chapitre.

---

## 23. Hors périmètre v1.0

Ce chapitre existe pour éviter qu'une décision soit reprise faute d'être écrite.
Il ne liste pas tout ce que Waterfall ne fait pas — la liste serait infinie — mais
ce qu'on a **envisagé puis écarté**, avec la raison. Quiconque propose l'une de
ces choses est en droit d'être répondu par autre chose qu'un silence.

Deux natures d'exclusion, qu'il faut distinguer.

### 23.1 Différé : utile, mais pas indispensable

Le critère d'inclusion (1.3) écarte ce dont l'absence rend le produit moins
agréable sans le rendre inutilisable. Ces sujets reviendront.

**Assistant de saisie des lignes de support** — ex-`EXG-DEV-007` et `008`. Seule
entrée de cette section qui ne reviendra pas telle quelle : elle figure ici parce
qu'on l'a envisagée, non parce qu'on l'attend.
Sélectionner un ensemble de lignes, saisir un pourcentage, laisser l'outil
reporter le nombre d'heures dans une ligne de support. Écarté non par manque de
temps mais parce qu'il s'est révélé **inutile** : afficher le total des lignes
sélectionnées (`EXG-DEV-015`) donne la seule chose qui manquait, le pourcentage
se calculant de tête. La leçon vaut d'être gardée — le besoin ressemblait à une
fonction, il n'était qu'un nombre absent de l'écran.

Si le sujet revient, trois propriétés le rendaient bon marché et méritent d'être
retrouvées plutôt que redécouvertes : il produit des **heures** et non des euros,
laissant la ligne passer par le mécanisme normal de taux et d'inflation ; le
périmètre est **choisi à la main**, aucune règle générale ne pouvant deviner ce
qu'un encadrement encadre ; et il n'établit **aucun lien vivant**, donc rien à
recalculer ni à invalider.

**La gestion de trésorerie.** Courbe d'encaissements et de décaissements, besoin
de financement, prix de vente et dates contractuelles portés par les lots, plan
d'acomptage. Différé en bloc, et pour une raison qui tient à la justesse plus
qu'au coût : une courbe qui confronte un consommé au périmètre rigoureux à des
recettes approximatives produit un **besoin de financement**, c'est-à-dire
précisément un nombre sur lequel on agit. Mieux vaut absent que faux.

La trésorerie suppose en outre une **marge nette**, qui rouvrirait la question de
périmètre que l'exclusion des lignes de coût réel a réglée d'un seul côté
(13.4) ; et l'ERP fait déjà cela. Une version suivante pourra en faire son sujet
principal : le découpage qui la porterait — le lotissement — existe déjà, et il
suffira de lui rendre les montants et les dates.

Sortent avec elle : `EXG-LOT-002`, `EXG-LOT-003`, `EXG-CYC-017`, la section
d'analyse correspondante, et les questions du plan d'acomptage et du décaissement
prévisionnel.

**Multilinguisme.** La v1.0 est en français. Une interface dans la langue de ses
utilisateurs n'est pas moins utilisable qu'une interface traduite, et le critère
l'écarte donc. Mais le besoin viendra, et deux exigences en préservent la
possibilité à coût nul : les refus du serveur portent un code plutôt qu'une
phrase (`EXG-NFO-011`), et ni les textes ni les formats ne sont écrits en dur
(`EXG-NFO-012`). C'est la différence entre reporter et condamner.

**Supervision continue, alertes et mesures de performance.** L'administration de
la v1.0 dit ce qui fonctionne et ce qui ne fonctionne pas (`EXG-ADM-009`), et
conserve l'historique des imports. Un tableau de bord d'exploitation, des seuils
et des notifications rendraient l'exploitation plus confortable, non possible.

**Disposition configurable du tableau de bord.** Sa disposition est fixe et suit
un enchaînement de questions (`EXG-ANA-001`). La rendre libre est une commodité —
et elle coûterait la règle de dénominateur, qui dépend du voisinage des tuiles.
Le jour où elle reviendra, c'est cette contrainte qu'il faudra reformuler
d'abord.

**Calendrier porteur de jours d'exception.** Écarté non pour sa difficulté mais
faute de **source fiable** : les calendriers des fichiers importés sont rarement
paramétrés, donc variables d'un fichier à l'autre, et les absences individuelles
supposeraient un modèle de personnes que Waterfall n'a pas. Le biais qui en
résulte est systématique, donc sans effet sur les indices (17.3).

### 23.2 Écarté par nature : ce n'est pas ce produit

Ces sujets ne reviendront pas par simple priorisation : les admettre changerait ce
qu'est Waterfall (2.2).

**L'ordonnancement.** Waterfall calcule des dates depuis des durées et des liens,
mais ne cherche aucun optimum, ne nivelle aucune ressource et ne propose aucun
réordonnancement. MS Project reste la référence de planification pour qui en veut
une, et son rôle est annexe.

**La saisie du temps passé.** Le coût réel vient de la comptabilité par import
(chapitre 13), jamais d'une déclaration d'heures dans Waterfall. Collecter du
temps ferait du produit un outil de suivi individuel, ce qu'il n'est pas, et
créerait une seconde vérité à côté de celle qui fait foi.

**La facturation.** Waterfall n'émet aucune facture, n'en suit aucun règlement, et
ne remplace aucun système de gestion. C'est vrai même le jour où la trésorerie
reviendra : prévoir des encaissements et facturer sont deux métiers.

**Le suivi de l'acceptation client.** Waterfall sait où en est le travail qui
produit un livrable, puisque rédiger, vérifier et livrer sont des tâches. Il ne
sait pas si le client l'a accepté, et cette information lui vient de l'extérieur —
d'un courrier, d'une réunion, d'un procès-verbal. La porter supposerait de
devenir le système où se tient la relation contractuelle, ce qu'il n'est pas.

**La gestion documentaire.** Les fichiers conservés sont les **sources d'import**,
gardées pour l'auditabilité et la reprise (`EXG-CRE-005`). Ce n'est pas un
espace de dépôt, et aucune pièce ne s'attache à une tâche ou à un projet.

**La multidevise.** Un projet porte une devise ; aucune conversion n'est faite,
aucun taux de change n'est tenu. Un projet facturé dans une devise et dépensé
dans une autre relève d'un besoin qui n'a pas été exprimé.

### 23.3 Différé pour une autre raison

**La séparation en services.** L'analyse d'architecture a conclu que l'identité
est extractible mais que la planification et le chiffrage ne le sont pas — ils
partagent un arbre et se lisent ensemble. La séparation a été différée, et les
exigences de ce document n'en dépendent pas : elles décrivent un comportement, pas
un déploiement. Les principes du chapitre 22 — application sans état, opérations
longues hors requête, tâches idempotentes — sont ce qui la laisse possible sans
la préjuger.

## Annexe A — Ce que ce document ne fera pas

*Des trois annexes, celle-ci est la seule appelée à rester : les deux suivantes
se videront à mesure que les questions se tranchent et que les écarts se
livrent.*

- Il ne décrit pas l'implémentation : pas de schéma SQL, pas de signature
  d'endpoint, sauf lorsque le contrat est lui-même une décision produit.
- Il ne remplace pas les EPIC : ceux-ci portent le découpage de livraison.
- Il n'invente rien. Une exigence sans décision derrière elle est une question
  ouverte, et figure à l'annexe B plutôt que dans un chapitre d'exigences.

---

## Annexe B — Questions ouvertes

Recensées ici pour ne pas être perdues ; chacune sera reprise dans son chapitre.

1. *Close le 2026-09-13 : différée avec la trésorerie* (chapitre 23). Un plan
   d'acomptage échelonne le prix d'un lot ; sans prix de vente dans le modèle, il
   n'a plus d'objet. La forme courante — un pourcentage du prix à une date, les
   échéances se partageant les cent pour cent — est consignée là pour le jour où
   le sujet reviendra.
2. **Provisions pour risques**. Question transverse aux chapitres 11, 12 et 14,
   et la plus lourde du document.

   *La pratique.* Chaque risque fait l'objet d'un **devis complet** — on chiffre
   ce qu'il coûterait s'il survenait — puis son montant est reporté dans le devis
   global en **une seule ligne, pondérée** par sa probabilité. La provision totale
   est la somme de ces espérances.

   *Ce que cela impliquerait.* Reproduire fidèlement cette pratique demande un
   module de gestion des risques à part entière : un registre, un devis par
   risque, une probabilité, un état — ouvert, réalisé, écarté — et le report
   pondéré vers le devis global. C'est un chantier, et il n'est pas acquis qu'il
   relève de la v1.0.

   *Le critère d'inclusion appliqué à ce cas.* Aujourd'hui une provision se
   saisit comme une ligne de frais ordinaire. Ce qui manque n'est donc pas le
   montant, c'est **la distinction** : rien ne sépare une provision d'une dépense
   prévue. Or la conséquence est réelle et silencieuse — une provision consommée
   n'est pas du travail produit, et la compter comme telle gonfle l'avancement
   physique. Un simple **marqueur** sur la ligne, avec sa pondération, suffirait
   à rétablir cette distinction sans registre ni devis par risque. À décider si
   ce minimum est le périmètre v1.0, et le module complet une version ultérieure.

   *La survenue d'un risque.* C'est elle qui donne sa dynamique au module, et
   sans elle un marqueur suffirait. On déclare qu'un risque s'est produit, et son
   devis entre alors dans le budget. Le coût augmente sans contrepartie, et
   d'autant plus que la provision ne couvrait qu'une fraction pondérée de ce qui
   arrive.

   Le fonctionnement **ressemble** à celui d'un avenant (question 14) — un
   événement daté qui déplace la référence — sans qu'on puisse en conclure qu'il
   s'agisse du même mécanisme. Une différence au moins l'interdit d'emblée : un
   avenant **ajoute** un travail absent du budget, là où une survenue
   **remplace** une ligne pondérée déjà présente par le devis complet du risque.
   L'arithmétique n'est pas la même opération. S'y ajoutent une date qui est
   contractuelle dans un cas et affaire de jugement dans l'autre, et un montant
   ferme contre une prévision qui peut se réaliser partiellement. Le
   rapprochement demande une analyse propre, à mener avant d'en tirer quoi que ce
   soit.

   *Où cette dégradation doit se lire.* Deux lectures, et le report de la
   trésorerie en élimine une. Si la survenue **porte le budget de référence** au
   montant réel du risque, les indices de coût restent proches de un — on dépense
   ce qui est désormais budgété — et la dégradation ne se lirait que dans la
   marge, qui n'existe plus en v1.0 : elle serait donc **invisible**. Si le
   budget **reste à la provision**, l'écart apparaît dans les indices, mais le
   plan affiche une cible que plus personne ne peut tenir. C'est exactement le piège
   de la question 14 : recaler la référence efface la dérive des indices, ne pas
   la recaler rend le plan irréaliste. La sortie est la même — conserver la
   référence antérieure et la référence courante, et pouvoir lire les deux, la
   survenue étant un événement daté qui les sépare.

   *Le cas symétrique.* Un risque qui ne survient pas et devient impossible doit
   **libérer sa provision**, sinon le budget conserve un poids mort et l'affaire
   paraît plus mauvaise qu'elle n'est jusqu'à sa clôture.

   *Ce qui reste ouvert dans tous les cas.* La ligne pondérée porte-t-elle
   l'espérance, ou le montant brut et sa probabilité séparément ? La provision
   entre-t-elle dans le budget de référence, donc dans le dénominateur de
   l'avancement physique ? Et sa consommation se suit-elle au reste à engager
   comme une ligne ordinaire ? C'est la même famille de problème que l'exclusion
   d'une ligne de coût (question 15) : une grandeur qui doit compter dans un
   indicateur et pas dans un autre.

   *À ne pas présumer.* Que les deux se ressemblent ne dit rien de la façon de
   les cadrer, ni de l'ordre dans lequel les traiter. C'est une piste d'analyse,
   pas une conclusion.
3. *(fusionnée dans la question 11, qui la contient.)*
4. *Close le 2026-09-13 : sans objet.* Elle portait sur l'assiette d'un
   assistant de calcul des lignes de support et sur l'utilité d'un mémo. Les deux
   tombent avec l'assistant lui-même : l'assiette est ce que l'utilisateur
   sélectionne, et le total de cette sélection (`EXG-DEV-015`) lui suffit à
   appliquer son pourcentage.
5. *Close le 2026-09-13 : la forme est arrêtée.* Le marqueur est une empreinte
   portée par la révision, calculée à la génération sur le lotissement **et** sur
   l'arbre produit ; « non retouché » signifie que l'arbre courant a la même
   empreinte. Elle couvre la forme de l'arbre et les libellés, les valeurs de
   planification saisies, le calendrier épinglé à la main — et lui seul, les
   valeurs dérivées feraient passer pour retouché un squelette que personne n'a
   touché — et les liens d'antériorité traduits en chemins de positions, qui
   vivent hors de l'arbre et dont l'oubli rendrait regénérable un planning déjà
   ordonnancé. Elle ne porte aucun identifiant, de sorte qu'une copie de révision
   reste un squelette non retouché (`EXG-LOT-011`).
6. *Close le 2026-09-13 : faux problème.* J'avais listé quatre cas où une tâche
   pourrait n'avoir pas de dates, et relevé que ses heures disparaîtraient alors
   du budget. Trois de ces cas ne tiennent pas. Une tâche créée reçoit la date de
   début du projet et une durée d'un jour, convention reprise de MS Project
   (`EXG-PLN-004`, `EXG-PLN-022`). Et les fichiers importés portent ces champs :
   vérifié sur six exports réels totalisant deux mille six cent soixante-six
   tâches, aucune ne manque de début, de fin, de durée ni d'indicateur de mode.
   Le quatrième cas — une récapitulative dont tous les enfants seraient sans
   dates — disparaît avec les précédents. `EXG-PLN-025` rend la garantie
   explicite plutôt qu'accidentelle.
7. *(fusionnée dans la question 10.)*
8. *Sans objet depuis le 2026-09-13.* Elle demandait où rattacher le découplage
   du lotissement et du planning. La question était de séquencement, non de
   produit : le chapitre 8 fixe la cible, et l'annexe C porte les écarts avec
   leur propriétaire quand il y en a un. Le découpage en lots relève des EPIC,
   que ce document ne fait pas (annexe A).
9. *Tranchée le 2026-09-13* (`EXG-NFO-013`) : deux cents projets, mille tâches,
   cinq lignes de coût par tâche, dix ans, mille utilisateurs. Le volume qui en
   découle — de l'ordre de deux cents gigaoctets sur dix ans — ne justifie par
   lui-même aucune rétention, et le seul chemin de lecture qui croissait avec
   l'âge d'un projet est traité par `EXG-NFO-014`.
10. *Close le 2026-09-13 : le périmètre est cadré au chapitre 20.* Comptes,
    habilitations, sauvegarde et restauration, trace et état du système ; la
    supervision continue, les alertes et les mesures de performance en sont
    écartées par le critère d'inclusion.
11. **Sous-traitance et fournitures** : comment mesure-t-on leur avancement ?
    Une commande passée et non livrée n'est ni du travail produit ni une dépense
    constatée, et aucune des trois grandeurs du modèle — budget de référence,
    reste à engager, consommé — ne la décrit.

    *Ce qu'il faut trancher.* D'abord le rattachement : une fourniture ou une
    prestation sous-traitée doit-elle pendre sous une tâche comme n'importe
    quelle ligne de coût, ou relève-t-elle d'un objet propre ? La question n'est
    pas de présentation. Une ligne portée par une tâche entre dans le budget de
    référence de cette tâche, donc dans la pondération qui commande son
    avancement : une commande de deux cent mille euros sous une tâche de
    rédaction ferait peser cette commande sur l'avancement de la rédaction.

    Ensuite le reste à engager. Que saisit-on pour une fourniture commandée mais
    non livrée — zéro, puisque l'argent est engagé, ou le montant, puisque rien
    n'est encore dû ? Comment s'en mesure l'avancement,
    la méthode 0/100 supposant une tâche qui se termine là où une fourniture se
    commande, se livre et se réceptionne ? Faut-il une notion d'« engagé »
    distincte du consommé, et si oui, à quelle date la rattacher — à la commande,
    à la facturation ou au règlement ? Cette dernière question est celle que
    portait la question 3 : l'export comptable ne donne que la date de pièce,
    donc le règlement, et aucune date de commande, ce qui interdit aujourd'hui de
    dater un engagement de façon fiable.

    *Ce que le modèle cible apporte déjà.* Une ligne de coût y porte un **état
    d'approvisionnement** — prévue, commandée, reçue, annulée — et une **date
    prévisionnelle de décaissement** indépendante des dates de sa tâche
    (`EXG-MOD-021`, `EXG-MOD-022`). La distinction matérielle existe donc, ainsi
    que la date du décaissement. Ce qui reste ouvert est ce qu'on en fait dans le
    reste à engager et dans la valeur acquise, non la façon de la représenter.

    Question transverse aux chapitres 11, 12 et 14. Remplace EXG-VOC-003 et
    absorbe la question 3.
12. *Tranchée le 2026-09-14 : l'inflation est portée par le projet.* Deux
    projets chiffrés à deux ans d'écart n'ont ni la même année de référence ni
    les mêmes perspectives, et certains marchés portent leur propre clause
    d'indexation ; un paramètre commun interdisait de les distinguer et
    déplaçait rétroactivement le budget des projets en cours. Le projet porte un
    **coefficient unique**, non une série annuelle (`EXG-DEV-020`) : une
    prévision année par année sur dix ans serait une donnée que personne ne tient
    à jour, dont la précision apparente masquerait qu'elle reste une hypothèse
    unique. L'inflation quitte en conséquence le référentiel commun
    (`EXG-PAR-007`, abandonnée).
13. *Tranchée le 2026-09-12 : le coefficient est cumulatif.* L'année de
    référence d'un chiffrage est son année de création, et l'inflation appliquée
    à une charge est le cumul depuis cette année jusqu'à l'année de consommation
    (`EXG-DEV-005`). Les charges à cheval sur deux années se répartissent au
    prorata du temps (`EXG-DEV-006`), et la grille affiche le montant hors
    inflation à côté du montant corrigé (`EXG-DEV-014`). La forme de stockage ne
    se pose plus depuis que le projet porte un coefficient unique
    (`EXG-DEV-020`) : il n'y a qu'un nombre à conserver, et le cumul est un
    calcul.
14. **Avenants** : un avenant ajoute du travail au projet — et, hors du
    périmètre v1.0, en modifie le prix de vente. Le principe est simple, la mise
    en œuvre beaucoup moins.

    *Ce qui est acquis.* Un avenant fait l'objet d'un devis, donc d'une liste de
    tâches : c'est le flux normal de Waterfall, et il n'y a pas lieu d'en
    inventer un autre.

    *Ce qui coince.* Ces tâches viennent s'entremêler aux tâches existantes, or
    le modèle repose sur un arbre commun aux tâches et aux lignes de coût. Ce
    principe est sain et on ne veut pas le casser pour un avenant.

    *La piste envisagée.* Créer les tâches de l'avenant dans le planning général
    en les marquant — « avenant 1 » — et filtrer sur ce marquage, dans le
    planning comme dans la feuille de coûts, pour en conduire le chiffrage. À la
    réception de la commande, fusionner le budget de référence et les coûts
    associés. L'arbre reste unique ; c'est la **lecture** qui se restreint, pas
    la structure.

    *Ce que cette piste réglerait.* Le marquage est une appartenance de
    périmètre, exactement de même nature que l'exclusion d'une ligne de coût de
    la question 15 — il y a peut-être un seul mécanisme à concevoir pour les
    deux. Et la fusion est un **événement daté** : c'est à cet instant que le
    budget de référence change, ce qui permet de conserver la référence
    antérieure et de lire les deux, au lieu d'effacer rétroactivement la dérive
    déjà constatée.

    *Ce qu'elle laisse à décider.* Le marquage porte-t-il un état — en chiffrage,
    puis commandé — puisque les tâches d'un avenant non commandé ne doivent
    compter ni dans le budget de référence ni dans les indices ? Un avenant
    peut-il être négatif, c'est-à-dire réduire le périmètre ? Et l'avenant
    est-il lui-même un objet daté, numéroté et motivé, ou seulement un marquage
    et une date de fusion ?

    *Réduite par le report de la trésorerie.* Le prix de vente ayant quitté la
    v1.0, un avenant n'y apporte plus que du coût et des tâches : la question du
    sort des lots déjà facturés tombe.

    *À rapprocher, avec prudence.* La survenue d'un risque (question 2) déplace
    elle aussi le budget de référence à une date donnée. La ressemblance s'arrête
    là où l'analyse commence : un avenant ajoute un travail absent du budget, une
    survenue remplace une provision pondérée déjà présente. Les deux questions
    méritent d'être instruites en se regardant, pas fusionnées.

    Question transverse aux chapitres 8, 10, 11, 14 et 15.
15. *Tranchée le 2026-09-15 : l'exclusion porte sur une ligne, et sur elle
    seule.* La question confondait deux cas. Le **ré-import** d'une pièce déjà
    connue ne pose rien : l'idempotence la reconnaît par son numéro et ne la
    recrée pas, de sorte qu'une ligne exclue le reste quel que soit le
    recouvrement des dates d'export — et l'utilisateur a tout intérêt à faire
    chevaucher ces dates pour ne rien perdre. Le cas réel est l'arrivée d'une
    pièce **nouvelle** de même nature, l'imputation des frais généraux du mois
    suivant portant son propre numéro. Aucune règle automatique ne le couvre :
    ses deux échecs ne se valent pas, un oubli laissant une dépense visible dans
    les indicateurs là où une règle trop large en retire une sans que rien ne le
    signale. Le geste reste manuel et devient fiable parce que l'import distingue
    ce qu'il vient de créer (`EXG-CRE-013`, `EXG-CRE-014`). Le motif est un texte
    libre et l'exclusion relève d'une permission distincte de l'écriture,
    attribuée au chef de projet (`EXG-CRE-006`). L'affichage permanent des deux
    consommés était déjà tranché par `EXG-CRE-008`.
16. *Tranchée le 2026-09-12 : la garde est conservée.* Un jalon ne porte pas
    d'enfants — c'est `EXG-PLN-008`. Le module de domaine pur doit donc porter
    cette règle et la couvrir comme ses autres invariants avant que le service
    d'arbre ne soit supprimé. L'agent en charge d'E14 en est informé ; l'issue
    #343 porte la décision.
17. *Tranchée le 2026-09-15 : la copie emporte tout le sous-arbre.* Les
    sous-tâches et les lignes de coût suivent, avec leurs montants
    (`EXG-PLN-031`). C'est l'intérêt principal de la commande : dupliquer un lot
    de travail récurrent sans en rapporter le chiffrage ne ferait gagner que
    l'arborescence, c'est-à-dire la partie la moins coûteuse à refaire. Le
    doublement silencieux du budget, qui motivait l'hésitation, est traité par
    l'affichage permanent des totaux au-dessus de la grille (`EXG-DEV-017`)
    plutôt qu'en amputant la commande. La troisième voie envisagée — demander au
    moment du collage — est écartée : une question posée à chaque collage
    finirait répondue sans être lue.
18. *Tranchée le 2026-09-12 : la chronologie appartient à la révision.* La
    cohérence entre une composition et l'arbre est ainsi garantie par
    construction (`EXG-PLN-020`, `EXG-PLN-023`). Le seul inconvénient du choix —
    recomposer à chaque revue mensuelle — est levé par le report d'une révision à
    la suivante (`EXG-PLN-024`), qui conserve le travail sans décorréler la
    composition de l'arbre qu'elle désigne.
19. *Tranchée le 2026-09-15 : elles acquièrent au taux d'ensemble du projet.*
    La question visait les lignes de racine ; le cas est plus large, une ligne
    portée par une **récapitulative** ne pouvant pas davantage acquérir
    (`EXG-AVA-012`) — et c'est là que vit le support de tout planning réel. Les
    exclure des deux termes aurait rompu l'identité du §5.1, où le rapport de
    l'avancement physique à la consommation du budget est exactement l'indice de
    coût ; les exclure aussi du côté coût l'aurait préservée, mais aurait fait
    disparaître des indicateurs une dépense qui croît justement quand le planning
    s'allonge. Exiger un rattachement aurait supposé une tâche **feuille**, donc
    une feuille artificielle sans durée sensée ni achèvement observable. Le taux
    d'ensemble laisse la dérive se lire là où elle compte, dans l'indice de coût
    du projet (`EXG-AVA-015`).
20. *Tranchée le 2026-09-13.* Une tâche est « en jeu » quand elle appartient au
    **plan de travail** d'une revue, et l'y faire entrer déclare son démarrage
    (`EXG-RAE-012`, `EXG-RAE-013`). Il n'y a donc pas de statut supplémentaire à
    tenir : l'appartenance au plan de travail est l'état, et le geste qui la
    change est l'acte lui-même — entrer déclare le démarrage, sortir vers le
    dépôt solde le reste à engager. Ce même sens donne enfin au « démarrage »
    d'`EXG-AVA-007` la définition qui lui manquait.
21. *Close le 2026-09-13 : ce n'était pas un défaut.* J'avais relevé que la
    capacité est un nombre d'heures unique par rôle, sans dimension temporelle,
    et proposé de la dater. C'est délibéré et suffisant : l'information utile
    n'est pas dans le niveau mais dans ce qui le dépasse, en amplitude et en
    durée, ce qui suffit à arbitrer entre assumer le retard, prendre un
    intérimaire ou recruter. Le motif est consigné dans `EXG-CHA-007` pour que la
    remarque ne soit pas refaite.
22. *Tranchée le 2026-09-15 : la maille est le domaine et le sens d'accès.*
    Une permission porte sur un domaine, en lecture ou en écriture, et jamais sur
    un acte isolé (`EXG-DRO-015`). Les actes irréversibles ne sont donc pas
    séparés de l'écriture ordinaire : qui écrit sur un domaine finit par recevoir
    le droit d'y conclure, et « écrire sans pouvoir clore » n'a pas d'usage
    identifié — on aurait doublé le catalogue pour une distinction que personne
    ne configure. Le risque qu'ils portent n'est pas qu'une personne non
    autorisée agisse mais qu'une personne autorisée agisse sans voir ce qu'elle
    engageait : il se traite par une confirmation qui nomme les conséquences,
    donc à l'écran et non dans l'habilitation. L'inventaire des domaines se
    construit chapitre par chapitre, comme la question le prévoyait.
23. *Close le 2026-09-13 : une convention suffit.* L'administrateur n'est pas
    exclusif par une règle ; on ne lui accorde simplement aucun rôle métier, et
    l'additivité d'`EXG-DRO-001` reste entière. L'objection — un administrateur
    figure dans l'arbre organisationnel comme tout le monde — est levée par
    `EXG-DRO-013` : le rattachement à un nœud ne confère rien par lui-même, il
    ne fait que délimiter la portée d'un rôle accordé par ailleurs.
24. *Tranchée le 2026-09-13 : c'est une fonction du produit.* Waterfall produit
    et restaure lui-même l'archive (`EXG-ADM-011`), parce que lui seul sait ce
    qui doit être cohérent avec quoi entre la base et le stockage objet. S'y
    ajoute `EXG-ADM-012` : l'archive sort de l'instance qui l'a produite, faute
    de quoi elle disparaîtrait avec la machine qu'elle est censée protéger.
25. *Close le 2026-09-13 : différée avec la trésorerie* (chapitre 23). Elle
    n'existait qu'à cause de l'asymétrie de la courbe — recettes prévisionnelles
    contre dépenses constatées. Sans courbe, l'asymétrie disparaît.
26. *Close le 2026-09-13 : faux problème.* J'avais supposé qu'il fallait un état
    sur le livrable pour le parcourir en revue. Ce n'est pas nécessaire :
    l'avancement du travail est déjà dans les tâches — rédiger, vérifier, livrer
    en sont — et leur achèvement se déduit du reste à engager. Ce que Waterfall
    ne sait pas, c'est l'**acceptation par le client**, information qui lui vient
    de l'extérieur et qu'il n'a pas vocation à porter (chapitre 23). Parcourir
    les livrables en revue, enfin, ne se fait pas nécessairement dans Waterfall :
    la liste est l'artefact, elle se lit.

---

## Annexe C — Écarts avec l'implémentation actuelle

Les chapitres décrivent l'état cible (§3.3). Cette annexe recense les points où
l'implémentation en diffère aujourd'hui. Elle est une liste de travail, pas une
description du produit : elle a vocation à se vider, et à disparaître.

Une partie de ces écarts est déjà prise en charge par un lot en cours — c'est le
cas de tout ce que porte E14 sur la révision et ses facettes. Les autres n'ont
pas de propriétaire, et la colonne « nature » le signale : ce sont ceux qui
demandent une décision de séquencement avant de pouvoir être livrés.

| Exigence | Écart constaté | Nature |
|---|---|---|
| EXG-CYC-002 | Le statut est persisté sous le code `en_reponse_appel_offre`. | Renommage d'une valeur d'énumération persistée. Relève du chapitre 21 pour sa migration, et doit être signalé comme changement de modèle. |
| EXG-PAR-004 | La capacité est stockée sans unité déclarée : ni contrainte, ni description de schéma, ni libellé d'interface ne dit que `available_hours` est un volume mensuel. La table est par ailleurs vide. | Fixer l'unité au mois dans le contrat et dans l'interface, et alimenter le référentiel. |
| EXG-PAR-010 | Les nœuds d'organisation et les calendriers exposent une suppression (`DELETE /resources/nodes/{id}`, `DELETE /resources/calendars/{id}`). Les rôles, les types et les catégories n'en exposent pas. | Retrait des deux routes au profit de la désactivation. |
| EXG-NAV-002 | L'écran Paramètres porte un onglet « Utilisateurs » qui administre les comptes — liste paginée et actions par ligne. L'exigence l'interdit et attribue cette gestion à Administration. | Déplacement de l'onglet vers Administration. |
| EXG-NFO-001 | Le banc publie ses mesures p50 et p95 et n'exécute **aucune assertion** : il ne peut pas échouer, et aucun historique n'est conservé d'une exécution à l'autre. | Conservation des mesures de la branche d'intégration, et comparaison à leur tendance. La référence absolue est écartée : le runner est partagé. |
| EXG-CYC-015 | Les prérequis de configuration sont calculés et exposés, mais **n'empêchent pas** la création : le service qui les produit précise « Never blocks POST /projects ». L'interface se contente d'avertir. | Passage d'un avertissement à un refus. |
| EXG-CYC-016 | Le calcul exige un `CostRate` **par année de consommation**, puis le multiplie par le coefficient d'inflation de cette même année. Il réclame donc une donnée qui n'existe pas, et compte l'inflation deux fois si on la saisit quand même. Bloquant : aucune affectation de rôle n'aboutit sur un planning pluriannuel. | Défaut connu, instruit dans l'issue **#323** (backend et frontend). |
| EXG-VOC-008 | Des opérations de domaine résolvent encore des nœuds par leur uid. | Périmètre d'E14 ; à vérifier à sa clôture. |
| EXG-LOT-004 | Le lotissement est stocké dans le brouillon de structure du planning, c'est-à-dire dans l'ancêtre direct de la révision — exactement l'endroit dont ce chapitre le sort. | Déplacement au niveau projet. |
| EXG-LOT-006 | La génération est additive et idempotente : elle met à jour et supprime les tâches précédemment générées quand elles disparaissent de la structure soumise. | Retrait de la propagation, au squelette seulement. |
| EXG-LOT-007 | La route d'enregistrement du brouillon documente qu'elle ne change jamais le statut du projet. | Inversion du contrat. |
| EXG-LOT-009 | Une route dédiée permet de « passer » l'étape de lotissement ; elle n'existait que parce que le lotissement barrait l'accès au planning. | Suppression devenue possible. |
| EXG-LOT-011 | Rien ne permet de savoir si un planning a été retouché depuis sa génération. | Marqueur à créer, et endpoint d'état du planning à exposer. |
| EXG-SPR-001 | Le CRUD des sous-projets existe côté serveur, mais aucun écran ne l'appelle : les projets en base n'ont que leur racine, et aucune ligne de coût n'est ventilée. | Écran à construire ; le modèle suffit. |
| EXG-SPR-006 | Renommer un code de sous-projet n'émet aucun avertissement, alors que le rapprochement des coûts réels en dépend. | Garde-fou à ajouter. |
| EXG-PLN-008 | Le service d'arbre interdit qu'un jalon porte des enfants ; le module de domaine pur qui le remplacera ne porte pas encore cette garde. | Décidé : la garde est conservée (#343). À porter dans le module de domaine, avec sa couverture d'invariant, avant la suppression du service. |
| EXG-PLN-004 | Le serveur refuse une tâche automatique sans ancrage ni prédécesseur, au lieu de la caler au début du projet. Ce refus interdit la saisie en masse des libellés avant les liens. | Remplacement du refus par un défaut. |
| EXG-PLN-013 | Les jeux de colonnes enregistrés et les colonnes figées n'existent pas. | Ajout à la table. |
| EXG-PLN-018 à 019 | Le couper/copier/coller et l'annulation d'un déplacement n'existent pas. La sélection multiple et la commande de déplacement, elles, existent déjà : le collage se ramène à cette commande. | Ajout à la table, sans opération serveur nouvelle pour le déplacement. |
| EXG-PLN-019 | Aucun historique d'édition n'existe, ni côté table ni côté serveur. | Ajout. La restitution des dates propagées en est la part délicate. |
| EXG-VOC-007 | Le compteur de concurrence s'appelle littéralement `revision`, sur le devis comme sur le planning — au moment même où E14 introduit un objet « révision ». L'homonymie proscrite est donc déjà dans le modèle. | Renommage, à traiter avec le modèle cible (chapitre 21). |
| EXG-DEV-005 | Voir la ligne EXG-CYC-016 : le calcul exige un taux par année de consommation et compte l'inflation deux fois (#323). | Même correctif. |
| EXG-DEV-005 | Le coefficient d'inflation est lu pour la seule année de consommation et appliqué une fois, sans cumul depuis l'année de référence. Une charge consommée deux ans après le chiffrage ne subit donc qu'une année d'inflation. Défaut distinct de celui d'#323, et qui subsisterait après son correctif. | Passage à un cumul. |
| EXG-DEV-006 | Les heures sont divisées par le **nombre d'années traversées**, non réparties au prorata du temps : une tâche du 20 décembre au 10 janvier est découpée en deux moitiés égales. La règle n'est par ailleurs énoncée nulle part dans le résultat. | Passage au prorata temporel, et restitution de la règle. |
| EXG-DEV-005, EXG-DEV-019 | Le moteur n'applique **aucune** inflation aux lignes non main-d'œuvre : il fige `inflation_coefficient` à 1 et calcule `quantité × débours unitaire`. Aucune année n'est donc dérivée pour un débours. | Changement de calcul, non d'affichage : les montants produits par la validation d'un devis changent. Les tests qui figent des montants non-MO changeront de valeur attendue, et il faudra vérifier qu'ils sont corrigés dans le bon sens plutôt qu'ajustés jusqu'à repasser au vert. Les devis déjà validés ne sont pas recalculés, leurs lignes étant figées : un devis validé avant et un devis validé après ne sont pas comparables à périmètre égal, ce qui est à acter à la livraison. |
| EXG-DEV-014 | La grille recalcule elle-même un aperçu de montant, à taux unique, en ne retenant que la première année de la tâche porteuse et sans appliquer l'inflation. Le montant lu à l'écran s'écarte donc de celui que produit la validation, sans que rien ne le signale — l'écart n'a rien de marginal sur une ligne portée par une récapitulative de plusieurs années. | Les deux montants passent par l'API. La logique dupliquée côté grille est retirée, non complétée : la compléter reviendrait à maintenir deux implémentations du même calcul. |
| EXG-DEV-014 | Un seul montant est affiché ; l'effet de l'inflation est invisible. | Ajout d'une colonne. |
| EXG-DEV-021, EXG-DEV-022 | Une ligne de coût sans tâche porteuse est datée de l'**année civile courante**, sur une seule année et quelle que soit sa nature (`_bearing_years`, `services/estimate_calculation.py`). Les années du projet ne sont dérivées nulle part. Une facette de coût se replie par ailleurs sur la **date prévisionnelle de décaissement** (`default_breakdown`, `domain/revision/pricing.py`), que la cible refuse de lire pour valoriser. | Dérivation des années du projet depuis les seules dates de planification de la révision ; prorata sur ces années pour la main-d'œuvre de racine, année de début pour le débours. Comme pour l'écart EXG-DEV-005/EXG-DEV-019, les montants produits changent : les tests qui figent un montant de ligne de racine changeront de valeur attendue, et il faudra vérifier qu'ils sont corrigés dans le bon sens plutôt qu'ajustés jusqu'à repasser au vert. |
| EXG-DEV-020 | L'inflation est stockée dans le référentiel commun, sous la forme d'une **série annuelle** — un coefficient par année, unique par année et partagé par tous les projets. La cible est un coefficient unique porté par le projet. | Déplacement de l'attribut vers le projet, et abandon de la dimension annuelle. Les révisions validées figent déjà leur coefficient (`EXG-PAR-011`), donc rien de validé ne bouge. |
| EXG-RAE-001 à 010 | Rien n'existe : `forecast_remaining` n'est qu'une valeur d'énumération réservée, sans colonne de reste à engager, sans service ni écran. Le chapitre entier décrit une cible. | Périmètre d'E10 (#250), non livré. |
| EXG-RAE-005 | E10 prévoit un pointeur vers la ligne source ; la cible est l'identité de l'élément de travail, qui seule survit à un remaniement du devis de référence. | Écart entre un EPIC antérieur et la cible : E10 a été écrit avant E14, à reprendre à sa livraison. |
| EXG-CRE-001 à 010 | Rien n'existe : ni modèle de pièce comptable, ni import, ni écran. Le chapitre entier décrit une cible. | Périmètre d'E11 (#255), non livré. |
| EXG-CRE-006 à 008 | L'exclusion de périmètre n'est prévue par aucun EPIC. | Ajout au périmètre d'E11, ou lot propre. |
| EXG-AVA-001 à 014 | Aucun calcul de valeur acquise n'existe : il dépend du reste à engager (E10) et du coût réel (E11), non livrés. | Cible entière. |
| EXG-CHA-002 à 004 | Aucune vue multiprojets n'existe. | Cible entière. |
| EXG-ANA-016 | Le calcul des dates ne fait qu'une passe avant, des prédécesseurs vers les successeurs. Le chemin critique demande en outre une passe arrière pour établir les marges ; elle n'existe pas. | Ajout au calcul d'ordonnancement. |
| EXG-DRO-001 à 010 | Il n'existe ni rôle d'habilitation, ni permission, ni portée : un utilisateur porte un unique drapeau d'administrateur. | Cible entière. |
| EXG-DRO-003 | L'arbre des ressources existe mais ne porte aucune habilitation. | Réemploi, sans second arbre à créer. |
| EXG-DRO-011 | Aucun modèle ne relie un utilisateur à l'organisation : ni nœud, ni rôle de ressource. Un compte est une adresse et un mot de passe, à côté de l'arbre. C'est le prérequis de tout le chapitre 18. | Ajout au modèle, **hors périmètre d'E14**, à traiter avant le reste du chapitre. |
| EXG-DRO-012 | Un projet ne déclare aucun besoin en services. | Ajout au modèle et à l'onglet Général. |
| EXG-DRO-014 | Le seul contrôle existant teste un drapeau d'administrateur, donc un rôle. | À remplacer par des permissions dès que le catalogue existe. |
| EXG-ADM-001 à 008 | Aucune administration n'existe : ni écran de comptes, ni sauvegarde, ni restauration, ni trace. | Cible entière. |
| EXG-ADM-007 | Aucun modèle de trace n'existe, alors que trois exigences déjà écrites s'y réfèrent — clôture définitive, retour en arrière sur un achèvement, motif et auteur d'une exclusion de périmètre. | Ajout au modèle, **hors périmètre d'E14**. Le plus urgent d'entre eux : les chapitres qui s'y appuient ne peuvent pas être livrés avant lui. |
| EXG-ADM-009 à 010 | Les sondes d'état et l'historique des imports existent côté serveur, sans écran qui les expose. | Écran à construire ; le socle suffit. |
| EXG-ADM-010 | Le journal d'import ne porte pas son auteur : on sait quel fichier a été importé, quand et avec quel résultat, jamais par qui. | Ajout d'une colonne. |
| EXG-DRO-006 | Un projet porte un propriétaire unique, et la liste des projets filtre dessus : nul autre ne le voit. | Remplacement de la propriété par l'appartenance (chapitre 21). |
| EXG-MOD-023 | Une révision porte un commentaire libre mais aucun nom : elle ne se désigne que par son numéro et sa nature. | Ajout d'un attribut, et de sa proposition par défaut. |
| EXG-CYC-004 | Le pointeur de révision unique existe et est écrit, mais le contrôle du passage en pilotage teste toujours les **deux** anciennes références, un planning et un devis. La condition « au moins une tâche » porte sur le planning référencé. | Basculer le contrôle sur la désignation unique, qui porte les deux facettes. |
| EXG-NFO-016 | L'import s'exécute dans la requête qui le déclenche. Le modèle de lot porte pourtant déjà un statut et des horodatages de début et de fin, donc anticipe une exécution différée. | Passage à une exécution hors requête. |
| EXG-NFO-018, EXG-NFO-019 | Redis est présent mais ne sert qu'à limiter les tentatives de connexion : aucun cache applicatif n'existe. | Rien à corriger ; les règles s'appliqueront au premier cache posé. |
| EXG-NFO-010, EXG-NFO-011 | Les refus du serveur sont des phrases rédigées en anglais, que l'interface affiche faute de code reconnu. Tout refus remonté à l'utilisateur est donc en anglais dans une interface française. | Passage à des codes de refus, qui conditionne aussi toute internationalisation. |
| EXG-MOD-024, EXG-MSP-013 | La note d'une tâche vit à deux endroits : sur l'instantané de version, alimenté par l'import, et sur un enrichissement au niveau projet. L'export préfère le premier. Deux dépôts de la même information, dont un seul survit aux versions. | Fusion sur l'attribut de projet, avec la règle de non-écrasement. |
| EXG-MOD-007 | Le modèle de révision est livré, mais **de façon additive** : `ms_task` et `wf_planning_task_snapshot` coexistent toujours avec lui. Pour les tâches les deux anciennes tables sont écrites ; pour les liens de précédence, seule celle de la version l'est. Sur un fichier de 1170 liens, la table de projet reste vide, et tout code qui la lit voit un planning sans aucune dépendance. | Retrait des anciennes tables une fois tous leurs consommateurs migrés. Le doublement subsiste jusque-là, et cette divergence n'est pas recensée parmi les cinq qu'E14 énumère. |
| EXG-PLN-025 | Le calcul du devis écarte silencieusement une tâche sans dates : ses heures ne produisent aucune ligne de coût et manquent au budget de référence. L'état devenant inatteignable, ce chemin doit signaler une erreur plutôt que retourner discrètement un résultat vide. | Transformer un écartement muet en échec explicite. |
| EXG-PLN-025 | `is_manual` est nullable, au motif qu'un fichier importé pourrait ne pas porter l'indicateur de mode. La mesure ne le confirme pas : aucune des deux mille six cent soixante-six tâches examinées n'en manque, et l'élément ne figure pas au schéma officiel Microsoft mais au seul sous-ensemble canonique de Waterfall. | Nullabilité défensive à réexaminer avec le modèle cible (chapitre 21). |
| EXG-ANA-001 à 017 | L'onglet d'analyse existant est scopé à un seul devis et n'agrège rien. Le tableau de bord, l'organigramme, les projections et le chemin critique n'existent que dans la maquette. | Cible entière, conditionnée à E10 et E11. |
| EXG-AVA-003, EXG-PLN-001 | Trois comportements coexistent aujourd'hui pour l'indicateur d'avancement d'une tâche : `avancement-v0.1` affirme qu'il n'est pas utilisé, ajoute qu'un ré-import MS Project l'écrase, et E10 prévoit que le calcul l'écrive à 100. La cible tranche : il est un résultat, et l'import ne retient ni ne réécrit ce champ. | Contradiction à résoudre à la livraison d'E10. |
| EXG-PLN-020, 023, 024, 026 | Ni la chronologie ni l'ensemble des jalons suivis n'existent comme objets : ni composition, ni nom, ni rattachement. | Ajout au modèle, portés par la révision — plusieurs chronologies, un seul ensemble de jalons suivis — et reportés par copie à la révision suivante. |

Un écart absent de cette table n'est pas un écart connu : il n'a pas été
cherché. Le recensement systématique se fera chapitre par chapitre, à mesure de
leur rédaction.
