# Modele de donnees V1 (ms_ / wf_)

## Objectif

Definir un schema SQL cible pour:
1. Import standard MS Project: taches + dependances uniquement.
2. Enrichissement metier via Excel: charges, cout budgetise, affectations de ressources.
3. Reexport XML MS Project multi-version.

## Principes de structuration

1. Prefixe ms_
- Tables de projection du modele d'interchange MS Project.
- Stables et proches des structures XML.

2. Prefixe wf_
- Tables de workflow et logique metier Waterfall.
- Pilotent import, enrichissement Excel, affectation et export.

3. Strategie de temps
- Stockage interne en minutes (entier) pour les durees/charges.
- Conversion en xsd:duration au reexport.

## Profil d'import

1. Profil standard
- Importe seulement ms_task et ms_task_link.
- Cree un projet technique ms_project + calendrier de reference minimal.
- N'importe pas ms_resource et ms_assignment.

2. Profil complet (optionnel)
- Importe aussi ms_resource et ms_assignment.

## Tables ms_ (interoperabilite)

### ms_project
- id (pk)
- external_uid (varchar(16), nullable)
- source_version (smallint, check in (2010, 2013, 2016))
- save_version_out (smallint, check in (14, 15, 16), default 16)
- name (varchar(255), not null)
- schedule_from_start (boolean, not null, default true)
- start_date (timestamptz, nullable)
- finish_date (timestamptz, nullable)
- calendar_uid (integer, nullable)
- minutes_per_day (integer, not null, default 480)
- minutes_per_week (integer, not null, default 2400)
- days_per_month (integer, not null, default 20)
- currency_code (char(3), nullable)
- created_at (timestamptz, not null)
- updated_at (timestamptz, not null)

Contraintes:
- ck_ms_project_schedule_dates:
  - schedule_from_start = true => start_date non null
  - schedule_from_start = false => finish_date non null

Index:
- idx_ms_project_name

### ms_calendar
- id (pk)
- project_id (fk -> ms_project.id, not null)
- uid (integer, not null)
- name (varchar(255), not null)
- is_base_calendar (boolean, not null, default false)
- base_calendar_uid (integer, nullable)

Contraintes:
- uq_ms_calendar_project_uid (project_id, uid)

### ms_calendar_weekday
- id (pk)
- calendar_id (fk -> ms_calendar.id, not null)
- day_type (smallint, check between 0 and 7)
- day_working (boolean, not null)

Contraintes:
- uq_ms_calendar_weekday (calendar_id, day_type)

### ms_calendar_working_time
- id (pk)
- weekday_id (fk -> ms_calendar_weekday.id, not null)
- from_time (time, not null)
- to_time (time, not null)

Contraintes:
- ck_ms_calendar_working_time_range (from_time < to_time)

### ms_task
- id (pk)
- project_id (fk -> ms_project.id, not null)
- uid (integer, not null)
- id_display (integer, nullable)
- name (varchar(512), not null)
- task_type (smallint, check in (0,1,2), nullable)
- outline_number (varchar(512), nullable)
- outline_level (integer, nullable)
- wbs (varchar(255), nullable)
- start_at (timestamptz, nullable)
- finish_at (timestamptz, nullable)
- duration_minutes (integer, nullable)
- duration_format (smallint, nullable)
- work_minutes (integer, nullable)
- percent_complete (smallint, nullable)
- is_summary (boolean, not null, default false)
- is_milestone (boolean, not null, default false)
- calendar_uid (integer, nullable)
- created_at (timestamptz, not null)
- updated_at (timestamptz, not null)

Contraintes:
- uq_ms_task_project_uid (project_id, uid)
- ck_ms_task_percent_complete (percent_complete between 0 and 100)
- ck_ms_task_duration_non_negative (duration_minutes is null or duration_minutes >= 0)
- ck_ms_task_work_non_negative (work_minutes is null or work_minutes >= 0)

Index:
- idx_ms_task_project_outline (project_id, outline_level, outline_number)
- idx_ms_task_project_id_display (project_id, id_display)

