from __future__ import annotations

from datetime import date

import pandas as pd

from market_sentinel.models import ScoreRun, Snapshot
from market_sentinel.services.orchestrator import SentinelOrchestrator
from market_sentinel.services.risk import RiskEngine
from market_sentinel.services.types import Metric


class FakeMarketClient:
    def fetch(self):
        index = pd.to_datetime(["2026-01-02", "2026-01-05"])
        return {"spy": pd.Series([100.0, 101.0], index=index)}, {"status": "ok"}


class FakeFredClient:
    configured = False


class FakeCalculator:
    def calculate(self, prices, macro, *, margin_debt_gdp_pct, margin_debt_as_of):
        values = {
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
            "margin_debt_gdp_pct": margin_debt_gdp_pct,
        }
        metrics = {
            key: Metric(
                key=key,
                label=key,
                value=value,
                unit="%",
                category="test",
                source="test",
                as_of=date(2026, 1, 5),
                description="test",
            )
            for key, value in values.items()
        }
        return date(2026, 1, 5), metrics


def test_refresh_dual_writes_snapshot_and_idempotent_score_run(app):
    with app.app_context():
        orchestrator = SentinelOrchestrator(
            market_client=FakeMarketClient(),
            fred_client=FakeFredClient(),
            calculator=FakeCalculator(),
            risk_engine=RiskEngine(),
        )

        first = orchestrator.refresh(generate_commentary=False)
        second = orchestrator.refresh(generate_commentary=False)

        assert first.id == second.id
        assert Snapshot.query.count() == 1
        assert ScoreRun.query.count() == 1
        stored = ScoreRun.query.one()
        assert stored.market_as_of == date(2026, 1, 5)
        assert stored.is_canonical is True
        assert stored.input_hash
