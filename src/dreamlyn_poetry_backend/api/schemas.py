import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from dreamlyn_poetry_backend.db.models import AudioFormat, GenerationStatus


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | list[Any] | None = None
    request_id: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str
    is_blocked: bool
    created_at: datetime


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    invite_code: uuid.UUID

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_name must not be blank")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class AuthResponse(TokenResponse):
    user: UserResponse


class GenerationCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    duration_seconds: float
    audio_format: AudioFormat = AudioFormat.wav
    seed: int | None = None

    @field_validator("prompt")
    @classmethod
    def strip_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("prompt must not be blank")
        return value


class GenerationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    prompt: str
    duration_seconds: float
    audio_format: AudioFormat
    seed: int | None
    status: GenerationStatus
    upstream_model: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    audio_url: str | None = None


class GenerationPage(BaseModel):
    items: list[GenerationResponse]
    total: int
    limit: int
    offset: int


class InviteCreateRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)


class InviteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: uuid.UUID
    is_revoked: bool
    is_used: bool
    used_by_user_id: uuid.UUID | None
    created_at: datetime
    revoked_at: datetime | None
    used_at: datetime | None


class InvitePage(BaseModel):
    items: list[InviteResponse]
    total: int
    limit: int
    offset: int


class UserPage(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class UserBlockRequest(BaseModel):
    is_blocked: bool


class HealthResponse(BaseModel):
    status: Literal["alive", "ready", "not_ready"]
    detail: str | None = None