### ms_task_link
- id (pk)
- project_id (fk -> ms_project.id, not null)
- task_uid (integer, not null)
- predecessor_uid (integer, not null)
- link_type (smallint, check in (0,1,2,3), not null, default 1)
- lag_tenth_minute (integer, nullable)
- lag_format (smallint, nullable)

Contraintes:
- uq_ms_task_link (project_id, task_uid, predecessor_uid, link_type)
- fk_ms_task_link_task (project_id, task_uid) -> ms_task(project_id, uid)
- fk_ms_task_link_pred (project_id, predecessor_uid) -> ms_task(project_id, uid)

Index:
- idx_ms_task_link_task_uid (project_id, task_uid)
- idx_ms_task_link_predecessor_uid (project_id, predecessor_uid)

### ms_resource
- id (pk)
- project_id (fk -> ms_project.id, not null)
- uid (integer, not null)
- id_display (integer, nullable)
- name (varchar(512), not null)
- resource_type (smallint, check in (0,1), not null, default 1)
- max_units (numeric(8,4), nullable)
- standard_rate (numeric(12,2), nullable)
- overtime_rate (numeric(12,2), nullable)
- calendar_uid (integer, nullable)
- is_cost_resource (boolean, nullable)
- created_at (timestamptz, not null)
- updated_at (timestamptz, not null)

Contraintes:
- uq_ms_resource_project_uid (project_id, uid)

### ms_assignment
- id (pk)
- project_id (fk -> ms_project.id, not null)
- uid (integer, not null)
- task_uid (integer, not null)
- resource_uid (integer, not null)
- units (numeric(8,4), nullable)
- work_minutes (integer, nullable)
- actual_work_minutes (integer, nullable)
- remaining_work_minutes (integer, nullable)
- budget_cost (numeric(14,2), nullable)
- budget_work_minutes (integer, nullable)
- start_at (timestamptz, nullable)
- finish_at (timestamptz, nullable)
- created_at (timestamptz, not null)
- updated_at (timestamptz, not null)

Contraintes:
- uq_ms_assignment_project_uid (project_id, uid)
- fk_ms_assignment_task (project_id, task_uid) -> ms_task(project_id, uid)
- fk_ms_assignment_resource (project_id, resource_uid) -> ms_resource(project_id, uid)
- ck_ms_assignment_work_non_negative
- ck_ms_assignment_actual_work_non_negative
- ck_ms_assignment_remaining_work_non_negative

Index:
- idx_ms_assignment_task (project_id, task_uid)
- idx_ms_assignment_resource (project_id, resource_uid)

### ms_extended_attribute_def
- id (pk)
- project_id (fk -> ms_project.id, not null)
- field_id (varchar(64), not null)
- field_name (varchar(255), nullable)
- cf_type (smallint, nullable)
- elem_type (smallint, nullable)
- alias (varchar(255), nullable)

Contraintes:
- uq_ms_ext_attr_def (project_id, field_id)

### ms_extended_attribute_value
- id (pk)
- project_id (fk -> ms_project.id, not null)
- elem_type (smallint, not null)
- owner_uid (integer, not null)
- field_id (varchar(64), not null)
- value_text (text, nullable)
- value_number (numeric(18,6), nullable)
- value_date (timestamptz, nullable)

Index:
- idx_ms_ext_attr_value_owner (project_id, elem_type, owner_uid)

## Tables wf_ (workflow metier)

### wf_import_batch
- id (pk)
- project_id (fk -> ms_project.id, nullable)
- import_mode (varchar(16), check in ('standard','full'), not null)
- source_filename (varchar(512), not null)
- source_sha256 (varchar(64), nullable)
- started_at (timestamptz, not null)
- finished_at (timestamptz, nullable)
- status (varchar(16), check in ('running','success','failed'), not null)
- log_json (jsonb, nullable)

