from __future__ import annotations

import numpy as np
import pandas as pd

from market_sentinel.services.indicators import IndicatorCalculator
from market_sentinel.services.market_data import SECTOR_SYMBOLS


def series(values):
    return pd.Series(values, index=pd.bdate_range("2025-01-01", periods=len(values)))


def test_indicator_calculator_builds_core_metrics():
    upward = series(np.linspace(100, 150, 260))
    vix = series(np.linspace(15, 22, 260))
    soxx = series(np.linspace(100, 155, 260))
    prices = {
        "spy": upward,
        "vix": vix,
        "soxx": soxx,
        "wti": series(np.linspace(70, 75, 260)),
        "kospi": series(np.linspace(2500, 2600, 260)),
    }
    for key in SECTOR_SYMBOLS:
        prices[key] = upward

    macro = {
        "hy_oas": series(np.linspace(3.0, 3.2, 260)),
        "dgs10": series(np.linspace(4.0, 4.1, 260)),
    }

    market_as_of, metrics = IndicatorCalculator().calculate(prices, macro)

    assert market_as_of == upward.index[-1].date()
    assert metrics["spy_vs_200d_pct"].value > 0
    assert metrics["sector_breadth_above_200d_pct"].value == 100.0
    assert metrics["vix_level"].value == 22.0
    assert metrics["margin_debt_gdp_pct"].value is None


def test_indicator_calculator_handles_optional_missing_data():
    spy = series(np.linspace(100, 110, 220))
    market_as_of, metrics = IndicatorCalculator().calculate({"spy": spy}, {})

    assert market_as_of == spy.index[-1].date()
    assert metrics["vix_level"].value is None
    assert metrics["hy_oas_pct"].value is None
    assert metrics["sector_breadth_above_200d_pct"].value is None
