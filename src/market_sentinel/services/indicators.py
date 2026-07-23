from __future__ import annotations

from datetime import date

import pandas as pd

from .market_data import sector_keys
from .types import Metric


class IndicatorCalculator:
    def calculate(
        self,
        prices: dict[str, pd.Series],
        macro: dict[str, pd.Series],
        *,
        margin_debt_gdp_pct: float | None = None,
        margin_debt_as_of: date | None = None,
    ) -> tuple[date, dict[str, Metric]]:
        spy = self._clean(prices["spy"])
        market_as_of = spy.index[-1].date()
        metrics: dict[str, Metric] = {}

        metrics["spy_drawdown_252d_pct"] = self._metric(
            key="spy_drawdown_252d_pct",
            label="S&P 500 drawdown from 252-day high",
            value=self._drawdown(spy, 252),
            unit="%",
            category="Market trend",
            source="SPY / yfinance",
            series=spy,
            description="Measures how far the S&P 500 proxy is below its trailing one-year high.",
        )
        metrics["spy_vs_50d_pct"] = self._metric(
            key="spy_vs_50d_pct",
            label="S&P 500 distance from 50-day average",
            value=self._distance_from_average(spy, 50),
            unit="%",
            category="Market trend",
            source="SPY / yfinance",
            series=spy,
            description="A negative value indicates an intermediate trend break.",
        )
        metrics["spy_vs_200d_pct"] = self._metric(
            key="spy_vs_200d_pct",
            label="S&P 500 distance from 200-day average",
            value=self._distance_from_average(spy, 200),
            unit="%",
            category="Market trend",
            source="SPY / yfinance",
            series=spy,
            description="A negative value indicates the index is below its long-term trend.",
        )
        metrics["spy_5d_return_pct"] = self._metric(
            key="spy_5d_return_pct",
            label="S&P 500 five-session return",
            value=self._return(spy, 5),
            unit="%",
            category="Market trend",
            source="SPY / yfinance",
            series=spy,
            description="Detects fast drawdowns that can force deleveraging.",
        )

        vix = self._optional(prices, "vix")
        metrics["vix_level"] = self._metric(
            key="vix_level",
            label="VIX level",
            value=self._latest(vix),
            unit="index",
            category="Volatility",
            source="^VIX / yfinance",
            series=vix,
            description=(
                "Higher readings indicate more expensive near-term S&P 500 options protection."
            ),
        )
        metrics["vix_5d_change_pct"] = self._metric(
            key="vix_5d_change_pct",
            label="VIX five-session change",
            value=self._return(vix, 5),
            unit="%",
            category="Volatility",
            source="^VIX / yfinance",
            series=vix,
            description="A rapid volatility increase can reveal a change in risk regime.",
        )

        breadth_value, breadth_as_of, breadth_detail = self._sector_breadth(prices)
        metrics["sector_breadth_above_200d_pct"] = Metric(
            key="sector_breadth_above_200d_pct",
            label="US sector breadth above 200-day averages",
            value=breadth_value,
            unit="%",
            category="Breadth and leadership",
            source="11 Select Sector SPDR ETFs / yfinance",
            as_of=breadth_as_of,
            description="Percentage of major US sector ETFs trading above their 200-day averages.",
            detail=breadth_detail,
        )

        soxx = self._optional(prices, "soxx")
        metrics["soxx_relative_20d_pct"] = self._metric(
            key="soxx_relative_20d_pct",
            label="Semiconductor relative return versus S&P 500",
            value=self._relative_return(soxx, spy, 20),
            unit="pp",
            category="Breadth and leadership",
            source="SOXX and SPY / yfinance",
            series=soxx,
            description=(
                "Negative readings show semiconductor leadership weakening versus the "
                "broad market."
            ),
        )
        metrics["soxx_5d_return_pct"] = self._metric(
            key="soxx_5d_return_pct",
            label="Semiconductor five-session return",
            value=self._return(soxx, 5),
            unit="%",
            category="Breadth and leadership",
            source="SOXX / yfinance",
            series=soxx,
            description=(
                "A sharp fall in semiconductors may signal stress in a concentrated "
                "market leader."
            ),
        )

        hy = self._optional(macro, "hy_oas")
        metrics["hy_oas_pct"] = self._metric(
            key="hy_oas_pct",
            label="US high-yield option-adjusted spread",
            value=self._latest(hy),
            unit="%",
            category="Credit and rates",
            source="FRED BAMLH0A0HYM2",
            series=hy,
            description=(
                "Wider spreads indicate that investors demand more compensation for "
                "credit risk."
            ),
        )
        metrics["hy_oas_20obs_change_bps"] = self._metric(
            key="hy_oas_20obs_change_bps",
            label="High-yield spread change over 20 observations",
            value=self._change(hy, 20, multiplier=100.0),
            unit="bps",
            category="Credit and rates",
            source="FRED BAMLH0A0HYM2",
            series=hy,
            description=(
                "Rapid spread widening is more concerning than an elevated but stable level."
            ),
        )

        ten_year = self._optional(macro, "dgs10")
        metrics["dgs10_5obs_change_bps"] = self._metric(
            key="dgs10_5obs_change_bps",
            label="10-year Treasury yield change over five observations",
            value=self._change(ten_year, 5, multiplier=100.0),
            unit="bps",
            category="Credit and rates",
            source="FRED DGS10",
            series=ten_year,
            description=(
                "A rapid yield rise can tighten financial conditions and pressure valuations."
            ),
        )

        wti = self._optional(prices, "wti")
        metrics["wti_20d_return_pct"] = self._metric(
            key="wti_20d_return_pct",
            label="WTI crude 20-session return",
            value=self._return(wti, 20),
            unit="%",
            category="Global and commodity stress",
            source="CL=F / yfinance",
            series=wti,
            description="A fast oil-price shock can worsen inflation and growth risks.",
        )

        kospi = self._optional(prices, "kospi")
        metrics["kospi_5d_return_pct"] = self._metric(
            key="kospi_5d_return_pct",
            label="KOSPI five-session return",
            value=self._return(kospi, 5),
            unit="%",
            category="Global and commodity stress",
            source="^KS11 / yfinance",
            series=kospi,
            description=(
                "Tracks whether stress in Korea is persisting or spreading, without "
                "assuming contagion."
            ),
        )

        metrics["margin_debt_gdp_pct"] = Metric(
            key="margin_debt_gdp_pct",
            label="FINRA margin debt relative to nominal GDP",
            value=margin_debt_gdp_pct,
            unit="%",
            category="Structural vulnerability",
            source="Manual FINRA value plus FRED GDP",
            as_of=margin_debt_as_of,
            description=(
                "A slow-moving vulnerability indicator. It should not be treated as a "
                "precise crash timer."
            ),
        )

        return market_as_of, metrics

    @staticmethod
    def _clean(series: pd.Series) -> pd.Series:
        clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
        return clean[~clean.index.duplicated(keep="last")]

    def _optional(self, values: dict[str, pd.Series], key: str) -> pd.Series | None:
        series = values.get(key)
        if series is None:
            return None
        clean = self._clean(series)
        return clean if not clean.empty else None

    @staticmethod
    def _latest(series: pd.Series | None) -> float | None:
        if series is None or series.empty:
            return None
        return float(series.iloc[-1])

    @staticmethod
    def _return(series: pd.Series | None, periods: int) -> float | None:
        if series is None or len(series) <= periods:
            return None
        return float((series.iloc[-1] / series.iloc[-periods - 1] - 1.0) * 100.0)

    @staticmethod
    def _relative_return(
        first: pd.Series | None, second: pd.Series | None, periods: int
    ) -> float | None:
        if first is None or second is None:
            return None
        first_return = IndicatorCalculator._return(first, periods)
        second_return = IndicatorCalculator._return(second, periods)
        if first_return is None or second_return is None:
            return None
        return first_return - second_return

    @staticmethod
    def _change(
        series: pd.Series | None, periods: int, *, multiplier: float = 1.0
    ) -> float | None:
        if series is None or len(series) <= periods:
            return None
        return float((series.iloc[-1] - series.iloc[-periods - 1]) * multiplier)

    @staticmethod
    def _distance_from_average(series: pd.Series, window: int) -> float | None:
        if len(series) < window:
            return None
        average = float(series.iloc[-window:].mean())
        if average == 0:
            return None
        return float((series.iloc[-1] / average - 1.0) * 100.0)

    @staticmethod
    def _drawdown(series: pd.Series, window: int) -> float | None:
        if series.empty:
            return None
        recent = series.iloc[-window:]
        peak = float(recent.max())
        if peak == 0:
            return None
        return float((series.iloc[-1] / peak - 1.0) * 100.0)

    def _sector_breadth(
        self, prices: dict[str, pd.Series]
    ) -> tuple[float | None, date | None, str | None]:
        available = 0
        above = 0
        dates: list[date] = []
        for key in sector_keys():
            series = self._optional(prices, key)
            if series is None or len(series) < 200:
                continue
            available += 1
            average = float(series.iloc[-200:].mean())
            if float(series.iloc[-1]) > average:
                above += 1
            dates.append(series.index[-1].date())

        if available == 0:
            return None, None, "No sector ETF had sufficient history."
        return (
            (above / available) * 100.0,
            max(dates),
            f"{above} of {available} sectors above trend",
        )

    @staticmethod
    def _metric(
        *,
        key: str,
        label: str,
        value: float | None,
        unit: str,
        category: str,
        source: str,
        series: pd.Series | None,
        description: str,
    ) -> Metric:
        as_of = None if series is None or series.empty else series.index[-1].date()
        return Metric(
            key=key,
            label=label,
            value=value,
            unit=unit,
            category=category,
            source=source,
            as_of=as_of,
            description=description,
        )
