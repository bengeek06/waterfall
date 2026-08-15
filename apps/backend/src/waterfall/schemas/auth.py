from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str


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
    current_password: str = Field(min_length=8, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class RefreshTokenRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    refresh_token: str = Field(alias="refreshToken")


class Token(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str
    refresh_token: str = Field(alias="refreshToken")
    token_type: str = "bearer"
    expires_in: int = Field(alias="expiresIn")
