"""Waterfall business logic services."""

from waterfall.services.calendar_schedule import (
    NoUsableCalendarError,
    ResolvedCalendar,
    compute_finish_at,
    compute_working_minutes_between,
    resolve_calendars_for_tasks,
    resolve_default_calendar_id,
    resolve_task_calendar_ids,
)
from waterfall.services.estimate_calculation import (
    EstimateAggregates,
    MissingRateCoverageError,
    calculate_estimate_aggregates,
    calculate_estimate_lines,
    collect_missing_rate_coverage,
    format_missing_rate_message,
    get_estimate_validation_warnings,
    missing_rate_coverage_detail,
    sync_task_role_assignments_from_estimate,
)
from waterfall.services.estimate_export import build_estimate_workbook
from waterfall.services.estimate_reconciliation_export import (
    build_estimate_reconciliation_workbook,
)
from waterfall.services.estimate_reconciliation_import import (
    CostLineFileRow,
    EstimateReconciliationFormatError,
    LaborFileRow,
    ParsedReconciliationWorkbook,
    TaskFileRow,
    parse_estimate_reconciliation_workbook,
)
from waterfall.services.pagination import PaginationResult, apply_pagination
from waterfall.services.planning_links import (
    PlanningLinkError,
    PlanningLinkInvariantError,
    PlanningLinkNotFoundError,
    replace_task_predecessor_links,
)
from waterfall.services.planning_structure import (
    generate_planning_snapshot,
    generate_planning_structure,
    load_planning_structure_draft,
    save_planning_structure_draft,
)
from waterfall.services.planning_tree import (
    PlanningTaskScheduleError,
    PlanningTreeCascadeConfirmationRequiredError,
    PlanningTreeInvariantError,
    PlanningTreeMoveError,
    PlanningTreeMoveNotFoundError,
    PlanningTreeTaskReferencedError,
    create_planning_task,
    delete_planning_tasks,
    move_planning_tasks,
    restore_planning_snapshot,
    update_planning_task_schedule,
)
from waterfall.services.project_setup import get_project_setup_warnings

__all__ = [
    "NoUsableCalendarError",
    "ResolvedCalendar",
    "compute_finish_at",
    "compute_working_minutes_between",
    "resolve_calendars_for_tasks",
    "resolve_default_calendar_id",
    "resolve_task_calendar_ids",
    "EstimateAggregates",
    "MissingRateCoverageError",
    "calculate_estimate_lines",
    "calculate_estimate_aggregates",
    "collect_missing_rate_coverage",
    "format_missing_rate_message",
    "get_estimate_validation_warnings",
    "missing_rate_coverage_detail",
    "sync_task_role_assignments_from_estimate",
    "build_estimate_workbook",
    "build_estimate_reconciliation_workbook",
    "CostLineFileRow",
    "EstimateReconciliationFormatError",
    "LaborFileRow",
    "ParsedReconciliationWorkbook",
    "TaskFileRow",
    "parse_estimate_reconciliation_workbook",
    "PaginationResult",
    "apply_pagination",
    "generate_planning_snapshot",
    "generate_planning_structure",
    "load_planning_structure_draft",
    "save_planning_structure_draft",
    "PlanningTreeMoveError",
    "PlanningTreeInvariantError",
    "PlanningTreeMoveNotFoundError",
    "PlanningTreeCascadeConfirmationRequiredError",
    "PlanningTreeTaskReferencedError",
    "PlanningTaskScheduleError",
    "move_planning_tasks",
    "create_planning_task",
    "delete_planning_tasks",
    "restore_planning_snapshot",
    "update_planning_task_schedule",
    "PlanningLinkError",
    "PlanningLinkInvariantError",
    "PlanningLinkNotFoundError",
    "replace_task_predecessor_links",
    "get_project_setup_warnings",
]
