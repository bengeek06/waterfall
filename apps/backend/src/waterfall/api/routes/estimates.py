from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user
from waterfall.api.pagination import ListParams, list_params
from waterfall.api.routes.planning_support import (
    order_snapshots_depth_first,
)
from waterfall.api.routes.project_access import (
    get_mutable_project_lock,
    get_planning_or_404,
    get_project_or_404,
)
from waterfall.api.routes.project_cost_codes import resolve_cost_code_id
from waterfall.api.routes.projects import (
    get_draft_estimate_or_409,
    get_estimate_or_404,
    get_non_labor_category_or_400,
    to_estimate_cost_line_read,
    to_estimate_task_row_read,
    to_project_estimate_read,
    to_project_read,
)
from waterfall.db.session import get_db
from waterfall.models.ms_core import MsTask
from waterfall.models.planning import WfPlanningTaskSnapshot
from waterfall.models.resources import Estimate, EstimateCostLine, EstimateTaskRow
from waterfall.models.user import User
from waterfall.schemas.projects import (
    EstimateAggregatesRead,
    EstimateCostLineCreate,
    EstimateCostLineListRead,
    EstimateCostLineRead,
    EstimateCostLineUpdate,
    EstimateTaskRowListRead,
    EstimateValidationRead,
    ProjectEstimateCreate,
    ProjectEstimateListRead,
    ProjectEstimateRead,
    ProjectRead,
)
from waterfall.schemas.resources import CostTypeKind
from waterfall.services import (
    apply_pagination,
    build_estimate_workbook,
    calculate_estimate_aggregates,
    calculate_estimate_lines,
    get_estimate_validation_warnings,
)
from waterfall.services.project_lifecycle import ensure_project_mutable

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}/estimates", response_model=ProjectEstimateListRead)
def list_project_estimates(
    project_id: int,
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectEstimateListRead:
    get_project_or_404(db, project_id, current_user.id)
    query = db.query(Estimate).filter(Estimate.project_id == project_id)
    result = apply_pagination(
        query,
        params,
        sortable={
            "version_number": Estimate.version_number,
            "kind": Estimate.kind,
            "status": Estimate.status,
            "created_at": Estimate.created_at,
        },
        searchable=[Estimate.note],
        default_sort=Estimate.version_number,
        tiebreaker=Estimate.id,
    )
    return ProjectEstimateListRead(
        items=[to_project_estimate_read(estimate) for estimate in result.rows],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "/{project_id}/estimates",
    response_model=ProjectEstimateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_estimate(
    project_id: int,
    payload: ProjectEstimateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectEstimateRead:
    project = get_mutable_project_lock(db, project_id, current_user.id)
    if payload.kind == "forecast_remaining" and payload.reference_estimate_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forecast remaining estimate requires a reference estimate",
        )
    if payload.reference_estimate_id is not None:
        get_estimate_or_404(db, project_id, payload.reference_estimate_id)

    current_version = (
        db.query(func.max(Estimate.version_number))
        .filter(Estimate.project_id == project_id)
        .scalar()
    )
    estimate = Estimate(
        project_id=project_id,
        planning_id=project.displayed_planning_id,
        reference_estimate_id=payload.reference_estimate_id,
        version_number=(current_version or 0) + 1,
        kind=payload.kind,
        status="draft",
        currency_code=payload.currency_code.upper(),
        note=payload.note,
    )
    db.add(estimate)
    db.flush()

    source_planning = (
        get_planning_or_404(db, project_id, project.displayed_planning_id)
        if project.displayed_planning_id is not None
        else None
    )
    snapshots = (
        order_snapshots_depth_first(
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == source_planning.id)
            .all()
        )
        if source_planning is not None
        else []
    )
    legacy_tasks = db.query(MsTask).filter(MsTask.project_id == project_id).all()
    task_by_uid = {task.uid: task for task in legacy_tasks}
    tasks = snapshots or legacy_tasks
    task_id_by_uid = {
        task.uid: task_by_uid[task.uid].id for task in snapshots if task.uid in task_by_uid
    }
    rows: list[EstimateTaskRow] = []
    for position, task in enumerate(tasks, start=1):
        parent_id = (
            task_id_by_uid.get(task.parent_uid)
            if source_planning is not None and task.parent_uid is not None
            else None
        )
        task_id = (
            task_by_uid[task.uid].id
            if source_planning is not None and task.uid in task_by_uid
            else None
            if source_planning is not None
            else task.id
        )
        rows.append(
            EstimateTaskRow(
                estimate_id=estimate.id,
                task_id=task_id,
                parent_task_id=parent_id,
                position=position,
                task_name=task.name,
                outline_number=task.outline_number,
                outline_level=task.outline_level,
                is_milestone=task.is_milestone,
            )
        )
    db.add_all(rows)
    db.commit()
    db.refresh(estimate)
    return to_project_estimate_read(estimate)


@router.get("/{project_id}/estimates/{estimate_id}", response_model=ProjectEstimateRead)
def get_project_estimate(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectEstimateRead:
    get_project_or_404(db, project_id, current_user.id)
    return to_project_estimate_read(get_estimate_or_404(db, project_id, estimate_id))


@router.post(
    "/{project_id}/estimates/{estimate_id}/validate", response_model=EstimateValidationRead
)
def validate_project_estimate(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateValidationRead:
    get_mutable_project_lock(db, project_id, current_user.id)
    estimate = get_estimate_or_404(db, project_id, estimate_id)
    if estimate.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Estimate is not a draft")
    try:
        estimate_lines = calculate_estimate_lines(db, estimate_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # Issue #65 (E6-04): computed from the same in-progress transaction, before commit,
    # so it reflects the estimate/cost-lines state actually being validated -- never a
    # state read back after some later, unrelated write.
    warnings = get_estimate_validation_warnings(db, project_id, estimate_id)
    db.add_all(estimate_lines)
    db.flush()
    estimate.status = "validated"
    estimate.validated_at = datetime.now(UTC)
    db.add(estimate)
    db.commit()
    db.refresh(estimate)
    return EstimateValidationRead(
        **to_project_estimate_read(estimate).model_dump(),
        warnings=warnings,
    )


@router.post("/{project_id}/estimates/{estimate_id}/reference", response_model=ProjectRead)
def set_estimate_reference(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    project = get_project_or_404(db, project_id, current_user.id)
    ensure_project_mutable(project)
    estimate = get_estimate_or_404(db, project_id, estimate_id)
    if estimate.status != "validated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Estimate must be validated",
        )
    project.reference_estimate_id = estimate.id
    db.commit()
    db.refresh(project)
    return to_project_read(project)


@router.get(
    "/{project_id}/estimates/{estimate_id}/task-rows",
    response_model=EstimateTaskRowListRead,
)
def list_estimate_task_rows(
    project_id: int,
    estimate_id: int,
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateTaskRowListRead:
    get_project_or_404(db, project_id, current_user.id)
    get_estimate_or_404(db, project_id, estimate_id)
    query = db.query(EstimateTaskRow).filter(EstimateTaskRow.estimate_id == estimate_id)
    result = apply_pagination(
        query,
        params,
        sortable={
            "position": EstimateTaskRow.position,
            "task_name": EstimateTaskRow.task_name,
            "outline_number": EstimateTaskRow.outline_number,
            "outline_level": EstimateTaskRow.outline_level,
        },
        default_sort=EstimateTaskRow.position,
        tiebreaker=EstimateTaskRow.id,
        searchable=[EstimateTaskRow.task_name],
    )
    return EstimateTaskRowListRead(
        items=[to_estimate_task_row_read(row) for row in result.rows],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get(
    "/{project_id}/estimates/{estimate_id}/aggregates",
    response_model=EstimateAggregatesRead,
)
def get_estimate_aggregates(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateAggregatesRead:
    get_project_or_404(db, project_id, current_user.id)
    get_estimate_or_404(db, project_id, estimate_id)
    return EstimateAggregatesRead(**calculate_estimate_aggregates(db, estimate_id))


@router.get("/{project_id}/estimates/{estimate_id}/export.xlsx")
def export_estimate_excel(
    project_id: int,
    estimate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    project = get_project_or_404(db, project_id, current_user.id)
    estimate = get_estimate_or_404(db, project_id, estimate_id)
    workbook_bytes = build_estimate_workbook(db, project, estimate)
    filename = f"devis-{project.name}-v{estimate.version_number}.xlsx".replace(" ", "-")
    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{project_id}/estimates/{estimate_id}/cost-lines",
    response_model=EstimateCostLineListRead,
)
def list_estimate_cost_lines(
    project_id: int,
    estimate_id: int,
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateCostLineListRead:
    get_project_or_404(db, project_id, current_user.id)
    get_estimate_or_404(db, project_id, estimate_id)
    query = db.query(EstimateCostLine).filter(EstimateCostLine.estimate_id == estimate_id)
    result = apply_pagination(
        query,
        params,
        sortable={
            "label": EstimateCostLine.label,
            "quantity": EstimateCostLine.quantity,
            "unit_cost": EstimateCostLine.unit_cost,
            "purchase_cost": EstimateCostLine.purchase_cost,
            "created_at": EstimateCostLine.created_at,
        },
        tiebreaker=EstimateCostLine.id,
        searchable=[EstimateCostLine.label],
    )
    return EstimateCostLineListRead(
        items=[to_estimate_cost_line_read(line) for line in result.rows],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "/{project_id}/estimates/{estimate_id}/cost-lines",
    response_model=EstimateCostLineRead,
    status_code=status.HTTP_201_CREATED,
)
def create_estimate_cost_line(
    project_id: int,
    estimate_id: int,
    payload: EstimateCostLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateCostLineRead:
    get_mutable_project_lock(db, project_id, current_user.id)
    get_draft_estimate_or_409(db, project_id, estimate_id)
    if payload.task_id is not None:
        task = db.query(MsTask).filter(MsTask.id == payload.task_id).first()
        if task is None or task.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task does not belong to project",
            )
    category, cost_type = get_non_labor_category_or_400(db, payload.cost_category_id)
    cost_code_id = resolve_cost_code_id(db, project_id, payload.cost_code_id)
    supply_status = "planned" if cost_type.kind == CostTypeKind.SUPPLY else None
    if payload.supply_status is not None:
        if cost_type.kind != CostTypeKind.SUPPLY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Supply status is only valid for supplies",
            )
        supply_status = payload.supply_status

    line = EstimateCostLine(
        estimate_id=estimate_id,
        task_id=payload.task_id,
        cost_type_id=cost_type.id,
        cost_category_id=category.id,
        cost_code_id=cost_code_id,
        cost_type_code=cost_type.code,
        accounting_code=category.accounting_code,
        category_code=category.category_code,
        label=payload.label,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        purchase_cost=payload.quantity * payload.unit_cost,
        supply_status=supply_status,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return to_estimate_cost_line_read(line)


@router.patch(
    "/{project_id}/estimates/{estimate_id}/cost-lines/{line_id}",
    response_model=EstimateCostLineRead,
)
def update_estimate_cost_line(
    project_id: int,
    estimate_id: int,
    line_id: int,
    payload: EstimateCostLineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EstimateCostLineRead:
    get_mutable_project_lock(db, project_id, current_user.id)
    get_draft_estimate_or_409(db, project_id, estimate_id)
    line = (
        db.query(EstimateCostLine)
        .filter(EstimateCostLine.id == line_id)
        .filter(EstimateCostLine.estimate_id == estimate_id)
        .first()
    )
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estimate cost line not found",
        )

    values = payload.model_dump(exclude_unset=True)
    if "task_id" in values and values["task_id"] is not None:
        task = db.query(MsTask).filter(MsTask.id == values["task_id"]).first()
        if task is None or task.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task does not belong to project",
            )
    if "cost_code_id" in values:
        # An explicit null resolves back to the project's root, exactly like an omitted
        # field does at create time -- never silently detaches the line from imputation
        # (the `.get(...) is not None` form used to let `{"cost_code_id": null}` bypass
        # both validation and the "always attached" invariant).
        values["cost_code_id"] = resolve_cost_code_id(db, project_id, values["cost_code_id"])

    category, cost_type = get_non_labor_category_or_400(
        db,
        values.get("cost_category_id", line.cost_category_id),
    )
    supply_status = values.get("supply_status", line.supply_status)
    if cost_type.kind == CostTypeKind.SUPPLY:
        supply_status = supply_status or "planned"
    else:
        if values.get("supply_status") is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Supply status is only valid for supplies",
            )
        supply_status = None

    for field, value in values.items():
        setattr(line, field, value)
    line.cost_type_id = cost_type.id
    line.cost_category_id = category.id
    line.cost_type_code = cost_type.code
    line.accounting_code = category.accounting_code
    line.category_code = category.category_code
    line.supply_status = supply_status
    line.purchase_cost = line.quantity * line.unit_cost
    db.add(line)
    db.commit()
    db.refresh(line)
    return to_estimate_cost_line_read(line)


@router.delete(
    "/{project_id}/estimates/{estimate_id}/cost-lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_estimate_cost_line(
    project_id: int,
    estimate_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    get_project_or_404(db, project_id, current_user.id)
    get_draft_estimate_or_409(db, project_id, estimate_id)
    line = (
        db.query(EstimateCostLine)
        .filter(EstimateCostLine.id == line_id)
        .filter(EstimateCostLine.estimate_id == estimate_id)
        .first()
    )
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estimate cost line not found",
        )
    db.delete(line)
    db.commit()
