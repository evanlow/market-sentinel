from __future__ import annotations

from datetime import UTC, date, datetime

from market_sentinel.extensions import db
from market_sentinel.models import ScoreRun


def score_run(market_as_of: date, score: int, *, revision: int = 1, canonical: bool = True):
    version = "1.0.0"
    return ScoreRun(
        market_as_of=market_as_of,
        calculated_at=datetime(2026, 1, 6, tzinfo=UTC),
        data_cutoff_at=datetime(2026, 1, 5, 23, 59, tzinfo=UTC),
        score=score,
        regime="yellow",
        coverage=1.0,
        score_change_1d=None,
        score_change_3d=None,
        score_version=version,
        ruleset_hash=f"rules-{market_as_of.isoformat()}-{revision}",
        input_hash=f"input-{market_as_of.isoformat()}-{revision}",
        revision=revision,
        run_type="live",
        is_canonical=canonical,
        canonical_key=f"{market_as_of.isoformat()}:{version}" if canonical else None,
        ruleset={},
        indicators=[],
        triggers=[],
        source_status={},
        is_demo=False,
    )


def test_history_api_returns_only_canonical_runs_by_default(app, client):
    with app.app_context():
        db.session.add_all(
            [
                score_run(date(2026, 1, 2), 30),
                score_run(date(2026, 1, 5), 42, revision=1, canonical=False),
                score_run(date(2026, 1, 5), 47, revision=2, canonical=True),
            ]
        )
        db.session.commit()

    response = client.get("/api/history?limit=10")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["count"] == 2
    assert [row["score"] for row in payload["runs"]] == [30, 47]
    assert payload["runs"][-1]["revision"] == 2


def test_history_api_can_include_revisions(app, client):
    with app.app_context():
        db.session.add_all(
            [
                score_run(date(2026, 1, 5), 42, revision=1, canonical=False),
                score_run(date(2026, 1, 5), 47, revision=2, canonical=True),
            ]
        )
        db.session.commit()

    payload = client.get("/api/history?limit=10&include_revisions=true").get_json()

    assert payload["count"] == 2
    assert [row["revision"] for row in payload["runs"]] == [1, 2]


def test_history_api_validates_query_parameters(client):
    assert client.get("/api/history?limit=0").status_code == 400
    assert client.get("/api/history?limit=not-a-number").status_code == 400
    assert client.get("/api/history?limit=5001").status_code == 400
    assert client.get("/api/history?include_revisions=maybe").status_code == 400
