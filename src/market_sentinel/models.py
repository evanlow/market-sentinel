from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Snapshot(db.Model):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_as_of: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    regime: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    score_change_1d: Mapped[float | None] = mapped_column(Float)
    score_change_3d: Mapped[float | None] = mapped_column(Float)
    indicators: Mapped[list[dict[str, Any]]] = mapped_column(db.JSON, nullable=False)
    triggers: Mapped[list[dict[str, Any]]] = mapped_column(db.JSON, nullable=False)
    source_status: Mapped[dict[str, Any]] = mapped_column(db.JSON, nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    alerts: Mapped[list["AlertEvent"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "market_as_of": self.market_as_of.isoformat(),
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "score": self.score,
            "regime": self.regime,
            "coverage": self.coverage,
            "score_change_1d": self.score_change_1d,
            "score_change_3d": self.score_change_3d,
            "indicators": self.indicators,
            "triggers": self.triggers,
            "source_status": self.source_status,
            "ai_summary": self.ai_summary,
            "is_demo": self.is_demo,
        }


class ManualMetric(db.Model):
    __tablename__ = "manual_metrics"
    __table_args__ = (UniqueConstraint("key", "as_of", name="uq_manual_metric_key_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AlertEvent(db.Model):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(250), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(db.JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    recipients: Mapped[list[str]] = mapped_column(db.JSON, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(250))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    snapshot: Mapped[Snapshot] = relationship(back_populates="alerts")
