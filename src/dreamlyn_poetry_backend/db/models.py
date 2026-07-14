import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dreamlyn_poetry_backend.db.base import Base


class GenerationStatus(enum.StrEnum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class AudioFormat(enum.StrEnum):
    wav = "wav"
    mp3 = "mp3"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    invite: Mapped["Invite"] = relationship(back_populates="used_by_user", uselist=False)
    refresh_sessions: Mapped[list["RefreshSession"]] = relationship(back_populates="user")
    generations: Mapped[list["Generation"]] = relationship(back_populates="user")


class Invite(TimestampMixin, Base):
    __tablename__ = "invites"

    code: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    api_key: Mapped[str] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True
    )

    used_by_user: Mapped[User | None] = relationship(back_populates="invite")


class RefreshSession(TimestampMixin, Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (UniqueConstraint("token_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    jti: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refresh_sessions.id")
    )

    user: Mapped[User] = relationship(back_populates="refresh_sessions")


class Generation(TimestampMixin, Base):
    __tablename__ = "generations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[float] = mapped_column(Float)
    audio_format: Mapped[AudioFormat] = mapped_column(Enum(AudioFormat, name="audio_format"))
    seed: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[GenerationStatus] = mapped_column(
        Enum(GenerationStatus, name="generation_status"), default=GenerationStatus.pending
    )
    upstream_model: Mapped[str] = mapped_column(String(200))
    storage_url: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped[User] = relationship(back_populates="generations")
