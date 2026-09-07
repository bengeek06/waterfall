---
name: deliver-batch
description: Livre en autonomie une liste d'issues GitHub de ce repo Waterfall sur la branche develop, sans intervention manuelle - une branche par issue, boucle revue locale -> correction -> revue jusqu'au vert, findings hors du scope de l'issue routes vers une nouvelle issue plutot que corriges sur place, merge dans develop, puis rapport de synthese pour le point de verification matin/soir de l'utilisateur. A utiliser quand l'utilisateur donne une liste de numeros d'issues a traiter pendant qu'il n'est pas disponible.
---

# deliver-batch

## Quand l'utiliser

L'utilisateur donne une liste de numéros d'issues (typiquement le matin avant de partir travailler, ou le soir avant de se coucher) et veut les voir traitées jusqu'à un état mergé sans avoir à intervenir avant son prochain point de vérification.

## Autorisation et limites (à ne jamais dépasser)

- L'utilisateur n'a pas les droits de merge sur `main`. `develop` est la branche d'intégration sur laquelle ce skill opère en autonomie complète : créer des branches, pousser, ouvrir des PR **et les merger** sans confirmation à chaque fois — c'est l'objet même de ce skill.
- Cette autorisation ne porte que sur `develop`. Ne jamais pousser, merger, forcer un push ou supprimer une branche sur `main` sans confirmation explicite de l'utilisateur pour cette action précise. Le passage `develop` → `main` reste la tâche du point de vérification de l'utilisateur, pas de ce skill.
- Si `develop` n'existe pas encore, la créer depuis `main` à jour (`git checkout main && git pull && git checkout -b develop && git push -u origin develop`) et le signaler avant de continuer.

## Limite d'usage de session

Si la limite d'usage de session est atteinte en cours de lot (requêtes refusées/throttlées) :

- Ne jamais considérer le lot comme abandonné ou terminé pour cette seule raison. Noter précisément l'état atteint (issue en cours, étape de la boucle, état de la branche/PR) pour pouvoir reprendre exactement là, pas depuis le début du lot.
- La limite se réinitialise toutes les 5 heures, et il faut au moins 3 heures d'activité pour l'atteindre : revérifier **toutes les heures** suffit donc à reprendre au plus tard une heure après le reset réel, sans vérifier inutilement plus souvent.
- Si le lot tourne sous `/loop` ou un agent planifié, utiliser `ScheduleWakeup` (ou le mécanisme de reprise équivalent) avec un délai d'environ une heure (`delaySeconds` ~3600) pour revérifier la disponibilité, plutôt qu'un délai plus court (n'accélère pas le reset) ou plus long (retarde la reprise sans raison).
- Dès que la limite est de nouveau disponible, reprendre le lot à l'endroit noté plutôt que de recommencer les issues déjà traitées.

## Entrée

Une liste de numéros d'issues (et éventuellement l'EPIC parent). Si l'ordre de dépendance n'est pas évident à la lecture de la demande, le déduire du corps de chaque issue (`Dépend de #N`) plutôt que de traiter dans l'ordre donné tel quel.

## Boucle par issue

Reprend le fond des étapes 1 à 6 de l'agent `epic-delivery-orchestrator` (cadrage de l'issue, analyse du code existant, délégation aux agents `python-fastapi-expert`/`js-react-next-expert`, style de commit), avec les différences suivantes propres au mode batch non supervisé :

1. **Base et cible** : `develop`, jamais `main`. Branche par issue depuis `develop` à jour (`git checkout develop && git pull && git checkout -b <nom>`), même convention de nommage que d'habitude (`feat/<n>-<slug>` / `fix/<n>-<slug>`).
2. **Revue locale jusqu'au vert** : lance le(s) reviewer(s) concerné(s) (`python-fastapi-reviewer` et/ou `js-react-next-reviewer`), fais corriger par l'agent développeur, relance la revue, répète. Ce cycle a toujours fini par converger jusqu'ici (aucun blocage observé, y compris sur 10 rounds). Plafond de sécurité propre au mode non supervisé : **12 itérations** par issue — au-delà, arrête cette issue précise (branche/PR laissée en l'état, non mergée), marque-la « bloquée » dans le rapport de synthèse avec le dernier finding non résolu, et passe à l'issue suivante de la liste. Ne jamais rester bloqué indéfiniment sur une seule issue en l'absence de l'utilisateur.
3. **Findings hors du scope de l'issue en cours** : ne pas les corriger sur place. Ouvrir une nouvelle issue GitHub (`gh issue create`) décrivant le finding (fichier, ligne, symptôme, et l'issue/PR où il a été découvert) ; si l'EPIC parent est identifiable, la rattacher en sous-issue. Continuer le traitement de l'issue en cours sans attendre de retour sur ce nouveau ticket.
4. **Gates** : avant de pousser, exécuter les commandes de qualité pertinentes selon le périmètre touché (lint/typecheck/tests backend et/ou frontend — mêmes commandes qu'à l'étape 6 de `epic-delivery-orchestrator`).
5. **Push et PR** : `git push -u origin <branche>`, `gh pr create --base develop --head <branche>`, corps de PR au format déjà en usage dans ce repo (Résumé, points vérifiés, revue locale, plan de test).
6. **Merge** : une fois la revue locale au vert et les gates passées (et la revue Copilot si elle se déclenche et répond avant que le délai ne devienne bloquant), merger la PR dans `develop` directement (`gh pr merge --squash` ou le mode déjà utilisé dans ce repo) — aucune confirmation utilisateur requise à cette étape précise sur `develop`. Fermer l'issue seulement si son comportement a réellement été vérifié (tests + gates), pas sur la seule base du merge — via `Closes #N` dans le corps de la PR ou fermeture manuelle explicite après vérification.
7. Passer à l'issue suivante de la liste.

Ne jamais lancer deux issues de la liste en parallèle si elles touchent des fichiers communs ou qu'une dépendance les relie — dans le doute, traiter séquentiellement.

## Rapport de synthèse (à la fin du lot, pour le point de vérification)

### Issues livrées (mergées dans develop)
Numéro, titre, lien PR, commandes de validation exécutées et résultat réel.

### Nouvelles issues créées (findings hors scope)
Numéro, titre, lien, issue/PR d'origine où le finding a été rencontré.

### Issues bloquées
Numéro, état de la branche/PR, plafond d'itération atteint, dernier finding non résolu, ce qu'il resterait à trancher.

### État develop vs main
`git log main..develop --oneline` (ou équivalent), prêt ou non pour une promotion vers `main`.

### Prochaine action
Une seule action prioritaire pour l'utilisateur à ce point de vérification.
