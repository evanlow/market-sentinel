from __future__ import annotations

from datetime import date

from market_sentinel.services.risk import RiskEngine
from market_sentinel.services.types import Metric


VALUES = {
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


def metrics_with(overrides=None):
    values = {**VALUES, **(overrides or {})}
    return {
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


def test_calm_market_scores_green():
    assessment = RiskEngine().assess(date(2026, 1, 5), metrics_with())
    assert assessment.score == 0
    assert assessment.regime == "green"
    assert assessment.coverage == 1.0
    assert not any(trigger["active"] for trigger in assessment.triggers)


def test_multi_factor_stress_scores_red_or_critical():
    assessment = RiskEngine().assess(
        date(2026, 1, 5),
        metrics_with(
            {
                "spy_drawdown_252d_pct": -18,
                "spy_vs_50d_pct": -7,
                "spy_vs_200d_pct": -10,
                "spy_5d_return_pct": -9,
                "vix_level": 42,
                "vix_5d_change_pct": 80,
                "sector_breadth_above_200d_pct": 20,
                "soxx_relative_20d_pct": -8,
                "soxx_5d_return_pct": -12,
                "hy_oas_pct": 8.5,
                "hy_oas_20obs_change_bps": 160,
                "dgs10_5obs_change_bps": 55,
                "wti_20d_return_pct": 35,
                "kospi_5d_return_pct": -12,
                "margin_debt_gdp_pct": 4.2,
            }
        ),
    )
    assert assessment.score == 100
    assert assessment.regime == "critical"
    assert sum(1 for trigger in assessment.triggers if trigger["active"]) >= 6


def test_missing_metrics_reduce_coverage_without_rescaling_score():
    metrics = metrics_with()
    metrics["hy_oas_pct"].value = None
    metrics["hy_oas_20obs_change_bps"].value = None
    assessment = RiskEngine().assess(date(2026, 1, 5), metrics)
    assert assessment.score == 0
    assert assessment.coverage == 0.83
