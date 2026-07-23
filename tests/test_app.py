from __future__ import annotations

from datetime import date

from market_sentinel.extensions import db
from market_sentinel.models import Snapshot


def test_dashboard_without_data(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"No market snapshot yet" in response.data


def test_health_and_api_status(client):
    assert client.get("/healthz").get_json() == {"status": "ok"}
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.get_json()["status"] == "no_data"


def test_api_returns_latest_snapshot(app, client):
    with app.app_context():
        db.session.add(
            Snapshot(
                market_as_of=date(2026, 1, 5),
                score=42,
                regime="yellow",
                coverage=0.8,
                indicators=[],
                triggers=[],
                source_status={},
                is_demo=False,
            )
        )
        db.session.commit()

    payload = client.get("/api/status").get_json()
    assert payload["score"] == 42
    assert payload["regime"] == "yellow"


def test_dashboard_and_api_prefer_non_demo_snapshots(app, client):
    with app.app_context():
        db.session.add_all(
            [
                Snapshot(
                    market_as_of=date(2026, 1, 5),
                    score=42,
                    regime="yellow",
                    coverage=0.8,
                    indicators=[],
                    triggers=[],
                    source_status={},
                    is_demo=False,
                ),
                Snapshot(
                    market_as_of=date(2026, 12, 31),
                    score=5,
                    regime="green",
                    coverage=1.0,
                    indicators=[],
                    triggers=[],
                    source_status={},
                    is_demo=True,
                ),
            ]
        )
        db.session.commit()

    payload = client.get("/api/status").get_json()
    assert payload["score"] == 42
    assert payload["market_as_of"] == "2026-01-05"

    response = client.get("/")
    assert response.status_code == 200
    assert b"2026-01-05" in response.data
    assert b"2026-12-31" not in response.data
    assert b"Demonstration data" not in response.data
