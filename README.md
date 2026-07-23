# Market Sentinel

Market Sentinel is a Flask application that converts a set of market, volatility, breadth, credit,
rates, commodity, global, and structural indicators into a deterministic **0–100 Market Stress
Score**. It provides a web dashboard, optional OpenAI-generated plain-English commentary, Mailgun daily
summaries, and rule-based red alerts.

It is deliberately described as a **risk monitor**, not a crash predictor. Margin debt, valuations, and
concentration describe vulnerability; faster indicators such as trend breaks, volatility, breadth, and
credit-spread widening are treated as potential triggers.

## Current MVP

The initial score covers:

- SPY drawdown, 50-day trend, 200-day trend, and five-session return;
- VIX level and five-session acceleration;
- breadth across the 11 Select Sector SPDR ETFs;
- SOXX absolute and relative performance;
- US high-yield option-adjusted spreads and 10-year Treasury yield changes from FRED;
- WTI crude momentum and KOSPI five-session stress;
- manually entered FINRA margin debt divided by the latest available nominal GDP observation.

A missing indicator contributes zero points **and reduces the coverage percentage**. Automated red
alerts are suppressed when coverage is below the configured minimum, rather than silently treating
missing stress data as calm.

## Architecture

```text
Yahoo Finance / FRED / monthly FINRA input
                  |
                  v
         indicator calculator
                  |
                  v
       deterministic risk engine
          |                 |
          v                 v
     Flask dashboard    alert policy
                            |
             optional OpenAI explanation
                            |
                         Mailgun
```

The OpenAI layer never changes the score or trigger states. It receives compact calculated data and
produces an explanatory narrative only.

## Quick start

Python 3.11 or newer is required.

```bash
git clone https://github.com/evanlow/market-sentinel.git
cd market-sentinel
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
flask --app wsgi sentinel init-db
flask --app wsgi sentinel refresh --no-ai
flask --app wsgi run --debug
```

Open `http://127.0.0.1:5000`.

The first live refresh needs outbound internet access. FRED indicators require `FRED_API_KEY`; without
it, the dashboard still calculates available market indicators and clearly reports reduced coverage.

## Configuration

Set values in `.env` locally and use a host secret store in production. Never commit `.env`.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLite by default, or a PostgreSQL URI |
| `FRED_API_KEY` | High-yield spread, Treasury yield, and GDP data |
| `OPENAI_ENABLED` | Enables commentary only when also supplied an API key |
| `OPENAI_API_KEY` | Server-side OpenAI credential |
| `OPENAI_MODEL` | Configurable model, default `gpt-5-mini` |
| `MAILGUN_API_KEY` / `MAILGUN_DOMAIN` | Email provider credentials |
| `MAILGUN_RECIPIENTS` | Comma-separated recipients |
| `DAILY_EMAIL_ENABLED` | Enables the scheduled daily summary |
| `ALERTS_ENABLED` | Enables rule-triggered alert delivery |
| `ALERT_MIN_COVERAGE` | Default `0.70`; lower coverage suppresses alerts |
| `ALERT_COOLDOWN_HOURS` | Prevents repeated same-severity alerts |

Mailgun EU-region users can set `MAILGUN_API_BASE=https://api.eu.mailgun.net`.

## Commands

```bash
# Create tables
flask --app wsgi sentinel init-db

# Collect and score live data
flask --app wsgi sentinel refresh

# Refresh, evaluate alerts, and send the enabled daily email
flask --app wsgi sentinel run-daily

# Test configured email delivery
flask --app wsgi sentinel send-daily --force
flask --app wsgi sentinel evaluate-alert --force

# Record FINRA debit balances, in USD millions
flask --app wsgi sentinel set-margin-debt \
  --value 1000000 \
  --as-of 2026-05-31 \
  --source-url "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics"
```

FINRA margin statistics are monthly and are intentionally entered as an audited manual observation in
this MVP. This avoids pretending that a slow-moving monthly series is a live daily signal and avoids a
fragile scraper. A future provider module can automate the monthly import while retaining the same data
model.

## Alert policy

A red or critical alert can be generated when sufficient data is available and one of these conditions
is met:

- score reaches 85;
- at least five critical triggers are active;
- score reaches 75;
- score stays at or above 70 for two market dates;
- score rises at least 15 points over three market sessions while at or above 50;
- at least three critical triggers are active together.

Critical trigger checks include the S&P 500 below its 200-day average, VIX at or above 30, rapid
high-yield spread widening, fast SPY or SOXX losses, breadth collapse, and a sharp KOSPI decline.
KOSPI stress is deliberately a small component: it is evidence of global risk appetite and possible
forced selling, not proof that US contagion must follow.

## Scheduling

Use an external scheduler rather than APScheduler inside a multi-worker web process. For a Singapore
morning workflow, run the daily CLI after the completed US session and after provider data has settled.
See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for Docker, EC2, cron, and PostgreSQL notes.

## Data-source limitations

- `yfinance` is a convenient delayed-data dependency, not a contractual real-time feed. Replace
  `YahooMarketDataClient` with a licensed provider before commercial or time-critical use.
- FRED observations can be delayed or revised and have different publication calendars.
- Sector ETF breadth is a transparent proxy, not the percentage of all S&P 500 constituents above
  their moving averages.
- Margin debt/GDP is a slow structural measure and can remain high for a long time before a decline.
- No score can eliminate false positives, false negatives, model risk, or provider outages.

## Development

```bash
ruff check .
pytest --cov=market_sentinel --cov-report=term-missing
```

The code is organized under `src/market_sentinel/`; data acquisition, indicator calculation, scoring,
commentary, and delivery are separate services so providers and thresholds can be changed independently.

## Disclaimer

Market Sentinel is for informational and software-development purposes. It is not financial, investment,
legal, tax, or trading advice. It does not guarantee that a correction or crash will occur, and it may
fail to detect one. Verify all data and consult qualified professionals before making financial decisions.
