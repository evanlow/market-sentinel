from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from flask import current_app
from sqlalchemy import desc, func

from ..extensions import db
from ..models import (
    CommentaryRun,
    IndicatorRecord,
    ScoreRun,
    Snapshot,
    SourceObservation,
)
from .risk import RiskEngine
from .types import Metric, RiskAssessment

VALID_RUN_TYPES = frozenset({"live", "revision", "backfill", "simulation", "legacy"})


@dataclass(slots=True)
class ArchiveResult:
    run: ScoreRun
    created: bool


class ResearchHistoryService:
    """Persist immutable score runs and normalized calculation lineage."""

    def __init__(self, risk_engine: RiskEngine | None = None) -> None:
        self.risk_engine = risk_engine or RiskEngine()

    def archive_assessment(
        self,
        *,
        assessment: RiskAssessment,
        metrics: dict[str, Metric],
        source_status: dict[str, Any],
        score_change_1d: float | None,
        score_change_3d: float | None,
        run_type: str = "live",
        calculated_at: datetime | None = None,
        is_demo: bool = False,
    ) -> ArchiveResult:
        self._validate_run_type(run_type)
        calculated_at = self._as_utc(calculated_at or datetime.now(UTC))
        score_version = self.risk_engine.SCORE_VERSION
        ruleset = self.risk_engine.ruleset_payload()
        ruleset_hash = self.risk_engine.ruleset_hash()
        input_hash = self._assessment_input_hash(
            assessment=assessment,
            metrics=metrics,
            source_status=source_status,
            ruleset_hash=ruleset_hash,
            is_demo=is_demo,
        )

        existing = ScoreRun.query.filter_by(
            market_as_of=assessment.market_as_of,
            score_version=score_version,
            is_demo=is_demo,
            input_hash=input_hash,
        ).one_or_none()
        if existing is not None:
            self._select_canonical(existing)
            return ArchiveResult(run=existing, created=False)

        previous = self._canonical_for_date(
            assessment.market_as_of,
            score_version,
            is_demo,
        )
        revision = self._next_revision(
            assessment.market_as_of,
            score_version,
            is_demo,
        )
        effective_run_type = "revision" if previous is not None and run_type == "live" else run_type
        self._clear_canonical(previous)

        run = ScoreRun(
            market_as_of=assessment.market_as_of,
            calculated_at=calculated_at,
            data_cutoff_at=self._end_of_day_utc(assessment.market_as_of),
            score=assessment.score,
            regime=assessment.regime,
            coverage=assessment.coverage,
            score_change_1d=score_change_1d,
            score_change_3d=score_change_3d,
            score_version=score_version,
            ruleset_hash=ruleset_hash,
            input_hash=input_hash,
            code_commit_sha=current_app.config.get("APP_GIT_SHA") or None,
            revision=revision,
            run_type=effective_run_type,
            is_canonical=True,
            canonical_key=self._canonical_key(
                assessment.market_as_of,
                score_version,
                is_demo,
            ),
            supersedes_run_id=previous.id if previous else None,
            ruleset=ruleset,
            indicators=[item.to_dict() for item in assessment.indicators],
            triggers=assessment.triggers,
            source_status=self._normalise(source_status),
            is_demo=is_demo,
        )
        db.session.add(run)
        db.session.flush()
        self._persist_assessment_lineage(
            run=run,
            assessment=assessment,
            metrics=metrics,
            retrieved_at=calculated_at,
        )
        return ArchiveResult(run=run, created=True)

    def migrate_snapshot(
        self,
        snapshot: Snapshot,
        *,
        run_type: str = "legacy",
    ) -> ArchiveResult:
        """Copy a legacy operational snapshot into the append-only research schema."""

        self._validate_run_type(run_type)
        score_version = self.risk_engine.SCORE_VERSION
        ruleset = self.risk_engine.ruleset_payload()
        ruleset_hash = self.risk_engine.ruleset_hash()

        # Migration is a one-time bootstrap. Never let a lossy Snapshot projection
        # supersede an existing run in the same live/demo research partition.
        existing_for_date = (
            ScoreRun.query.filter_by(
                market_as_of=snapshot.market_as_of,
                score_version=score_version,
                is_demo=snapshot.is_demo,
            )
            .order_by(desc(ScoreRun.is_canonical), desc(ScoreRun.revision))
            .first()
        )
        if existing_for_date is not None:
            return ArchiveResult(run=existing_for_date, created=False)

        input_hash = self._hash_payload(
            {
                "legacy_snapshot_id": snapshot.id,
                "market_as_of": snapshot.market_as_of,
                "score": snapshot.score,
                "regime": snapshot.regime,
                "coverage": snapshot.coverage,
                "score_change_1d": snapshot.score_change_1d,
                "score_change_3d": snapshot.score_change_3d,
                "indicators": snapshot.indicators,
                "triggers": snapshot.triggers,
                "source_status": snapshot.source_status,
                "is_demo": snapshot.is_demo,
                "ruleset_hash": ruleset_hash,
            }
        )
        calculated_at = self._as_utc(
            snapshot.captured_at or snapshot.updated_at or datetime.now(UTC)
        )
        run = ScoreRun(
            market_as_of=snapshot.market_as_of,
            calculated_at=calculated_at,
            data_cutoff_at=self._end_of_day_utc(snapshot.market_as_of),
            score=snapshot.score,
            regime=snapshot.regime,
            coverage=snapshot.coverage,
            score_change_1d=snapshot.score_change_1d,
            score_change_3d=snapshot.score_change_3d,
            score_version=score_version,
            ruleset_hash=ruleset_hash,
            input_hash=input_hash,
            code_commit_sha=current_app.config.get("APP_GIT_SHA") or None,
            revision=1,
            run_type=run_type,
            is_canonical=True,
            canonical_key=self._canonical_key(
                snapshot.market_as_of,
                score_version,
                snapshot.is_demo,
            ),
            supersedes_run_id=None,
            ruleset=ruleset,
            indicators=self._normalise(snapshot.indicators),
            triggers=self._normalise(snapshot.triggers),
            source_status=self._normalise(snapshot.source_status),
            is_demo=snapshot.is_demo,
        )
        db.session.add(run)
        db.session.flush()
        self._persist_legacy_lineage(run, snapshot.indicators, calculated_at)
        if snapshot.ai_summary:
            self.record_commentary(
                run,
                summary=snapshot.ai_summary,
                provider="legacy",
                model="snapshot-cache",
                prompt_version="legacy",
            )
        return ArchiveResult(run=run, created=True)

    def migrate_all_snapshots(self) -> tuple[int, int]:
        created = 0
        reused = 0
        snapshots = Snapshot.query.order_by(Snapshot.market_as_of).all()
        for snapshot in snapshots:
            result = self.migrate_snapshot(snapshot)
            if result.created:
                created += 1
            else:
                reused += 1
        return created, reused

    def record_commentary(
        self,
        run: ScoreRun,
        *,
        summary: str | None,
        provider: str,
        model: str,
        prompt_version: str,
        status: str = "generated",
        error: str | None = None,
        structured_response: dict[str, Any] | None = None,
    ) -> CommentaryRun:
        if run.id is None:
            db.session.flush()
        input_hash = self._hash_payload(
            {
                "score_run_input_hash": run.input_hash,
                "provider": provider,
                "model": model,
                "prompt_version": prompt_version,
                "summary": summary,
                "structured_response": structured_response,
                "status": status,
                "error": error,
            }
        )
        existing = CommentaryRun.query.filter_by(
            score_run_id=run.id,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            input_hash=input_hash,
        ).one_or_none()
        if existing is not None:
            return existing

        commentary = CommentaryRun(
            score_run=run,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            summary=summary,
            structured_response=self._normalise(structured_response),
            input_hash=input_hash,
            status=status,
            error=error,
        )
        db.session.add(commentary)
        db.session.flush()
        return commentary

    @staticmethod
    def find_commentary(
        run: ScoreRun,
        *,
        provider: str,
        model: str,
        prompt_version: str,
    ) -> CommentaryRun | None:
        return (
            CommentaryRun.query.filter_by(
                score_run_id=run.id,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                status="generated",
            )
            .order_by(desc(CommentaryRun.generated_at))
            .first()
        )

    def _persist_assessment_lineage(
        self,
        *,
        run: ScoreRun,
        assessment: RiskAssessment,
        metrics: dict[str, Metric],
        retrieved_at: datetime,
    ) -> None:
        results = {item.key: item for item in assessment.indicators}
        for key in sorted(metrics):
            metric = metrics[key]
            result = results[key]
            observation_date = metric.as_of
            staleness_days = (
                (assessment.market_as_of - observation_date).days if observation_date else None
            )
            quality_status = self._quality_status(metric.value, staleness_days)
            source_payload = {
                "series_key": key,
                "provider": metric.source,
                "observation_as_of": observation_date,
                "value": self._float_or_none(metric.value),
                "unit": metric.unit,
                "label": metric.label,
                "category": metric.category,
                "detail": metric.detail,
            }
            run.source_observations.append(
                SourceObservation(
                    series_key=key,
                    provider=metric.source,
                    observation_as_of=observation_date,
                    value=self._float_or_none(metric.value),
                    unit=metric.unit,
                    retrieved_at=retrieved_at,
                    payload_hash=self._hash_payload(source_payload),
                    quality_status=quality_status,
                    metadata_payload={
                        "label": metric.label,
                        "category": metric.category,
                        "description": metric.description,
                        "detail": metric.detail,
                    },
                )
            )
            rule = self.risk_engine.rule_for_key(key)
            run.indicator_records.append(
                IndicatorRecord(
                    indicator_key=result.key,
                    indicator_version=self.risk_engine.INDICATOR_VERSION,
                    label=result.label,
                    category=result.category,
                    value=self._float_or_none(result.value),
                    unit=result.unit,
                    display_value=result.display_value,
                    points=result.points,
                    max_points=result.max_points,
                    status=result.status,
                    source=result.source,
                    observation_as_of=observation_date,
                    description=result.description,
                    detail=result.detail,
                    thresholds=rule.to_dict() if rule else {},
                    staleness_days=staleness_days,
                    quality_status=quality_status,
                )
            )

    def _persist_legacy_lineage(
        self,
        run: ScoreRun,
        indicators: list[dict[str, Any]],
        retrieved_at: datetime,
    ) -> None:
        for item in indicators:
            key = str(item.get("key") or "unknown")
            observation_date = self._parse_date(item.get("as_of"))
            value = self._float_or_none(item.get("value"))
            staleness_days = (
                (run.market_as_of - observation_date).days if observation_date else None
            )
            quality_status = self._quality_status(value, staleness_days)
            provider = str(item.get("source") or "legacy")
            unit = str(item.get("unit") or "")
            display_value = item.get("display_value")
            if display_value is None:
                display_value = "Not available" if value is None else str(value)
            source_payload = {
                "series_key": key,
                "provider": provider,
                "observation_as_of": observation_date,
                "value": value,
                "unit": unit,
                "legacy": True,
            }
            run.source_observations.append(
                SourceObservation(
                    series_key=key,
                    provider=provider,
                    observation_as_of=observation_date,
                    value=value,
                    unit=unit,
                    retrieved_at=retrieved_at,
                    payload_hash=self._hash_payload(source_payload),
                    quality_status=quality_status,
                    metadata_payload={"legacy": True},
                )
            )
            rule = self.risk_engine.rule_for_key(key)
            run.indicator_records.append(
                IndicatorRecord(
                    indicator_key=key,
                    indicator_version="legacy",
                    label=str(item.get("label") or key),
                    category=str(item.get("category") or "legacy"),
                    value=value,
                    unit=unit,
                    display_value=str(display_value),
                    points=int(item.get("points") or 0),
                    max_points=int(item.get("max_points") or 0),
                    status=str(item.get("status") or "unknown"),
                    source=provider,
                    observation_as_of=observation_date,
                    description=str(
                        item.get("description") or "Legacy snapshot indicator"
                    ),
                    detail=item.get("detail"),
                    thresholds=rule.to_dict() if rule else {},
                    staleness_days=staleness_days,
                    quality_status=quality_status,
                )
            )

    def _assessment_input_hash(
        self,
        *,
        assessment: RiskAssessment,
        metrics: dict[str, Metric],
        source_status: dict[str, Any],
        ruleset_hash: str,
        is_demo: bool,
    ) -> str:
        metric_payload = [
            {
                "key": key,
                "value": self._float_or_none(metrics[key].value),
                "unit": metrics[key].unit,
                "source": metrics[key].source,
                "as_of": metrics[key].as_of,
                "detail": metrics[key].detail,
            }
            for key in sorted(metrics)
        ]
        return self._hash_payload(
            {
                "market_as_of": assessment.market_as_of,
                "score_version": self.risk_engine.SCORE_VERSION,
                "ruleset_hash": ruleset_hash,
                "is_demo": is_demo,
                "metrics": metric_payload,
                "source_status": source_status,
            }
        )

    @staticmethod
    def _validate_run_type(run_type: str) -> None:
        if run_type not in VALID_RUN_TYPES:
            allowed = ", ".join(sorted(VALID_RUN_TYPES))
            raise ValueError(f"run_type must be one of: {allowed}")

    @staticmethod
    def _canonical_key(
        market_as_of: date,
        score_version: str,
        is_demo: bool,
    ) -> str:
        partition = "demo" if is_demo else "live"
        return f"{market_as_of.isoformat()}:{score_version}:{partition}"

    @staticmethod
    def _canonical_for_date(
        market_as_of: date,
        score_version: str,
        is_demo: bool,
    ) -> ScoreRun | None:
        return ScoreRun.query.filter_by(
            market_as_of=market_as_of,
            score_version=score_version,
            is_demo=is_demo,
            is_canonical=True,
        ).one_or_none()

    @staticmethod
    def _clear_canonical(run: ScoreRun | None) -> None:
        if run is None:
            return
        run.is_canonical = False
        run.canonical_key = None
        db.session.flush()

    def _select_canonical(self, run: ScoreRun) -> None:
        if run.is_canonical:
            return
        current = self._canonical_for_date(
            run.market_as_of,
            run.score_version,
            run.is_demo,
        )
        self._clear_canonical(current)
        run.is_canonical = True
        run.canonical_key = self._canonical_key(
            run.market_as_of,
            run.score_version,
            run.is_demo,
        )
        db.session.flush()

    @staticmethod
    def _next_revision(
        market_as_of: date,
        score_version: str,
        is_demo: bool,
    ) -> int:
        maximum = (
            db.session.query(func.max(ScoreRun.revision))
            .filter(
                ScoreRun.market_as_of == market_as_of,
                ScoreRun.score_version == score_version,
                ScoreRun.is_demo.is_(is_demo),
            )
            .scalar()
        )
        return int(maximum or 0) + 1

    @classmethod
    def _hash_payload(cls, payload: Any) -> str:
        encoded = json.dumps(
            cls._normalise(payload),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(encoded.encode()).hexdigest()

    @classmethod
    def _normalise(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, dict):
            ordered_items = sorted(value.items(), key=lambda item: str(item[0]))
            return {str(key): cls._normalise(item) for key, item in ordered_items}
        if isinstance(value, set):
            normalized = [cls._normalise(item) for item in value]
            return sorted(
                normalized,
                key=lambda item: json.dumps(
                    item,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            )
        if isinstance(value, (list, tuple)):
            return [cls._normalise(item) for item in value]
        item_method = getattr(value, "item", None)
        if callable(item_method):
            return cls._normalise(item_method())
        return str(value)

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        if value is None:
            return None
        try:
            converted = float(value)
        except (TypeError, ValueError):
            return None
        return converted if math.isfinite(converted) else None

    @staticmethod
    def _quality_status(value: float | None, staleness_days: int | None) -> str:
        if value is None:
            return "missing"
        if staleness_days is not None and staleness_days < 0:
            return "future"
        return "valid"

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _end_of_day_utc(value: date) -> datetime:
        return datetime.combine(value, time.max, tzinfo=UTC)
