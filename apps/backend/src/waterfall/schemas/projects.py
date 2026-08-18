from datetime import datetime

from pydantic import BaseModel, Field


class ProjectRead(BaseModel):
    id: int
    name: str
    source_version: int
    save_version_out: int
    schedule_from_start: bool
    start_date: datetime | None
    finish_date: datetime | None
    currency_code: str | None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


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
    description: str | None


class TaskDescriptionUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=10000)
