from __future__ import annotations

import json
from datetime import UTC, date, datetime

from market_sentinel.extensions import db
from market_sentinel.models import ScoreRun, Snapshot


def test_migrate_history_command_is_idempotent(app):
    with app.app_context():
        db.session.add(
            Snapshot(
                market_as_of=date(2026, 1, 5),
                score=42,
                regime="yellow",
                coverage=0.9,
                indicators=[],
                triggers=[],
                source_status={"legacy": True},
                is_demo=False,
            )
        )
        db.session.commit()

    runner = app.test_cli_runner()
    first = runner.invoke(args=["sentinel", "migrate-history"])
    second = runner.invoke(args=["sentinel", "migrate-history"])

    assert first.exit_code == 0
    assert "1 created" in first.output
    assert second.exit_code == 0
    assert "1 already present" in second.output
    with app.app_context():
        assert ScoreRun.query.count() == 1


def test_export_history_writes_atomic_jsonl_with_lineage(app, tmp_path):
    with app.app_context():
        run = ScoreRun(
            market_as_of=date(2026, 1, 5),
            calculated_at=datetime(2026, 1, 6, tzinfo=UTC),
            data_cutoff_at=datetime(2026, 1, 5, 23, 59, tzinfo=UTC),
            score=42,
            regime="yellow",
            coverage=1.0,
            score_change_1d=None,
            score_change_3d=None,
            score_version="1.0.0",
            ruleset_hash="rules",
            input_hash="input",
            revision=1,
            run_type="live",
            is_canonical=True,
            canonical_key="2026-01-05:1.0.0",
            ruleset={"rules": []},
            indicators=[],
            triggers=[],
            source_status={},
            is_demo=False,
        )
        db.session.add(run)
        db.session.commit()

    output = tmp_path / "history.jsonl"
    result = app.test_cli_runner().invoke(
        args=[
            "sentinel",
            "export-history",
            "--output",
            str(output),
            "--format",
            "jsonl",
            "--include-lineage",
        ]
    )

    assert result.exit_code == 0
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["score"] == 42
    assert payload["ruleset"] == {"rules": []}
    assert payload["indicators"] == []
