from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pending_totp_secret: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    recovery_codes: Mapped[List["RecoveryCode"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    def __repr__(self) -> str:
        return f"<RefreshToken user_id={self.user_id} revoked={self.revoked}>"


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(128))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="recovery_codes")

    def __repr__(self) -> str:
        return f"<RecoveryCode user_id={self.user_id} used={self.used}>"


class WorkItem(Base):
    """A unit of in-progress work (uploaded file, analysis, NUBAN, intel sync).

    The full state object is stored as a JSON blob in ``data``; a few fields are
    duplicated into indexed columns for filtering by user and for cleanup. This
    replaces the old per-process dicts so that every worker sees the same state.
    """

    __tablename__ = "work_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    uploaded_at: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    status: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    data: Mapped[str] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<WorkItem {self.kind}:{self.id} user={self.user_id}>"


class Task(Base):
    """Background processing-task status, shared across workers."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, default=0.0, index=True)

    def __repr__(self) -> str:
        return f"<Task {self.id} status={self.status}>"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} user={self.user_email}>"


class Space(Base):
    """A coworking space: an owner shares files with members for live viewing
    and collaborative processing."""

    __tablename__ = "spaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    share_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    members: Mapped[List["SpaceMember"]] = relationship(
        back_populates="space", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Space {self.name} owner={self.owner_id}>"


class SpaceMember(Base):
    """An existing user granted access to a coworking space."""

    __tablename__ = "space_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    space: Mapped["Space"] = relationship(back_populates="members")

    def __repr__(self) -> str:
        return f"<SpaceMember space={self.space_id} user={self.user_id}>"
