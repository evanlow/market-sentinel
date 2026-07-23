from __future__ import annotations

from datetime import UTC, date, datetime

from market_sentinel.extensions import db
from market_sentinel.models import (
    CommentaryRun,
    IndicatorRecord,
    ScoreRun,
    Snapshot,
    SourceObservation,
)
from market_sentinel.services.history import ResearchHistoryService
from market_sentinel.services.risk import RiskEngine
from market_sentinel.services.types import Metric


CALM_VALUES = {
    "spy_drawdown_252d_pct": 0.0,
    "spy_vs_50d_pct": 1.0,
    "spy_vs_200d_pct": 2.0,
    "spy_5d_return_pct": 1.0,
    "vix_level": 15.0,
    "vix_5d_change_pct": 0.0,
    "sector_breadth_above_200d_pct": 90.0,
    "soxx_relative_20d_pct": 1.0,
    "soxx_5d_return_pct": 1.0,
    "hy_oas_pct": 3.0,
    "hy_oas_20obs_change_bps": 0.0,
    "dgs10_5obs_change_bps": 0.0,
    "wti_20d_return_pct": 0.0,
    "kospi_5d_return_pct": 0.0,
    "margin_debt_gdp_pct": 2.0,
}


def metrics_with(overrides: dict[str, float | None] | None = None) -> dict[str, Metric]:
    values = {**CALM_VALUES, **(overrides or {})}
    return {
        key: Metric(
            key=key,
            label=key.replace("_", " ").title(),
            value=value,
            unit="%",
            category="test",
            source="test-provider",
            as_of=date(2026, 1, 5),
            description="Test metric",
        )
        for key, value in values.items()
    }


def archive(
    *,
    metrics: dict[str, Metric],
    run_type: str = "live",
):
    market_as_of = date(2026, 1, 5)
    engine = RiskEngine()
    assessment = engine.assess(market_as_of, metrics)
    return ResearchHistoryService(engine).archive_assessment(
        assessment=assessment,
        metrics=metrics,
        source_status={"market_data": {"provider": "test-provider", "status": "ok"}},
        score_change_1d=None,
        score_change_3d=None,
        run_type=run_type,
        calculated_at=datetime(2026, 1, 6, 0, 30, tzinfo=UTC),
    )


def test_ruleset_payload_and_hash_are_stable():
    engine = RiskEngine()

    payload = engine.ruleset_payload()

    assert payload["score_version"] == engine.SCORE_VERSION
    assert payload["total_max_points"] == 100
    assert len(payload["rules"]) == len(engine.RULES)
    assert len(engine.ruleset_hash()) == 64
    assert engine.ruleset_hash() == RiskEngine().ruleset_hash()


def test_archive_is_idempotent_and_persists_normalized_lineage(app):
    with app.app_context():
        first = archive(metrics=metrics_with())
        db.session.commit()
        repeated = archive(metrics=metrics_with())
        db.session.commit()

        assert first.created is True
        assert repeated.created is False
        assert repeated.run.id == first.run.id
        assert ScoreRun.query.count() == 1
        assert IndicatorRecord.query.count() == len(RiskEngine.RULES)
        assert SourceObservation.query.count() == len(RiskEngine.RULES)

        stored = ScoreRun.query.one()
        assert stored.revision == 1
        assert stored.is_canonical is True
        assert stored.canonical_key == "2026-01-05:1.0.0"
        assert stored.ruleset_hash == RiskEngine().ruleset_hash()
        assert len(stored.input_hash) == 64
        assert stored.indicator_records[0].thresholds
        assert stored.source_observations[0].payload_hash


def test_changed_inputs_create_revision_and_move_canonical_pointer(app):
    with app.app_context():
        first = archive(metrics=metrics_with())
        db.session.commit()

        second = archive(metrics=metrics_with({"vix_level": 31.0}))
        db.session.commit()

        assert second.created is True
        assert second.run.revision == 2
        assert second.run.supersedes_run_id == first.run.id
        assert second.run.is_canonical is True

        db.session.refresh(first.run)
        assert first.run.is_canonical is False
        assert first.run.canonical_key is None
        assert ScoreRun.query.filter_by(is_canonical=True).one().id == second.run.id


def test_commentary_is_versioned_and_idempotent(app):
    with app.app_context():
        archived = archive(metrics=metrics_with())
        service = ResearchHistoryService(RiskEngine())
        first = service.record_commentary(
            archived.run,
            summary="Risk remains contained.",
            provider="openai",
            model="gpt-test",
            prompt_version="1.0.0",
        )
        second = service.record_commentary(
            archived.run,
            summary="Risk remains contained.",
            provider="openai",
            model="gpt-test",
            prompt_version="1.0.0",
        )
        db.session.commit()

        assert first.id == second.id
        assert CommentaryRun.query.count() == 1
        assert first.status == "generated"
        assert len(first.input_hash) == 64


def test_legacy_snapshot_can_be_migrated_without_overwriting_it(app):
    with app.app_context():
        snapshot = Snapshot(
            market_as_of=date(2025, 12, 31),
            score=58,
            regime="amber",
            coverage=0.9,
            score_change_1d=4,
            score_change_3d=9,
            indicators=[
                {
                    "key": "vix_level",
                    "label": "VIX level",
                    "category": "volatility",
                    "value": 25.0,
                    "unit": "index",
                    "display_value": "25.00",
                    "points": 6,
                    "max_points": 12,
                    "status": "elevated",
                    "source": "legacy",
                    "as_of": "2025-12-31",
                    "description": "Legacy snapshot",
                    "detail": None,
                }
            ],
            triggers=[],
            source_status={"legacy": True},
            ai_summary="Legacy summary",
            is_demo=False,
        )
        db.session.add(snapshot)
        db.session.commit()

        result = ResearchHistoryService(RiskEngine()).migrate_snapshot(snapshot)
        db.session.commit()

        assert result.created is True
        assert result.run.run_type == "legacy"
        assert result.run.market_as_of == snapshot.market_as_of
        assert result.run.score == snapshot.score
        assert Snapshot.query.count() == 1
        assert ScoreRun.query.count() == 1
        assert IndicatorRecord.query.count() == 1
        assert CommentaryRun.query.count() == 1
