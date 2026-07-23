from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import pandas as pd


@dataclass(slots=True)
class MarketDataBundle:
    prices: dict[str, pd.Series]
    macro: dict[str, pd.Series]
    source_status: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Metric:
    key: str
    label: str
    value: float | None
    unit: str
    category: str
    source: str
    as_of: date | None
    description: str
    detail: str | None = None


@dataclass(slots=True)
class IndicatorResult:
    key: str
    label: str
    category: str
    value: float | None
    unit: str
    display_value: str
    points: int
    max_points: int
    status: str
    source: str
    as_of: str | None
    description: str
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RiskAssessment:
    market_as_of: date
    score: int
    regime: str
    coverage: float
    indicators: list[IndicatorResult]
    triggers: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_as_of": self.market_as_of.isoformat(),
            "score": self.score,
            "regime": self.regime,
            "coverage": self.coverage,
            "indicators": [indicator.to_dict() for indicator in self.indicators],
            "triggers": self.triggers,
        }


@dataclass(slots=True)
class AlertDecision:
    should_send: bool
    severity: str | None
    reasons: list[str]
