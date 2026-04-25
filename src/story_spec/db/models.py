"""
SQLAlchemy ORM models for the backend.
"""
import uuid
import enum
from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, 
    ForeignKey, Text, Enum, Index, func
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column
from passlib.context import CryptContext

# SQLAlchemy Base
Base = declarative_base()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User(Base):
    """User account model."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    # Relationships
    test_runs: Mapped[List["TestRun"]] = relationship("TestRun", back_populates="user")
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    api_tokens: Mapped[List["APIToken"]] = relationship("APIToken", back_populates="user", cascade="all, delete-orphan")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")

    def verify_password(self, plain_password: str) -> bool:
        """Verify password against the hashed password."""
        return pwd_context.verify(plain_password, self.hashed_password)

    def set_password(self, plain_password: str) -> None:
        """Hash and set the password."""
        self.hashed_password = pwd_context.hash(plain_password)

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, username={self.username})>"


class TestRun(Base):
    """Test run model with relationship to user."""
    __tablename__ = "test_runs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    story: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    
    # Test execution details
    steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # Serialized JSON
    results_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # Serialized JSON
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    overall_status: Mapped[str] = mapped_column(String(50), default="pending", index=True)  # pending, pass, fail
    goal_achieved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="test_runs")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", back_populates="test_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_test_runs_user_created", "user_id", "created_at"),
        Index("idx_test_runs_status", "overall_status"),
    )

    def __repr__(self):
        return f"<TestRun(id={self.id}, user_id={self.user_id}, url={self.url})>"


class RefreshToken(Base):
    """Refresh token model for JWT token renewal."""
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")

    def is_valid(self) -> bool:
        """Check if refresh token is still valid."""
        return not self.revoked and self.expires_at > datetime.utcnow()

    def __repr__(self):
        return f"<RefreshToken(id={self.id}, user_id={self.user_id}, valid={self.is_valid()})>"


class APIToken(Base):
    """API token model for API key authentication."""
    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g., "Production API Key"
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)  # Hash of the token
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)  # None = never expires
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="api_tokens")

    def is_valid(self) -> bool:
        """Check if API token is still valid."""
        if not self.is_active or self.deleted_at is not None:
            return False
        if self.expires_at and self.expires_at <= datetime.utcnow():
            return False
        return True

    def __repr__(self):
        return f"<APIToken(id={self.id}, user_id={self.user_id}, name={self.name})>"


class AuditLogAction(str, enum.Enum):
    """Audit log action types."""
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    TEST_RUN_CREATED = "test_run_created"
    TEST_RUN_UPDATED = "test_run_updated"
    TEST_RUN_DELETED = "test_run_deleted"
    API_TOKEN_CREATED = "api_token_created"
    API_TOKEN_REVOKED = "api_token_revoked"
    PASSWORD_CHANGED = "password_changed"
    EMAIL_VERIFIED = "email_verified"


class AuditLog(Base):
    """Audit log model for tracking all user actions."""
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[AuditLogAction] = mapped_column(Enum(AuditLogAction), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., "user", "test_run", "api_token"
    resource_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    test_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("test_runs.id"), nullable=True, index=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON with additional context
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="audit_logs")
    test_run: Mapped[Optional["TestRun"]] = relationship("TestRun", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_logs_user_action", "user_id", "action"),
        Index("idx_audit_logs_created", "created_at"),
    )

    def __repr__(self):
        return f"<AuditLog(id={self.id}, user_id={self.user_id}, action={self.action})>"
