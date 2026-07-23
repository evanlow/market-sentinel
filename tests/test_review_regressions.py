from __future__ import annotations

from datetime import UTC, date, datetime

from market_sentinel.extensions import db
from market_sentinel.models import ScoreRun, Snapshot
from market_sentinel.services.history import ResearchHistoryService
from market_sentinel.services.risk import RiskEngine
from market_sentinel.services.types import Metric


def score_run(
    market_as_of: date,
    score: int,
    *,
    score_version: str = "1.0.0",
    is_demo: bool = False,
    calculated_hour: int = 0,
) -> ScoreRun:
    partition = "demo" if is_demo else "live"
    return ScoreRun(
        market_as_of=market_as_of,
        calculated_at=datetime(2026, 1, 6, calculated_hour, tzinfo=UTC),
        data_cutoff_at=datetime(2026, 1, 5, 23, 59, tzinfo=UTC),
        score=score,
        regime="yellow",
        coverage=1.0,
        score_change_1d=None,
        score_change_3d=None,
        score_version=score_version,
        ruleset_hash=f"rules-{score_version}-{market_as_of.isoformat()}-{partition}",
        input_hash=f"input-{score_version}-{market_as_of.isoformat()}-{partition}",
        revision=1,
        run_type="simulation" if is_demo else "live",
        is_canonical=True,
        canonical_key=f"{market_as_of.isoformat()}:{score_version}:{partition}",
        ruleset={},
        indicators=[],
        triggers=[],
        source_status={},
        is_demo=is_demo,
    )


def snapshot(market_as_of: date, score: int, *, is_demo: bool = False) -> Snapshot:
    return Snapshot(
        market_as_of=market_as_of,
        score=score,
        regime="yellow",
        coverage=1.0,
        indicators=[],
        triggers=[],
        source_status={},
        is_demo=is_demo,
    )


def metric_bundle(market_as_of: date) -> dict[str, Metric]:
    return {
        rule.key: Metric(
            key=rule.key,
            label=rule.key,
            value=0.0,
            unit="%",
            category="test",
            source="test-provider",
            as_of=market_as_of,
            description="Partition test metric",
        )
        for rule in RiskEngine.RULES
    }


def archive_partition(*, is_demo: bool):
    market_as_of = date(2026, 1, 5)
    engine = RiskEngine()
    metrics = metric_bundle(market_as_of)
    assessment = engine.assess(market_as_of, metrics)
    return ResearchHistoryService(engine).archive_assessment(
        assessment=assessment,
        metrics=metrics,
        source_status={"provider": "test-provider"},
        score_change_1d=None,
        score_change_3d=None,
        run_type="simulation" if is_demo else "live",
        calculated_at=datetime(2026, 1, 6, tzinfo=UTC),
        is_demo=is_demo,
    )


def test_hash_normalisation_sorts_sets_and_handles_mixed_mapping_keys():
    normalized = ResearchHistoryService._normalise(
        {"values": {"beta", "alpha"}, 2: "two", "1": "one"}
    )

    assert normalized == {
        "1": "one",
        "2": "two",
        "values": ["alpha", "beta"],
    }


def test_dashboard_uses_only_current_score_version(app, client):
    with app.app_context():
        db.session.add(snapshot(date(2026, 1, 5), 47))
        db.session.add_all(
            [
                score_run(date(2026, 1, 2), 30),
                score_run(date(2026, 1, 5), 47),
                score_run(
                    date(2026, 1, 5),
                    99,
                    score_version="2.0.0",
                    calculated_hour=1,
                ),
            ]
        )
        db.session.commit()

    response = client.get("/")
    payload = client.get("/api/status").get_json()

    assert response.status_code == 200
    assert b'"scores": [30, 47]' in response.data
    assert b'"scores": [30, 47, 99]' not in response.data
    assert payload["research"]["score_version"] == RiskEngine.SCORE_VERSION
    assert payload["research"]["input_hash"].startswith("input-1.0.0")


def test_demo_dashboard_can_use_demo_score_run_history(app, client):
    with app.app_context():
        db.session.add(snapshot(date(2099, 1, 1), 58, is_demo=True))
        db.session.add_all(
            [
                score_run(date(2098, 12, 31), 40, is_demo=True),
                score_run(date(2099, 1, 1), 58, is_demo=True),
            ]
        )
        db.session.commit()

    response = client.get("/")

    assert response.status_code == 200
    assert b'"scores": [40, 58]' in response.data


def test_migration_does_not_replace_existing_live_run(app):
    with app.app_context():
        market_date = date(2026, 1, 5)
        live_run = score_run(market_date, 47)
        legacy_snapshot = snapshot(market_date, 47)
        db.session.add_all([live_run, legacy_snapshot])
        db.session.commit()

        result = ResearchHistoryService(RiskEngine()).migrate_snapshot(legacy_snapshot)
        db.session.commit()

        assert result.created is False
        assert result.run.id == live_run.id
        assert ScoreRun.query.count() == 1
        assert live_run.run_type == "live"
        assert live_run.is_canonical is True


def test_demo_and_live_archives_are_independent_partitions(app):
    with app.app_context():
        live = archive_partition(is_demo=False)
        demo = archive_partition(is_demo=True)
        db.session.commit()

        assert live.created is True
        assert demo.created is True
        assert live.run.id != demo.run.id
        assert live.run.is_canonical is True
        assert demo.run.is_canonical is True
        assert live.run.canonical_key == "2026-01-05:1.0.0:live"
        assert demo.run.canonical_key == "2026-01-05:1.0.0:demo"
        assert ScoreRun.query.count() == 2


def test_demo_snapshot_migration_does_not_cross_live_partition(app):
    with app.app_context():
        market_date = date(2026, 1, 5)
        live_run = score_run(market_date, 47)
        demo_snapshot = snapshot(market_date, 58, is_demo=True)
        db.session.add_all([live_run, demo_snapshot])
        db.session.commit()

        result = ResearchHistoryService(RiskEngine()).migrate_snapshot(
            demo_snapshot,
            run_type="simulation",
        )
        db.session.commit()

        assert result.created is True
        assert result.run.is_demo is True
        assert result.run.is_canonical is True
        assert live_run.is_canonical is True
        assert result.run.canonical_key != live_run.canonical_key
        assert ScoreRun.query.count() == 2
