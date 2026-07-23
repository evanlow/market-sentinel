from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from .types import IndicatorResult, Metric, RiskAssessment

Direction = Literal["gte", "lte"]


@dataclass(frozen=True, slots=True)
class Rule:
    key: str
    max_points: int
    direction: Direction
    thresholds: tuple[tuple[float, int], ...]

    def score(self, value: float) -> int:
        for threshold, points in self.thresholds:
            if self.direction == "gte" and value >= threshold:
                return points
            if self.direction == "lte" and value <= threshold:
                return points
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "max_points": self.max_points,
            "direction": self.direction,
            "thresholds": [
                {"threshold": threshold, "points": points}
                for threshold, points in self.thresholds
            ],
        }


class RiskEngine:
    SCORE_VERSION = "1.0.0"
    INDICATOR_VERSION = "1.0.0"
    TOTAL_MAX_POINTS = 100

    RULES = (
        Rule(
            "spy_drawdown_252d_pct",
            12,
            "lte",
            ((-15, 12), (-10, 9), (-5, 6), (-3, 3)),
        ),
        Rule("spy_vs_50d_pct", 7, "lte", ((-5, 7), (-2, 5), (0, 3))),
        Rule("spy_vs_200d_pct", 10, "lte", ((-8, 10), (-3, 8), (0, 5))),
        Rule("spy_5d_return_pct", 6, "lte", ((-8, 6), (-5, 4), (-2, 2))),
        Rule("vix_level", 12, "gte", ((40, 12), (30, 9), (25, 6), (20, 3))),
        Rule("vix_5d_change_pct", 3, "gte", ((75, 3), (40, 2), (20, 1))),
        Rule(
            "sector_breadth_above_200d_pct",
            10,
            "lte",
            ((30, 10), (50, 6), (70, 3)),
        ),
        Rule("soxx_relative_20d_pct", 4, "lte", ((-5, 4), (-2, 2))),
        Rule("soxx_5d_return_pct", 1, "lte", ((-5, 1),)),
        Rule(
            "hy_oas_pct",
            10,
            "gte",
            ((8, 10), (6, 8), (4.5, 6), (3.5, 3)),
        ),
        Rule(
            "hy_oas_20obs_change_bps",
            7,
            "gte",
            ((150, 7), (100, 6), (50, 4), (25, 2)),
        ),
        Rule("dgs10_5obs_change_bps", 3, "gte", ((50, 3), (30, 2), (15, 1))),
        Rule("wti_20d_return_pct", 3, "gte", ((30, 3), (20, 2), (10, 1))),
        Rule("kospi_5d_return_pct", 2, "lte", ((-10, 2), (-5, 1))),
        Rule("margin_debt_gdp_pct", 10, "gte", ((4, 10), (3.5, 6), (2.5, 3))),
    )

    def assess(self, market_as_of, metrics: dict[str, Metric]) -> RiskAssessment:
        results: list[IndicatorResult] = []
        score = 0
        covered_points = 0

        for rule in self.RULES:
            metric = metrics[rule.key]
            available = metric.value is not None
            points = rule.score(metric.value) if available else 0
            if available:
                covered_points += rule.max_points
            score += points
            results.append(
                IndicatorResult(
                    key=metric.key,
                    label=metric.label,
                    category=metric.category,
                    value=metric.value,
                    unit=metric.unit,
                    display_value=self._format(metric.value, metric.unit),
                    points=points,
                    max_points=rule.max_points,
                    status=self._status(points, rule.max_points, available),
                    source=metric.source,
                    as_of=metric.as_of.isoformat() if metric.as_of else None,
                    description=metric.description,
                    detail=metric.detail,
                )
            )

        score = min(score, self.TOTAL_MAX_POINTS)
        coverage = covered_points / self.TOTAL_MAX_POINTS
        triggers = self._critical_triggers(metrics)
        return RiskAssessment(
            market_as_of=market_as_of,
            score=score,
            regime=self.regime_for_score(score),
            coverage=coverage,
            indicators=results,
            triggers=triggers,
        )

    @classmethod
    def ruleset_payload(cls) -> dict[str, Any]:
        return {
            "score_version": cls.SCORE_VERSION,
            "indicator_version": cls.INDICATOR_VERSION,
            "total_max_points": cls.TOTAL_MAX_POINTS,
            "rules": [rule.to_dict() for rule in cls.RULES],
        }

    @classmethod
    def ruleset_hash(cls) -> str:
        payload = json.dumps(
            cls.ruleset_payload(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @classmethod
    def rule_for_key(cls, key: str) -> Rule | None:
        return next((rule for rule in cls.RULES if rule.key == key), None)

    @staticmethod
    def regime_for_score(score: int) -> str:
        if score >= 85:
            return "critical"
        if score >= 70:
            return "red"
        if score >= 50:
            return "amber"
        if score >= 30:
            return "yellow"
        return "green"

    @staticmethod
    def _status(points: int, maximum: int, available: bool) -> str:
        if not available:
            return "unavailable"
        ratio = points / maximum if maximum else 0
        if ratio >= 0.75:
            return "severe"
        if ratio >= 0.40:
            return "elevated"
        if points > 0:
            return "watch"
        return "normal"

    @staticmethod
    def _format(value: float | None, unit: str) -> str:
        if value is None:
            return "Not available"
        if unit == "%":
            return f"{value:+.2f}%"
        if unit == "pp":
            return f"{value:+.2f} pp"
        if unit == "bps":
            return f"{value:+.0f} bps"
        if unit == "index":
            return f"{value:.2f}"
        return f"{value:.2f}"

    @staticmethod
    def _critical_triggers(metrics: dict[str, Metric]) -> list[dict[str, object]]:
        checks = (
            (
                "spy_below_200d",
                "S&P 500 is below its 200-day average",
                metrics["spy_vs_200d_pct"].value is not None
                and metrics["spy_vs_200d_pct"].value < 0,
            ),
            (
                "vix_above_30",
                "VIX is at or above 30",
                metrics["vix_level"].value is not None
                and metrics["vix_level"].value >= 30,
            ),
            (
                "hy_spread_widening",
                "High-yield spreads widened by at least 75 bps over 20 observations",
                metrics["hy_oas_20obs_change_bps"].value is not None
                and metrics["hy_oas_20obs_change_bps"].value >= 75,
            ),
            (
                "soxx_fast_drop",
                "Semiconductors fell at least 10% over five sessions",
                metrics["soxx_5d_return_pct"].value is not None
                and metrics["soxx_5d_return_pct"].value <= -10,
            ),
            (
                "spy_fast_drop",
                "S&P 500 fell at least 5% over five sessions",
                metrics["spy_5d_return_pct"].value is not None
                and metrics["spy_5d_return_pct"].value <= -5,
            ),
            (
                "breadth_collapse",
                "Fewer than 30% of tracked US sectors are above their 200-day averages",
                metrics["sector_breadth_above_200d_pct"].value is not None
                and metrics["sector_breadth_above_200d_pct"].value < 30,
            ),
            (
                "kospi_fast_drop",
                "KOSPI fell at least 10% over five sessions",
                metrics["kospi_5d_return_pct"].value is not None
                and metrics["kospi_5d_return_pct"].value <= -10,
            ),
        )
        return [
            {"key": key, "label": label, "active": bool(active)}
            for key, label, active in checks
        ]
