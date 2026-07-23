from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import requests


class FredError(RuntimeError):
    pass


class FredClient:
    BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "market-sentinel/0.1"})

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def fetch_series(
        self,
        series_id: str,
        *,
        observation_start: date | None = None,
    ) -> tuple[pd.Series, dict[str, Any]]:
        if not self.configured:
            raise FredError("FRED_API_KEY is not configured")

        start = observation_start or (date.today() - timedelta(days=800))
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "sort_order": "asc",
        }
        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise FredError(f"FRED request failed for {series_id}: {exc}") from exc

        observations = payload.get("observations", [])
        dates: list[pd.Timestamp] = []
        values: list[float] = []
        for item in observations:
            value = item.get("value")
            if value in {None, "."}:
                continue
            try:
                dates.append(pd.Timestamp(item["date"]))
                values.append(float(value))
            except (KeyError, TypeError, ValueError):
                continue

        series = pd.Series(values, index=pd.DatetimeIndex(dates), dtype="float64")
        series = series[~series.index.duplicated(keep="last")].sort_index()
        if series.empty:
            raise FredError(f"FRED returned no usable observations for {series_id}")

        status = {
            "series_id": series_id,
            "status": "ok",
            "observations": int(series.size),
            "latest": series.index[-1].date().isoformat(),
        }
        return series, status
