"""
SQLAlchemy ORM models for the Renovation Chatbot.

This module defines the complete database schema:
- User         — anyone who interacts with the bot (client, tradesperson, expert)
- Project      — a renovation project ("passport")
- ProjectRole  — links a user to a project with a specific role
- Stage        — a major work phase (e.g. Demolition, Electrical)
- SubStage     — a task within a stage (e.g. "Remove bathroom tiles")
- BudgetItem   — budget tracking per category
- ChangeLog    — immutable audit trail for all budget/stage changes
- Message      — every incoming message (text/voice/image), stored as text for RAG
- Embedding    — vector embeddings for semantic search
"""

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ── Base ──────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


# ── Enums ─────────────────────────────────────────────────────


class RenovationType(str, enum.Enum):
    COSMETIC = "cosmetic"
    STANDARD = "standard"
    MAJOR = "major"
    DESIGNER = "designer"


class RoleType(str, enum.Enum):
    OWNER = "owner"
    CO_OWNER = "co_owner"
    FOREMAN = "foreman"
    TRADESPERSON = "tradesperson"
    DESIGNER = "designer"
    SUPPLIER = "supplier"
    EXPERT = "expert"
    VIEWER = "viewer"


class StageStatus(str, enum.Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELAYED = "delayed"


class PaymentStatus(str, enum.Enum):
    RECORDED = "recorded"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    PAID = "paid"
    CLOSED = "closed"


class MessageType(str, enum.Enum):
    """Type of incoming user message."""
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"


# ── Models ────────────────────────────────────────────────────


class User(Base):
    """A person who interacts with the bot (across any platform)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    whatsapp_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    is_bot_started: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project_roles: Mapped[list["ProjectRole"]] = relationship(back_populates="user")


class Project(Base):
    """A renovation project — the central entity ("passport")."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    area_sqm: Mapped[float | None] = mapped_column(Numeric(8, 2))
    renovation_type: Mapped[RenovationType] = mapped_column(
        Enum(RenovationType, name="renovation_type")
    )
    total_budget: Mapped[float | None] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Telegram group chat ID for this project (optional)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)

    # Relationships
    roles: Mapped[list["ProjectRole"]] = relationship(back_populates="project")
    stages: Mapped[list["Stage"]] = relationship(back_populates="project", order_by="Stage.order")
    budget_items: Mapped[list["BudgetItem"]] = relationship(back_populates="project")
    change_logs: Mapped[list["ChangeLog"]] = relationship(back_populates="project")


class ProjectRole(Base):
    """Links a user to a project with a specific role."""

    __tablename__ = "project_roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[RoleType] = mapped_column(Enum(RoleType, name="role_type"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="roles")
    user: Mapped["User"] = relationship(back_populates="project_roles")


class Stage(Base):
    """A major work phase in a renovation project."""

    __tablename__ = "stages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    order: Mapped[int] = mapped_column(default=0)
    status: Mapped[StageStatus] = mapped_column(
        Enum(StageStatus, name="stage_status"), default=StageStatus.PLANNED
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.RECORDED
    )
    budget: Mapped[float | None] = mapped_column(Numeric(12, 2))
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_parallel: Mapped[bool] = mapped_column(Boolean, default=False)
    is_checkpoint: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="stages")
    responsible_user: Mapped["User | None"] = relationship()
    sub_stages: Mapped[list["SubStage"]] = relationship(
        back_populates="stage", order_by="SubStage.order"
    )


class SubStage(Base):
    """A task within a stage (e.g. 'Remove bathroom tiles' under 'Demolition')."""

    __tablename__ = "sub_stages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    order: Mapped[int] = mapped_column(default=0)
    status: Mapped[StageStatus] = mapped_column(
        Enum(StageStatus, name="stage_status", create_type=False), default=StageStatus.PLANNED
    )
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    stage: Mapped["Stage"] = relationship(back_populates="sub_stages")
    responsible_user: Mapped["User | None"] = relationship()


class BudgetItem(Base):
    """Budget tracking per category within a project."""

    __tablename__ = "budget_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(100))  # e.g. "electrical", "plumbing"
    work_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    material_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    prepayment: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="budget_items")


class ChangeLog(Base):
    """Immutable audit trail for budget and stage changes."""

    __tablename__ = "change_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(String(50))   # "stage", "budget_item", etc.
    entity_id: Mapped[int] = mapped_column(BigInteger)
    field_name: Mapped[str] = mapped_column(String(100))    # e.g. "budget", "status"
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="change_logs")
    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])
    confirmed_by: Mapped["User | None"] = relationship(foreign_keys=[confirmed_by_user_id])


class Message(Base):
    """
    Every incoming message — text, voice, or image — stored as text for RAG.

    In Phase 1–3, only text messages are fully processed. Voice and image
    messages are acknowledged and stored with message_type set, but their
    transcribed_text is populated later (Phase 8+) when STT / Vision
    services are integrated.

    The transcribed_text field is the canonical text used for:
    - Semantic search (pgvector embeddings)
    - Budget extraction and reporting
    - RAG context for AI responses
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    platform: Mapped[str] = mapped_column(String(20))  # "telegram", "whatsapp"
    platform_chat_id: Mapped[str] = mapped_column(String(100))  # chat identifier on the platform
    platform_message_id: Mapped[str | None] = mapped_column(String(100))  # message ID on the platform
    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, name="message_type"), default=MessageType.TEXT
    )
    # Original text content (for text messages) or caption (for images)
    raw_text: Mapped[str | None] = mapped_column(Text)
    # Platform file reference (file_id for Telegram, URL for WhatsApp)
    file_ref: Mapped[str | None] = mapped_column(Text)
    # Text produced by STT (voice) or Vision AI (image); same as raw_text for text messages
    transcribed_text: Mapped[str | None] = mapped_column(Text)
    is_from_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project: Mapped["Project | None"] = relationship()
    user: Mapped["User | None"] = relationship()


class Embedding(Base):
    """Vector embeddings for semantic search (chat messages, documents)."""

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(1536))  # text-embedding-3-small outputs 1536 dims
    metadata_: Mapped[str | None] = mapped_column("metadata", Text)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
