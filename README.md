# Market Sentinel

Market Sentinel is a Flask application that converts a set of market, volatility, breadth, credit,
rates, commodity, global, and structural indicators into a deterministic **0-100 Market Stress
Score**. It provides a web dashboard, persistent research-grade score history, optional OpenAI-generated
plain-English commentary, Mailgun daily summaries, and rule-based red alerts.

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
          |          |             |
          v          v             v
 operational     versioned      alert policy
 snapshot        score runs          |
          |          |        optional OpenAI
          v          v             |
 Flask dashboard  research API    Mailgun
                    + exports
```

The OpenAI layer never changes the score or trigger states. It receives compact calculated data and
produces an explanatory narrative only. Commentary versions are stored separately from deterministic
score runs.

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
| `APP_GIT_SHA` | Optional deployed commit SHA stored with new score runs |
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
| `HISTORY_API_MAX_LIMIT` | Maximum records returned by one history API request |

Mailgun EU-region users can set `MAILGUN_API_BASE=https://api.eu.mailgun.net`.

## Commands

```bash
# Create operational and research-history tables
flask --app wsgi sentinel init-db

# Collect and score live data
flask --app wsgi sentinel refresh

# Refresh, evaluate alerts, and send the enabled daily email
flask --app wsgi sentinel run-daily

# Test configured email delivery
flask --app wsgi sentinel send-daily --force
flask --app wsgi sentinel evaluate-alert --force

# Copy legacy snapshots into append-only research history
flask --app wsgi sentinel migrate-history

# Inspect canonical history or include superseded revisions
flask --app wsgi sentinel history --limit 120
flask --app wsgi sentinel history --limit 120 --include-revisions

# Export summaries or full normalized lineage
flask --app wsgi sentinel export-history \
  --output /approved/path/score-history.csv \
  --format csv
flask --app wsgi sentinel export-history \
  --output /approved/path/score-history.jsonl \
  --format jsonl \
  --include-lineage \
  --include-revisions

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

## Research history and reproducibility

Every deterministic refresh is archived as a versioned `score_run`. Identical same-day inputs are
idempotent; changed inputs create a new revision and preserve the earlier result. Each run stores:

- score version, full ruleset, ruleset hash, and optional deployed commit SHA;
- exact metric-input hash, source status, calculation timestamp, and data cutoff;
- normalized indicator values, points, thresholds, source dates, and quality status;
- canonical/superseded state and revision lineage;
- separately versioned OpenAI commentary;
- a schema for matured forward outcomes used only in later studies.

The original `snapshots` table remains as the operational projection for dashboard and alert
compatibility. The research tables are additive, so existing installations can upgrade with:

```bash
flask --app wsgi sentinel init-db
flask --app wsgi sentinel migrate-history
```

History endpoints:

```text
GET /api/history?limit=60
GET /api/history?limit=60&include_revisions=true
GET /api/history?score_version=1.0.0
GET /api/history/<score_run_id>
```

See [`docs/RESEARCH_HISTORY.md`](docs/RESEARCH_HISTORY.md) for the schema, revision semantics, export
workflow, backup policy, methodology-version rules, and research cautions.

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
See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for Docker, EC2, cron, PostgreSQL, and backup notes.

## Data-source limitations

- `yfinance` is a convenient delayed-data dependency, not a contractual real-time feed. Replace
  `YahooMarketDataClient` with a licensed provider before commercial or time-critical use.
- FRED observations can be delayed or revised and have different publication calendars.
- Sector ETF breadth is a transparent proxy, not the percentage of all S&P 500 constituents above
  their moving averages.
- Margin debt/GDP is a slow structural measure and can remain high for a long time before a decline.
- Stored vendor observations remain subject to provider licensing and retention restrictions.
- No score can eliminate false positives, false negatives, model risk, or provider outages.

## Development

```bash
ruff check .
pytest --cov=market_sentinel --cov-report=term-missing
```

The code is organized under `src/market_sentinel/`; data acquisition, indicator calculation, scoring,
history, commentary, and delivery are separate services so providers and thresholds can be changed
independently.

## AI-Assisted Development

This repository uses `prime_directive.md` as the main engineering guideline for human contributors and
AI coding agents.

Important supporting files:

- `.github/copilot-instructions.md` - GitHub Copilot repository instructions
- `AGENTS.md` - General AI agent instructions
- `session_log.md` - AI-assisted development session log
- `.github/pull_request_template.md` - PR checklist

### Development Rules

Before making changes:

1. Read `prime_directive.md`.
2. Work on a feature branch.
3. Verify the environment.
4. Run relevant tests.
5. Do not commit secrets.
6. Document test results and risks before handoff.

## Disclaimer

Market Sentinel is for informational and software-development purposes. It is not financial, investment,
legal, tax, or trading advice. It does not guarantee that a correction or crash will occur, and it may
fail to detect one. Verify all data and consult qualified professionals before making financial decisions.
