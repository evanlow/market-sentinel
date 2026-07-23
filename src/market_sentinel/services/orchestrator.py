from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from flask import current_app, render_template
from sqlalchemy import desc

from ..extensions import db
from ..models import AlertEvent, ManualMetric, Snapshot
from .alerts import AlertPolicy
from .fred import FredClient, FredError
from .indicators import IndicatorCalculator
from .mailgun import MailgunMailer
from .market_data import YahooMarketDataClient
from .openai_commentary import OpenAICommentaryService
from .risk import RiskEngine

logger = logging.getLogger(__name__)


class SentinelOrchestrator:
    def __init__(
        self,
        *,
        market_client: YahooMarketDataClient | None = None,
        fred_client: FredClient | None = None,
        calculator: IndicatorCalculator | None = None,
        risk_engine: RiskEngine | None = None,
        commentary: OpenAICommentaryService | None = None,
        mailer: MailgunMailer | None = None,
    ) -> None:
        config = current_app.config
        self.market_client = market_client or YahooMarketDataClient(config["MARKET_DATA_PERIOD"])
        self.fred_client = fred_client or FredClient(config["FRED_API_KEY"])
        self.calculator = calculator or IndicatorCalculator()
        self.risk_engine = risk_engine or RiskEngine()
        self.commentary = commentary or OpenAICommentaryService(
            enabled=config["OPENAI_ENABLED"],
            api_key=config["OPENAI_API_KEY"],
            model=config["OPENAI_MODEL"],
            timeout=config["OPENAI_TIMEOUT_SECONDS"],
        )
        self.mailer = mailer or MailgunMailer(
            api_key=config["MAILGUN_API_KEY"],
            domain=config["MAILGUN_DOMAIN"],
            sender=config["MAILGUN_FROM_EMAIL"],
            api_base=config["MAILGUN_API_BASE"],
            timeout=config["MAILGUN_TIMEOUT_SECONDS"],
        )
        self.alert_policy = AlertPolicy(config["ALERT_MIN_COVERAGE"])

    def refresh(self, *, generate_commentary: bool = True) -> Snapshot:
        prices, market_status = self.market_client.fetch()
        macro, fred_status = self._fetch_macro()
        source_status: dict[str, Any] = {
            "market_data": market_status,
            "fred": fred_status,
        }

        preliminary_as_of = prices["spy"].index[-1].date()
        margin_pct, margin_as_of, margin_status = self._margin_debt_to_gdp(
            macro, preliminary_as_of
        )
        source_status["margin_debt"] = margin_status

        market_as_of, metrics = self.calculator.calculate(
            prices,
            macro,
            margin_debt_gdp_pct=margin_pct,
            margin_debt_as_of=margin_as_of,
        )
        assessment = self.risk_engine.assess(market_as_of, metrics)

        previous_rows = (
            Snapshot.query.filter(Snapshot.market_as_of < market_as_of)
            .order_by(desc(Snapshot.market_as_of))
            .limit(3)
            .all()
        )
        previous = previous_rows[0] if previous_rows else None
        third_previous = previous_rows[2] if len(previous_rows) >= 3 else None
        change_1d = assessment.score - previous.score if previous else None
        change_3d = assessment.score - third_previous.score if third_previous else None

        snapshot = Snapshot.query.filter_by(market_as_of=market_as_of).one_or_none()
        if snapshot is None:
            snapshot = Snapshot(market_as_of=market_as_of)
            db.session.add(snapshot)

        snapshot.captured_at = datetime.now(timezone.utc)
        snapshot.score = assessment.score
        snapshot.regime = assessment.regime
        snapshot.coverage = assessment.coverage
        snapshot.score_change_1d = change_1d
        snapshot.score_change_3d = change_3d
        snapshot.indicators = [item.to_dict() for item in assessment.indicators]
        snapshot.triggers = assessment.triggers
        snapshot.source_status = source_status
        snapshot.ai_summary = None
        snapshot.is_demo = False
        db.session.commit()

        if generate_commentary:
            summary = self.commentary.generate(snapshot.to_dict())
            if summary:
                snapshot.ai_summary = summary
                db.session.commit()

        return snapshot

    def process_alert(self, snapshot: Snapshot, *, force: bool = False) -> AlertEvent | None:
        if not current_app.config["ALERTS_ENABLED"] and not force:
            return None

        previous = (
            Snapshot.query.filter(Snapshot.market_as_of < snapshot.market_as_of)
            .order_by(desc(Snapshot.market_as_of))
            .first()
        )
        decision = self.alert_policy.evaluate(
            score=snapshot.score,
            coverage=snapshot.coverage,
            score_change_1d=snapshot.score_change_1d,
            score_change_3d=snapshot.score_change_3d,
            triggers=snapshot.triggers,
            previous_score=previous.score if previous else None,
        )
        if not decision.should_send and not force:
            return None

        severity = decision.severity or "test"
        reasons = decision.reasons or ["Forced test alert."]
        fingerprint = self._alert_fingerprint(snapshot.market_as_of, severity, reasons)
        existing = AlertEvent.query.filter_by(fingerprint=fingerprint).one_or_none()
        if existing is not None:
            return existing

        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=current_app.config["ALERT_COOLDOWN_HOURS"]
        )
        recent = (
            AlertEvent.query.filter(
                AlertEvent.status == "sent",
                AlertEvent.severity == severity,
                AlertEvent.sent_at >= cutoff,
            )
            .order_by(desc(AlertEvent.sent_at))
            .first()
        )
        if recent is not None and not force:
            return None

        recipients = self._recipients()
        subject = f"{severity.upper()} ALERT — Market Sentinel {snapshot.score}/100"
        text = render_template(
            "email/alert.txt",
            snapshot=snapshot,
            reasons=reasons,
            severity=severity,
        )
        html = render_template(
            "email/alert.html",
            snapshot=snapshot,
            reasons=reasons,
            severity=severity,
        )
        result = self.mailer.send(
            recipients=recipients,
            subject=subject,
            text=text,
            html=html,
            tags=["market-sentinel", severity],
        )
        event = AlertEvent(
            snapshot_id=snapshot.id,
            severity=severity,
            subject=subject,
            reasons=reasons,
            fingerprint=fingerprint,
            status="sent" if result.success else "failed",
            recipients=recipients,
            provider_id=result.provider_id,
            error=result.error,
            sent_at=datetime.now(timezone.utc) if result.success else None,
        )
        db.session.add(event)
        db.session.commit()
        return event

    def send_daily(self, snapshot: Snapshot, *, force: bool = False) -> bool:
        if not current_app.config["DAILY_EMAIL_ENABLED"] and not force:
            return False
        recipients = self._recipients()
        subject = (
            f"Market Sentinel Daily — {snapshot.regime.upper()} — "
            f"{snapshot.score}/100 ({snapshot.market_as_of.isoformat()})"
        )
        text = render_template("email/daily.txt", snapshot=snapshot)
        html = render_template("email/daily.html", snapshot=snapshot)
        result = self.mailer.send(
            recipients=recipients,
            subject=subject,
            text=text,
            html=html,
            tags=["market-sentinel", "daily"],
        )
        if not result.success:
            logger.error("Daily email failed: %s", result.error)
        return result.success

    def run_daily(
        self,
        *,
        generate_commentary: bool = True,
        force_email: bool = False,
        force_alert: bool = False,
    ) -> dict[str, Any]:
        snapshot = self.refresh(generate_commentary=generate_commentary)
        alert = self.process_alert(snapshot, force=force_alert)
        daily_sent = self.send_daily(snapshot, force=force_email)
        return {
            "snapshot": snapshot.to_dict(),
            "alert_status": alert.status if alert else None,
            "daily_email_sent": daily_sent,
        }

    def _fetch_macro(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.fred_client.configured:
            return {}, {"status": "disabled", "reason": "FRED_API_KEY is not configured"}

        macro = {}
        status: dict[str, Any] = {"status": "ok", "series": {}}
        series_map = {
            "hy_oas": "BAMLH0A0HYM2",
            "dgs10": "DGS10",
            "gdp": "GDP",
        }
        for key, series_id in series_map.items():
            try:
                series, series_status = self.fred_client.fetch_series(series_id)
                macro[key] = series
                status["series"][key] = series_status
            except FredError as exc:
                status["series"][key] = {
                    "series_id": series_id,
                    "status": "error",
                    "error": str(exc),
                }
        if not macro:
            status["status"] = "error"
        elif len(macro) < len(series_map):
            status["status"] = "partial"
        return macro, status

    @staticmethod
    def _margin_debt_to_gdp(
        macro: dict[str, Any], market_as_of: date
    ) -> tuple[float | None, date | None, dict[str, Any]]:
        metric = (
            ManualMetric.query.filter(
                ManualMetric.key == "finra_margin_debt_usd_millions",
                ManualMetric.as_of <= market_as_of,
            )
            .order_by(desc(ManualMetric.as_of))
            .first()
        )
        if metric is None:
            return None, None, {
                "status": "missing",
                "reason": "No manually entered FINRA margin debt value is available",
            }

        gdp = macro.get("gdp")
        if gdp is None or gdp.empty:
            return None, metric.as_of, {
                "status": "partial",
                "margin_debt_as_of": metric.as_of.isoformat(),
                "reason": "GDP data is unavailable",
            }

        gdp_available = gdp[gdp.index.date <= market_as_of]
        if gdp_available.empty:
            return None, metric.as_of, {
                "status": "partial",
                "margin_debt_as_of": metric.as_of.isoformat(),
                "reason": "No GDP observation predates the market date",
            }

        latest_gdp_billions = float(gdp_available.iloc[-1])
        ratio_pct = metric.value / (latest_gdp_billions * 1000.0) * 100.0
        return ratio_pct, metric.as_of, {
            "status": "ok",
            "margin_debt_as_of": metric.as_of.isoformat(),
            "margin_debt_usd_millions": metric.value,
            "gdp_as_of": gdp_available.index[-1].date().isoformat(),
            "gdp_usd_billions_annual_rate": latest_gdp_billions,
            "ratio_pct": ratio_pct,
        }

    @staticmethod
    def _alert_fingerprint(market_as_of: date, severity: str, reasons: list[str]) -> str:
        raw = json.dumps(
            {
                "market_as_of": market_as_of.isoformat(),
                "severity": severity,
                "reasons": sorted(reasons),
            },
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _recipients() -> list[str]:
        raw = current_app.config["MAILGUN_RECIPIENTS"]
        return [item.strip() for item in raw.split(",") if item.strip()]
