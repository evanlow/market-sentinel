from __future__ import annotations

from datetime import date

from market_sentinel.extensions import db
from market_sentinel.models import AlertEvent, Snapshot
from market_sentinel.services.mailgun import MailResult
from market_sentinel.services.orchestrator import SentinelOrchestrator


class FakeMailer:
    def __init__(self, results: list[MailResult]) -> None:
        self._results = results
        self.calls = 0

    def send(self, **kwargs) -> MailResult:  # noqa: ANN003
        self.calls += 1
        return self._results[self.calls - 1]


def test_process_alert_retries_failed_delivery(app):
    with app.app_context():
        snapshot = Snapshot(
            market_as_of=date(2026, 1, 5),
            score=80,
            regime="red",
            coverage=0.95,
            indicators=[],
            triggers=[],
            source_status={},
            is_demo=False,
        )
        db.session.add(snapshot)
        db.session.commit()

        mailer = FakeMailer([MailResult(False, error="temporary"), MailResult(True, "provider-1")])
        orchestrator = SentinelOrchestrator(mailer=mailer)

        first = orchestrator.process_alert(snapshot, force=True)
        second = orchestrator.process_alert(snapshot, force=True)

        assert first is not None
        assert second is not None
        assert mailer.calls == 2
        assert second.id == first.id

        stored = AlertEvent.query.filter_by(fingerprint=first.fingerprint).one()
        assert stored.status == "sent"
        assert stored.provider_id == "provider-1"
