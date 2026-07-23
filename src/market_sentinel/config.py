from __future__ import annotations

import os
from typing import Any


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def normalize_database_url(url: str) -> str:
    # Some platforms still provide the retired postgres:// URI form.
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def default_config() -> dict[str, Any]:
    database_url = normalize_database_url(
        os.getenv("DATABASE_URL", "sqlite:///market_sentinel.db")
    )

    return {
        "APP_ENV": os.getenv("APP_ENV", "development"),
        "SECRET_KEY": os.getenv("SECRET_KEY", "dev-only-change-me"),
        "SQLALCHEMY_DATABASE_URI": database_url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "MARKET_DATA_PERIOD": os.getenv("MARKET_DATA_PERIOD", "2y"),
        "FRED_API_KEY": os.getenv("FRED_API_KEY", ""),
        "OPENAI_ENABLED": env_bool("OPENAI_ENABLED", False),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        "OPENAI_TIMEOUT_SECONDS": env_float("OPENAI_TIMEOUT_SECONDS", 30.0),
        "MAILGUN_API_KEY": os.getenv("MAILGUN_API_KEY", ""),
        "MAILGUN_DOMAIN": os.getenv("MAILGUN_DOMAIN", ""),
        "MAILGUN_FROM_EMAIL": os.getenv(
            "MAILGUN_FROM_EMAIL", "Market Sentinel <alerts@example.com>"
        ),
        "MAILGUN_RECIPIENTS": os.getenv("MAILGUN_RECIPIENTS", ""),
        "MAILGUN_API_BASE": os.getenv("MAILGUN_API_BASE", "https://api.mailgun.net"),
        "MAILGUN_TIMEOUT_SECONDS": env_float("MAILGUN_TIMEOUT_SECONDS", 20.0),
        "DAILY_EMAIL_ENABLED": env_bool("DAILY_EMAIL_ENABLED", False),
        "ALERTS_ENABLED": env_bool("ALERTS_ENABLED", False),
        "ALERT_MIN_COVERAGE": env_float("ALERT_MIN_COVERAGE", 0.70),
        "ALERT_COOLDOWN_HOURS": env_int("ALERT_COOLDOWN_HOURS", 18),
        "JSON_SORT_KEYS": False,
    }
