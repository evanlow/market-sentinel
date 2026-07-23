from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

CORE_SYMBOLS: dict[str, str] = {
    "spy": "SPY",
    "soxx": "SOXX",
    "vix": "^VIX",
    "wti": "CL=F",
    "kospi": "^KS11",
}

SECTOR_SYMBOLS: dict[str, str] = {
    "sector_xlb": "XLB",
    "sector_xlc": "XLC",
    "sector_xle": "XLE",
    "sector_xlf": "XLF",
    "sector_xli": "XLI",
    "sector_xlk": "XLK",
    "sector_xlp": "XLP",
    "sector_xlre": "XLRE",
    "sector_xlu": "XLU",
    "sector_xlv": "XLV",
    "sector_xly": "XLY",
}

ALL_SYMBOLS = {**CORE_SYMBOLS, **SECTOR_SYMBOLS}


class MarketDataError(RuntimeError):
    pass


class YahooMarketDataClient:
    """Convenience provider for delayed end-of-day market data.

    Yahoo Finance/yfinance is suitable for an MVP and personal monitoring, but it
    should be replaceable with a licensed production feed for commercial or
    intraday use.
    """

    def __init__(self, period: str = "2y") -> None:
        self.period = period

    def fetch(
        self,
        symbols: dict[str, str] | None = None,
    ) -> tuple[dict[str, pd.Series], dict[str, Any]]:
        requested = symbols or ALL_SYMBOLS
        tickers = list(dict.fromkeys(requested.values()))
        status: dict[str, Any] = {"provider": "yfinance", "symbols": {}}

        try:
            raw = yf.download(
                tickers=tickers,
                period=self.period,
                interval="1d",
                auto_adjust=True,
                actions=False,
                progress=False,
                group_by="ticker",
                threads=True,
            )
        except Exception as exc:  # pragma: no cover - network/provider failure
            raise MarketDataError(f"Market-data download failed: {exc}") from exc

        result: dict[str, pd.Series] = {}
        for key, symbol in requested.items():
            try:
                series = self._extract_close(raw, symbol, len(tickers) == 1)
                series = self._normalise_series(series)
                if series.empty:
                    raise ValueError("empty close series")
                result[key] = series
                status["symbols"][key] = {
                    "symbol": symbol,
                    "status": "ok",
                    "observations": int(series.size),
                    "latest": series.index[-1].date().isoformat(),
                }
            except Exception as exc:
                logger.warning("Unable to load %s (%s): %s", key, symbol, exc)
                status["symbols"][key] = {
                    "symbol": symbol,
                    "status": "error",
                    "error": str(exc),
                }

        if "spy" not in result:
            raise MarketDataError("SPY data is required to calculate a market snapshot")

        return result, status

    @staticmethod
    def _extract_close(raw: pd.DataFrame, symbol: str, single_ticker: bool) -> pd.Series:
        if raw.empty:
            raise ValueError("provider returned no rows")

        if not isinstance(raw.columns, pd.MultiIndex):
            if "Close" not in raw.columns:
                raise ValueError("Close column is missing")
            return raw["Close"]

        level_zero = set(raw.columns.get_level_values(0))
        level_one = set(raw.columns.get_level_values(1))

        if symbol in level_zero:
            frame = raw[symbol]
            if "Close" not in frame.columns:
                raise ValueError("Close column is missing")
            return frame["Close"]

        if "Close" in level_zero:
            close = raw["Close"]
            if isinstance(close, pd.Series):
                return close
            if symbol in close.columns:
                return close[symbol]
            if single_ticker and len(close.columns) == 1:
                return close.iloc[:, 0]

        if symbol in level_one:
            frame = raw.xs(symbol, axis=1, level=1)
            if "Close" not in frame.columns:
                raise ValueError("Close column is missing")
            return frame["Close"]

        raise ValueError(f"No close data returned for {symbol}")

    @staticmethod
    def _normalise_series(series: pd.Series) -> pd.Series:
        normalised = pd.Series(
            pd.to_numeric(series, errors="coerce").to_numpy(),
            index=pd.to_datetime(series.index, errors="coerce"),
            dtype="float64",
        ).dropna()
        normalised = normalised[~normalised.index.isna()]
        if getattr(normalised.index, "tz", None) is not None:
            normalised.index = normalised.index.tz_localize(None)
        return normalised[~normalised.index.duplicated(keep="last")].sort_index()


def sector_keys() -> Iterable[str]:
    return SECTOR_SYMBOLS.keys()
