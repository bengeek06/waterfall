# Checklist d'acceptation planning

Issue de reference : #14.

## Versionnage et brouillons

- [x] Sauvegarde et lecture d'un brouillon de structure.
- [x] Generation d'un planning hierarchique.
- [x] Validation d'une version brouillon.
- [x] Designation et selection d'une version de reference.
- [x] Selection de la version affichee.
- [x] Edition directe d'une tache dans un planning brouillon.
- [x] Rejet de l'edition directe d'une version validee.
- [x] Rejet de l'edition directe pour un projet en lecture seule.

## Import, diff et round-trip

- [x] Import XML et creation d'un brouillon.
- [x] Diff non mutatif avant confirmation.
- [x] Confirmation obligatoire avant mutation.
- [x] Import d'une modification apres validation de la version precedente.
- [x] Preservation de la version validee et creation d'une nouvelle version brouillon.
- [x] Export de la nouvelle version.
- [x] Reimport de controle de l'export dans un second projet.

## Performance PostgreSQL

- [x] Lecture d'un planning de 1 000 taches : 5 echauffements et 30 mesures.
- [x] Mutation representative : 5 echauffements et 30 mesures.
- [x] Publication des valeurs p50/p95 sans seuil bloquant sur runner partage.

Derniere mesure locale : lecture p50 32,55 ms / p95 78,06 ms ; mutation p50 52,40 ms / p95 97,78 ms.

## Hors perimetre

- Tests E2E navigateur : reportes a #89 jusqu'a stabilisation de l'interface.
- Copie d'une version hierarchique via `source_planning_id` : anomalie suivie dans #103.
