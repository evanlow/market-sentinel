from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC)


class Snapshot(db.Model):
    """Operational one-row-per-market-date projection used by the dashboard and alerts.

    Research history is stored separately in :class:`ScoreRun`. Keeping this table intact
    makes the history upgrade additive and safe for existing installations.
    """

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

    alerts: Mapped[list[AlertEvent]] = relationship(
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


class ScoreRun(db.Model):
    """Immutable, versioned calculation result for research and audit use."""

    __tablename__ = "score_runs"
    __table_args__ = (
        UniqueConstraint(
            "market_as_of",
            "score_version",
            "revision",
            name="uq_score_run_date_version_revision",
        ),
        UniqueConstraint(
            "market_as_of",
            "score_version",
            "input_hash",
            name="uq_score_run_date_version_input",
        ),
        Index("ix_score_runs_canonical_date", "is_canonical", "market_as_of"),
        Index("ix_score_runs_version_date", "score_version", "market_as_of"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    regime: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    score_change_1d: Mapped[float | None] = mapped_column(Float)
    score_change_3d: Mapped[float | None] = mapped_column(Float)
    score_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ruleset_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code_commit_sha: Mapped[str | None] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    run_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    canonical_key: Mapped[str | None] = mapped_column(String(96), unique=True)
    supersedes_run_id: Mapped[int | None] = mapped_column(ForeignKey("score_runs.id"))
    ruleset: Mapped[dict[str, Any]] = mapped_column(db.JSON, nullable=False)
    indicators: Mapped[list[dict[str, Any]]] = mapped_column(db.JSON, nullable=False)
    triggers: Mapped[list[dict[str, Any]]] = mapped_column(db.JSON, nullable=False)
    source_status: Mapped[dict[str, Any]] = mapped_column(db.JSON, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    supersedes: Mapped[ScoreRun | None] = relationship(
        "ScoreRun", remote_side="ScoreRun.id", foreign_keys=[supersedes_run_id]
    )
    indicator_records: Mapped[list[IndicatorRecord]] = relationship(
        back_populates="score_run",
        cascade="all, delete-orphan",
        order_by="IndicatorRecord.indicator_key",
    )
    source_observations: Mapped[list[SourceObservation]] = relationship(
        back_populates="score_run",
        cascade="all, delete-orphan",
        order_by="SourceObservation.series_key",
    )
    commentary_runs: Mapped[list[CommentaryRun]] = relationship(
        back_populates="score_run",
        cascade="all, delete-orphan",
        order_by="CommentaryRun.generated_at",
    )
    outcomes: Mapped[list[MarketOutcome]] = relationship(
        back_populates="score_run", cascade="all, delete-orphan"
    )

    @property
    def latest_commentary(self) -> CommentaryRun | None:
        return self.commentary_runs[-1] if self.commentary_runs else None

    def to_dict(self, *, include_lineage: bool = False) -> dict[str, Any]:
        commentary = self.latest_commentary
        payload: dict[str, Any] = {
            "id": self.id,
            "market_as_of": self.market_as_of.isoformat(),
            "calculated_at": self.calculated_at.isoformat(),
            "data_cutoff_at": self.data_cutoff_at.isoformat(),
            "score": self.score,
            "regime": self.regime,
            "coverage": self.coverage,
            "score_change_1d": self.score_change_1d,
            "score_change_3d": self.score_change_3d,
            "score_version": self.score_version,
            "ruleset_hash": self.ruleset_hash,
            "input_hash": self.input_hash,
            "code_commit_sha": self.code_commit_sha,
            "revision": self.revision,
            "run_type": self.run_type,
            "is_canonical": self.is_canonical,
            "supersedes_run_id": self.supersedes_run_id,
            "is_demo": self.is_demo,
            "ai_summary": commentary.summary if commentary else None,
        }
        if include_lineage:
            payload.update(
                {
                    "ruleset": self.ruleset,
                    "indicators": [row.to_dict() for row in self.indicator_records],
                    "source_observations": [
                        row.to_dict() for row in self.source_observations
                    ],
                    "triggers": self.triggers,
                    "source_status": self.source_status,
                    "commentary_runs": [row.to_dict() for row in self.commentary_runs],
                    "outcomes": [row.to_dict() for row in self.outcomes],
                }
            )
        return payload


class IndicatorRecord(db.Model):
    __tablename__ = "indicator_records"
    __table_args__ = (
        UniqueConstraint(
            "score_run_id", "indicator_key", name="uq_indicator_record_run_key"
        ),
        Index("ix_indicator_records_key_date", "indicator_key", "observation_as_of"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score_run_id: Mapped[int] = mapped_column(
        ForeignKey("score_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    indicator_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    indicator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    display_value: Mapped[str] = mapped_column(String(80), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    max_points: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(250), nullable=False)
    observation_as_of: Mapped[date | None] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    thresholds: Mapped[dict[str, Any]] = mapped_column(db.JSON, nullable=False)
    staleness_days: Mapped[int | None] = mapped_column(Integer)
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    score_run: Mapped[ScoreRun] = relationship(back_populates="indicator_records")

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator_key": self.indicator_key,
            "indicator_version": self.indicator_version,
            "label": self.label,
            "category": self.category,
            "value": self.value,
            "unit": self.unit,
            "display_value": self.display_value,
            "points": self.points,
            "max_points": self.max_points,
            "status": self.status,
            "source": self.source,
            "observation_as_of": (
                self.observation_as_of.isoformat() if self.observation_as_of else None
            ),
            "description": self.description,
            "detail": self.detail,
            "thresholds": self.thresholds,
            "staleness_days": self.staleness_days,
            "quality_status": self.quality_status,
        }


class SourceObservation(db.Model):
    __tablename__ = "source_observations"
    __table_args__ = (
        UniqueConstraint(
            "score_run_id", "series_key", name="uq_source_observation_run_key"
        ),
        Index(
            "ix_source_observations_series_date", "series_key", "observation_as_of"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score_run_id: Mapped[int] = mapped_column(
        ForeignKey("score_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    series_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(250), nullable=False)
    observation_as_of: Mapped[date | None] = mapped_column(Date, index=True)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", db.JSON, nullable=False
    )

    score_run: Mapped[ScoreRun] = relationship(back_populates="source_observations")

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_key": self.series_key,
            "provider": self.provider,
            "observation_as_of": (
                self.observation_as_of.isoformat() if self.observation_as_of else None
            ),
            "value": self.value,
            "unit": self.unit,
            "retrieved_at": self.retrieved_at.isoformat(),
            "payload_hash": self.payload_hash,
            "quality_status": self.quality_status,
            "metadata": self.metadata_payload,
        }


class CommentaryRun(db.Model):
    __tablename__ = "commentary_runs"
    __table_args__ = (
        UniqueConstraint(
            "score_run_id",
            "provider",
            "model",
            "prompt_version",
            "input_hash",
            name="uq_commentary_run_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score_run_id: Mapped[int] = mapped_column(
        ForeignKey("score_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text)
    structured_response: Mapped[dict[str, Any] | None] = mapped_column(db.JSON)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text)

    score_run: Mapped[ScoreRun] = relationship(back_populates="commentary_runs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "generated_at": self.generated_at.isoformat(),
            "summary": self.summary,
            "structured_response": self.structured_response,
            "input_hash": self.input_hash,
            "status": self.status,
            "error": self.error,
        }


class MarketOutcome(db.Model):
    """Forward outcome attached only after the selected horizon has matured."""

    __tablename__ = "market_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "score_run_id",
            "benchmark",
            "horizon_sessions",
            name="uq_market_outcome_run_benchmark_horizon",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score_run_id: Mapped[int] = mapped_column(
        ForeignKey("score_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    benchmark: Mapped[str] = mapped_column(String(30), nullable=False, default="SPY")
    horizon_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    forward_return_pct: Mapped[float | None] = mapped_column(Float)
    maximum_drawdown_pct: Mapped[float | None] = mapped_column(Float)
    maximum_vix: Mapped[float | None] = mapped_column(Float)
    realized_volatility_pct: Mapped[float | None] = mapped_column(Float)
    correction_occurred: Mapped[bool | None] = mapped_column(Boolean)
    bear_market_occurred: Mapped[bool | None] = mapped_column(Boolean)
    matured_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    data_source: Mapped[str] = mapped_column(String(100), nullable=False)

    score_run: Mapped[ScoreRun] = relationship(back_populates="outcomes")

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark,
            "horizon_sessions": self.horizon_sessions,
            "forward_return_pct": self.forward_return_pct,
            "maximum_drawdown_pct": self.maximum_drawdown_pct,
            "maximum_vix": self.maximum_vix,
            "realized_volatility_pct": self.realized_volatility_pct,
            "correction_occurred": self.correction_occurred,
            "bear_market_occurred": self.bear_market_occurred,
            "matured_at": self.matured_at.isoformat(),
            "computed_at": self.computed_at.isoformat(),
            "data_source": self.data_source,
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
