# Research-Grade Score History

Market Sentinel keeps two complementary persistence layers:

1. `snapshots` remains the operational one-row-per-market-date projection used by the dashboard, email templates, and alert engine.
2. `score_runs` and its child tables form an append-only research record. A recalculation never deletes or overwrites an earlier score run.

This additive design upgrades existing installations without destructively changing the original `snapshots` table.

## Why preserve every score run?

Persistent history supports questions that cannot be answered from the latest dashboard value alone:

- Did elevated scores precede subsequent corrections?
- Which indicators usually deteriorated first?
- How often did a high score become a false positive?
- Did a ruleset change improve lead time or merely fit historical data?
- What did Market Sentinel actually publish on a particular date?
- Did later provider corrections alter the canonical result?

A score is therefore stored together with its methodology, input identity, revision, and normalized indicator lineage.

## Data model

### `score_runs`

Each row represents one immutable calculation result. Important fields include:

- `market_as_of`: market date being assessed;
- `calculated_at`: UTC calculation timestamp;
- `data_cutoff_at`: end-of-day cutoff represented by the run;
- `score`, `regime`, and `coverage`;
- `score_version`: semantic version of the deterministic methodology;
- `ruleset_hash`: SHA-256 identity of the complete weights and thresholds;
- `input_hash`: SHA-256 identity of the exact metric bundle and source status;
- `revision`: sequential revision for a market date and score version;
- `run_type`: `live`, `revision`, `backfill`, `simulation`, or `legacy`;
- `is_canonical`: whether this is the currently selected result for the date/version;
- `supersedes_run_id`: prior canonical revision, when applicable;
- `code_commit_sha`: deployment commit supplied through `APP_GIT_SHA`.

`canonical_key` enforces at most one canonical run for each market date and score version while allowing any number of superseded revisions.

### `indicator_records`

There is one normalized row per scored indicator and score run. It stores the observed value, awarded points, maximum points, status, thresholds, source date, staleness, and quality status.

### `source_observations`

There is one point-in-time source/metric observation per score run. It stores the provider label, observation date, retrieved timestamp, value, unit, quality status, and a payload hash. The current MVP records the exact calculated metric inputs used by the risk engine; a future licensed provider can extend this layer with raw vendor observation identifiers.

### `commentary_runs`

OpenAI commentary is versioned separately from the deterministic score. Records include provider, model, prompt version, input hash, generation status, and summary. AI text never changes the numerical score.

### `market_outcomes`

The schema reserves forward outcomes such as returns, maximum drawdown, realized volatility, correction occurrence, and bear-market occurrence. These rows should be populated only after the selected trading-session horizon has matured. They must never feed back into the live score calculation.

## Idempotency and revisions

The archive service hashes:

- market date;
- score version;
- ruleset hash;
- every metric value, unit, source, and observation date;
- source-status metadata.

Running the daily job twice with identical inputs reuses the existing score run and does not duplicate indicator rows.

When any input changes for the same market date and methodology, Market Sentinel creates the next revision, marks the earlier run non-canonical, records `supersedes_run_id`, and selects the new canonical row. The earlier revision remains queryable and exportable.

This supports two distinct research views:

- **First-published history:** use all revisions to reconstruct what the system emitted at each calculation time.
- **Restated history:** use only canonical runs to study the best currently available result for each market date.

## Upgrade an existing installation

Pull the release, activate the existing project virtual environment, and run:

```bash
flask --app wsgi sentinel init-db
flask --app wsgi sentinel migrate-history
```

`init-db` creates the new additive tables. It does not drop or rewrite the existing `snapshots`, `manual_metrics`, or `alert_events` tables.

`migrate-history` copies existing snapshots into research tables and is safe to run repeatedly. The command reports how many rows were created and how many were already present.

Back up the database before any production upgrade even though this migration is additive.

## Inspect history

```bash
# Canonical score runs, oldest to newest
flask --app wsgi sentinel history --limit 120

# Include superseded revisions
flask --app wsgi sentinel history --limit 120 --include-revisions

# Filter one methodology
flask --app wsgi sentinel history --score-version 1.0.0
```

HTTP endpoints:

```text
GET /api/history?limit=60
GET /api/history?limit=60&include_revisions=true
GET /api/history?score_version=1.0.0
GET /api/history/<score_run_id>
```

The list endpoint omits demo data. The detail endpoint includes normalized indicators, source observations, commentary versions, trigger states, and any matured outcomes.

## Export for offline study

Canonical score summaries as CSV:

```bash
flask --app wsgi sentinel export-history \
  --output /approved/export/path/score-history.csv \
  --format csv
```

Full nested lineage as JSON Lines:

```bash
flask --app wsgi sentinel export-history \
  --output /approved/export/path/score-history.jsonl \
  --format jsonl \
  --include-lineage \
  --include-revisions
```

The exporter verifies that the destination directory exists and writes to a temporary file in the same directory before using an atomic replace. It never creates unexpected parent directories.

## Methodology changes

Change `RiskEngine.SCORE_VERSION` whenever weights, thresholds, indicator formulas, lookback windows, missing-data policy, or scoring semantics materially change.

Do not rewrite older score runs. A new methodology may be backfilled as a separate score version and `run_type=backfill`. Live and backfilled rows can then be compared without mixing methodologies on one unlabeled chart.

## Backup and retention

Retain research history indefinitely. Daily data volume is small, while reconstructing point-in-time lineage later may be impossible.

Recommended production controls:

- PostgreSQL rather than SQLite for a continuously operating server;
- automated daily backups and point-in-time recovery;
- monthly logical dumps to versioned object storage;
- periodic JSONL/CSV research exports with checksums;
- quarterly restore tests;
- `APP_GIT_SHA` populated from the deployed commit;
- documented provider licensing and retention restrictions.

Raw vendor data must be stored only when the applicable license permits retention and redistribution.

## Research cautions

- Use the score as a stress index until out-of-sample evidence supports a calibrated probability interpretation.
- Avoid look-ahead bias. Studies should use the data and revisions actually available at the tested time.
- Separate live observations from backfilled calculations.
- Report false positives, false negatives, coverage, and regime duration rather than only successful warnings.
- Do not tune thresholds solely on the same historical period used to report performance.
