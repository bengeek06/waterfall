# Reexport MS Project multi-version (2010/2013/2016)

## 1) Constats issus des XSD

1. Les XSD 2010, 2013 et 2016 utilisent le meme namespace XML:
- http://schemas.microsoft.com/project/2007
- Voir [schemas/2010/project_2010_schema.xml](schemas/2010/project_2010_schema.xml#L23), [schemas/2013/project_2013_schema.xml](schemas/2013/project_2013_schema.xml#L23), [schemas/2016/project_2016_schema.xml](schemas/2016/project_2016_schema.xml#L23)

2. Les structures principales sont equivalentes entre versions:
- Project, Calendars, Tasks, Resources, Assignments, ExtendedAttributes, OutlineCodes, WBSMasks

3. Les durees de planning doivent etre en xsd:duration (ISO 8601), pas en "5d" ou "40h":
- Voir [schemas/2016/tasks_2016_schema.xml](schemas/2016/tasks_2016_schema.xml#L108)
- Voir [schemas/2016/assignments_2016_schema.xml](schemas/2016/assignments_2016_schema.xml#L315)

4. Les liens de dependance ont un typage strict:
- Type: 0=FF, 1=FS, 2=SF, 3=SS
- LinkLag: dixiemes de minute
- Voir [schemas/2016/tasks_2016_schema.xml](schemas/2016/tasks_2016_schema.xml#L579)
- Voir [schemas/2016/tasks_2016_schema.xml](schemas/2016/tasks_2016_schema.xml#L602)

5. Les calendriers ont des DayType stricts:
- 0=Exception, 1=Sunday, 2=Monday, ..., 7=Saturday
- Voir [schemas/2016/calendars_2016_schema.xml](schemas/2016/calendars_2016_schema.xml#L53)

## 2) Analyse de synthese.xml

Fichier analyse: [schemas/synthese.xml](schemas/synthese.xml)

Points positifs:
- Bonne granularite fonctionnelle (Calendars, Tasks, Resources, Assignments)
- Presence des liens de precedence et des charges
- Bonne base pour la cible metier

Points a corriger pour un reexport robuste:
1. Namespace racine
- Actuel: http://schemas.microsoft.com/project
- Recommande: http://schemas.microsoft.com/project/2007

2. Durees
- Actuel: 10d, 40h, 20h
- Recommande xsd:duration: P10D ou PT80H, PT40H, PT20H

3. DayType calendrier
- Le schema attend Sunday=1, Monday=2, ... Saturday=7
- Le fichier contient une incoherence de mapping (Sunday et Monday confondus)

4. Champs Project utilitaires pour round-trip
- Ajouter CalendarUID (calendar projet)
- Ajouter MinutesPerDay, MinutesPerWeek, DaysPerMonth (stabilise les conversions de duree)

5. Tasks resumees
- Pour une tache parent, preferer explicitement Summary=true et Milestone selon besoin

## 3) Schema canonique interne recommande (version-agnostic)

Conserver un modele interne stable, puis faire un mapper vers XML cible.

## 3.1) Workflow fonctionnel cible (valide)

1. Import standard (par defaut)
- Importer seulement les taches et dependances depuis le fichier MS Project.
- Ne pas importer charges et ressources par defaut.

2. Import avance (option utilisateur)
- Option possible: importer aussi ressources et affectations existantes du fichier MS Project.

3. Enrichissement metier hors MS Project
- Export Excel de saisie des charges par tache.
- Affectation des ressources via Excel (mode non nominatif, conforme au cycle de vie cible).
- Reimport Excel pour enrichir la base.

4. Reexport MS Project
- Produire un XML conforme pour ouvrir dans MS Project.
- Injecter charges, ressources et affectations issues de la base enrichie.

### Entites coeur

1. project
- id
- source_version (2010|2013|2016)
- save_version_out (14|15|16)
- name
- schedule_from_start
- start_date
- finish_date
- calendar_uid
- minutes_per_day
- minutes_per_week
- days_per_month
- currency_code

2. calendar
- uid
- name
- is_base_calendar
- base_calendar_uid

3. calendar_weekday
- calendar_uid
- day_type (0..7)
- day_working (bool)

4. calendar_working_time
- calendar_uid
- day_type
- from_time
- to_time

5. calendar_exception
- calendar_uid
- name
- from_date
- to_date
- recurrence_type
- period
- days_of_week_mask

6. task
- uid
- id_display
- name
- type (0|1|2)
- outline_number
- outline_level
- wbs
- start
- finish
- duration_minutes
- work_minutes
- percent_complete
- is_summary
- is_milestone
- calendar_uid

7. task_link
- task_uid
- predecessor_uid
- link_type (0=FF,1=FS,2=SF,3=SS)
- lag_tenth_minute
- lag_format

8. resource
- uid
- id_display
- name
- type (0 material, 1 work)
- max_units
- standard_rate
- overtime_rate
- calendar_uid

9. assignment
- uid
- task_uid
- resource_uid
- units
- work_minutes
- actual_work_minutes
- remaining_work_minutes
- start
- finish

10. extended_attribute_def
- field_id
- field_name
- cf_type
- elem_type (20 task, 21 resource, 23 assignment)
- alias

11. extended_attribute_value
- elem_type
- owner_uid
- field_id
- value

## 3.2) Convention de nommage des tables

La convention proposee est judicieuse et recommandee:

1. Prefixe ms_
- Pour les tables refletant le modele d'interchange MS Project (UID, liens, calendriers, etc.).
- Exemple: ms_project, ms_task, ms_task_link, ms_calendar, ms_resource, ms_assignment.

2. Prefixe wf_
- Pour les tables metier/API propres a Waterfall (saisie, workflow, regles, historisation).
- Exemple: wf_import_batch, wf_excel_sheet, wf_charge_line, wf_resource_pool, wf_allocation_rule.

3. Avantage
- Separation claire entre couche d'interoperabilite et couche metier.
- Facilite la tracabilite, les migrations et le debug du round-trip XML.

## 4) Contrat de reexport minimal (MVP stable)

Pour ton use case (import standard taches/dependances + enrichissement Excel):

1. Project
- SaveVersion, Name, ScheduleFromStart, StartDate/FinishDate, CalendarUID
- MinutesPerDay, MinutesPerWeek, DaysPerMonth

2. Calendars
- Au moins 1 base calendar
- WeekDays coherents

3. Tasks
- UID obligatoire
- ID, Name
- Start, Finish, Duration (xsd:duration)
- OutlineNumber, OutlineLevel
- PercentComplete
- PredecessorLink (si dependances)

4. Resources
- UID, ID, Name, Type
- MaxUnits
- StandardRate
- CalendarUID

Note: ce bloc peut etre vide lors du premier import standard. Il devient actif apres enrichissement Excel.

5. Assignments
- UID, TaskUID, ResourceUID
- Units
- Work, ActualWork, RemainingWork (xsd:duration)

Note: ce bloc peut etre vide lors du premier import standard. Il devient actif apres enrichissement Excel.

6. Couts budgetises
- Le schema MS Project supporte explicitement BudgetCost et BudgetWork sur Assignment.
- Voir [schemas/2016/assignments_2016_schema.xml](schemas/2016/assignments_2016_schema.xml#L384)
- Recommandation: stocker en base le cout budgetise au niveau affectation (wf_charge_line -> ms_assignment.BudgetCost) pour conserver un mapping simple et explicite au reexport.

## 5) Strategie multi-version

1. Interne: toujours schema canonique
2. Export: adapter uniquement:
- SaveVersion (14/15/16)
- Eventuels champs optionnels version-cible
3. Namespace XML: rester sur /2007 pour compatibilite 2010/2013/2016

## 6) Rappels de mapping critiques

1. Unites
- Duration/Work stockees en minutes en base
- Export en xsd:duration (ex: PT480M pour 1 jour a 8h)

2. Lag dependance
- LinkLag en dixiemes de minute
- Exemple: 1 jour (8h) => 480 min => 4800

3. Calendrier
- DayType: 1 Sunday, 2 Monday, ..., 7 Saturday
- Ne pas inverser Sunday/Monday

## 7) Recommandation d implementation

1. Ecrire un validateur interne avant export XML:
- UID uniques
- references TaskUID/ResourceUID valides
- au moins un calendar de base
- durees non negatives

2. Ecrire un exporter deterministe:
- tri stable (UID asc)
- generation XML avec namespace /2007
- options de cible (SaveVersion=14/15/16)

3. Valider a minima avec:
- ouverture dans MS Project 2010, 2013, 2016
- reimport immediat (round-trip) et comparaison de:
  - taches
  - liens
  - charges
  - affectations

## 8) Modele SQL detaille

Le detail des tables proposees ms_ / wf_ (colonnes, contraintes, index, workflow) est documente dans:
- [schemas/modele_donnees_v1_ms_wf.md](schemas/modele_donnees_v1_ms_wf.md)
