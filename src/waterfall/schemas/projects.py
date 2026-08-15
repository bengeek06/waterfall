from datetime import datetime

from pydantic import BaseModel


class ProjectRead(BaseModel):
    id: int
    name: str
    source_version: int
    save_version_out: int
    schedule_from_start: bool
    start_date: datetime | None
    finish_date: datetime | None
    currency_code: str | None


class TaskRead(BaseModel):
    id: int
    project_id: int
    uid: int
    id_display: int | None
    name: str
    outline_number: str | None
    outline_level: int | None
    start_at: datetime | None
    finish_at: datetime | None
    percent_complete: int | None
    is_summary: bool
    is_milestone: bool
