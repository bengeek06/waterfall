from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from waterfall.core.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class UserRead(BaseModel):
    id: int
    email: EmailStr
    is_active: bool


class UserAdminRead(BaseModel):
    id: int
    email: EmailStr
    is_active: bool
    is_admin: bool
    failed_login_attempts: int
    locked_until: datetime | None
    created_at: datetime
    updated_at: datetime


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserRoleUpdate(BaseModel):
    is_admin: bool


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(alias="expiresIn")