### wf_excel_import
- id (pk)
- project_id (fk -> ms_project.id, not null)
- import_batch_id (fk -> wf_import_batch.id, nullable)
- filename (varchar(512), not null)
- sha256 (varchar(64), nullable)
- started_at (timestamptz, not null)
- finished_at (timestamptz, nullable)
- status (varchar(16), check in ('running','success','failed'), not null)
- log_json (jsonb, nullable)

### wf_resource_pool
- id (pk)
- project_id (fk -> ms_project.id, not null)
- code (varchar(64), not null)
- name (varchar(255), not null)
- category (varchar(64), nullable)
- default_units (numeric(8,4), nullable)
- default_standard_rate (numeric(12,2), nullable)
- active (boolean, not null, default true)

Contraintes:
- uq_wf_resource_pool_code (project_id, code)

### wf_charge_line
- id (pk)
- project_id (fk -> ms_project.id, not null)
- task_uid (integer, not null)
- resource_pool_id (fk -> wf_resource_pool.id, nullable)
- load_minutes (integer, not null)
- budget_cost (numeric(14,2), nullable)
- comment (text, nullable)
- source_excel_import_id (fk -> wf_excel_import.id, nullable)
- created_at (timestamptz, not null)

Contraintes:
- fk_wf_charge_line_task (project_id, task_uid) -> ms_task(project_id, uid)
- ck_wf_charge_line_load_non_negative (load_minutes >= 0)

Index:
- idx_wf_charge_line_task (project_id, task_uid)

### wf_allocation_rule
- id (pk)
- project_id (fk -> ms_project.id, not null)
- name (varchar(255), not null)
- strategy (varchar(32), not null)
- payload_json (jsonb, nullable)
- active (boolean, not null, default true)

### wf_allocation_result
- id (pk)
- project_id (fk -> ms_project.id, not null)
- charge_line_id (fk -> wf_charge_line.id, not null)
- assignment_uid (integer, nullable)
- task_uid (integer, not null)
- resource_uid (integer, nullable)
- units (numeric(8,4), nullable)
- work_minutes (integer, not null)
- budget_cost (numeric(14,2), nullable)
- created_at (timestamptz, not null)

### wf_export_batch
- id (pk)
- project_id (fk -> ms_project.id, not null)
- target_save_version (smallint, check in (14,15,16), not null)
- include_resources_assignments (boolean, not null, default true)
- include_extended_attributes (boolean, not null, default true)
- status (varchar(16), check in ('running','success','failed'), not null)
- output_filename (varchar(512), nullable)
- output_sha256 (varchar(64), nullable)
- started_at (timestamptz, not null)
- finished_at (timestamptz, nullable)
- log_json (jsonb, nullable)

## Vues utiles (optionnel)

1. wf_v_task_charge_summary
- Somme des charges budget et charge minutes par task_uid.

2. wf_v_task_allocation_gap
- Compare charge demandee (wf_charge_line) vs affectee (wf_allocation_result).

## Regles de gestion essentielles

1. Import standard
- ms_resource et ms_assignment peuvent rester vides.
- wf_charge_line devient la source metier des charges initiales.

2. Reexport
- Si include_resources_assignments = false:
  - export uniquement Tasks + PredecessorLink (+Calendars +Project)
- Si true:
  - materialiser resources/assignments depuis wf_* vers ms_* avant export XML.

3. Cout budgetise
- Stockage metier dans wf_charge_line.budget_cost.
- Projection export dans ms_assignment.budget_cost (BudgetCost XML).

4. Tracabilite
- Toute operation import/export est journalisee dans wf_import_batch, wf_excel_import, wf_export_batch.

## Ordre de migration recommande

1. Tables ms_project, ms_calendar, ms_task, ms_task_link
2. Tables wf_import_batch, wf_excel_import
3. Tables wf_resource_pool, wf_charge_line
4. Tables ms_resource, ms_assignment
5. Tables wf_allocation_rule, wf_allocation_result, wf_export_batch
6. Tables ms_extended_attribute_def, ms_extended_attribute_value
