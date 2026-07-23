from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import date
from pathlib import Path

import click
from flask.cli import AppGroup
from sqlalchemy import desc

from .extensions import db
from .models import ManualMetric, ScoreRun, Snapshot
from .services.history import ResearchHistoryService
from .services.orchestrator import SentinelOrchestrator
from .services.risk import RiskEngine

sentinel_cli = AppGroup("sentinel", help="Collect, score, and report market-risk data.")


@sentinel_cli.command("init-db")
def init_db():
    """Create all operational and research-history database tables."""
    db.create_all()
    click.echo("Database tables created.")


@sentinel_cli.command("refresh")
@click.option("--no-ai", is_flag=True, help="Skip optional OpenAI commentary.")
def refresh(no_ai: bool):
    """Collect data and store an operational snapshot plus immutable score run."""
    snapshot = SentinelOrchestrator().refresh(generate_commentary=not no_ai)
    click.echo(json.dumps(snapshot.to_dict(), indent=2))


@sentinel_cli.command("run-daily")
@click.option("--no-ai", is_flag=True, help="Skip optional OpenAI commentary.")
@click.option("--force-email", is_flag=True, help="Send the daily email even if disabled.")
@click.option("--force-alert", is_flag=True, help="Send a test alert even if no rule fires.")
def run_daily(no_ai: bool, force_email: bool, force_alert: bool):
    """Refresh, evaluate red-alert rules, and optionally send the daily email."""
    result = SentinelOrchestrator().run_daily(
        generate_commentary=not no_ai,
        force_email=force_email,
        force_alert=force_alert,
    )
    click.echo(json.dumps(result, indent=2))


@sentinel_cli.command("send-daily")
@click.option("--force", is_flag=True, help="Send even when DAILY_EMAIL_ENABLED is false.")
def send_daily(force: bool):
    """Send the latest stored non-demo snapshot as a daily email."""
    snapshot = _latest_snapshot()
    if snapshot is None:
        raise click.ClickException("No snapshot is available. Run sentinel refresh first.")
    sent = SentinelOrchestrator().send_daily(snapshot, force=force)
    click.echo("Email sent." if sent else "Email not sent; check configuration and logs.")


@sentinel_cli.command("evaluate-alert")
@click.option("--force", is_flag=True, help="Send a test alert even when no rule fires.")
def evaluate_alert(force: bool):
    """Evaluate alert rules against the latest stored non-demo snapshot."""
    snapshot = _latest_snapshot()
    if snapshot is None:
        raise click.ClickException("No snapshot is available. Run sentinel refresh first.")
    event = SentinelOrchestrator().process_alert(snapshot, force=force)
    if event is None:
        click.echo("No alert was sent.")
    else:
        click.echo(f"Alert status: {event.status}; event id: {event.id}")


@sentinel_cli.command("migrate-history")
def migrate_history():
    """Copy legacy snapshots into the additive research-history tables."""
    service = ResearchHistoryService(RiskEngine())
    created, reused = service.migrate_all_snapshots()
    db.session.commit()
    click.echo(f"History migration complete: {created} created, {reused} already present.")


@sentinel_cli.command("history")
@click.option("--limit", type=click.IntRange(1, 5000), default=60, show_default=True)
@click.option("--include-revisions", is_flag=True, help="Include superseded revisions.")
@click.option("--score-version", default=None, help="Filter by deterministic score version.")
def history(limit: int, include_revisions: bool, score_version: str | None):
    """Print stored score-run summaries as JSON."""
    rows = _history_rows(
        limit=limit,
        include_revisions=include_revisions,
        score_version=score_version,
    )
    click.echo(json.dumps([row.to_dict() for row in rows], indent=2))


@sentinel_cli.command("export-history")
@click.option(
    "--output",
    type=click.Path(path_type=Path, dir_okay=False, resolve_path=True),
    required=True,
    help="Destination .jsonl or .csv file.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["jsonl", "csv"], case_sensitive=False),
    required=True,
)
@click.option("--limit", type=click.IntRange(1, 5000), default=5000, show_default=True)
@click.option("--include-revisions", is_flag=True, help="Include superseded revisions.")
@click.option("--include-lineage", is_flag=True, help="Include normalized lineage in JSONL.")
@click.option("--score-version", default=None, help="Filter by deterministic score version.")
def export_history(
    output: Path,
    output_format: str,
    limit: int,
    include_revisions: bool,
    include_lineage: bool,
    score_version: str | None,
):
    """Atomically export score history for offline studies."""
    if not output.parent.exists() or not output.parent.is_dir():
        raise click.ClickException(f"Output directory does not exist: {output.parent}")
    if output.exists() and output.is_dir():
        raise click.ClickException("--output must be a file path")
    if output_format == "csv" and include_lineage:
        raise click.ClickException("--include-lineage is supported only with JSONL")

    rows = _history_rows(
        limit=limit,
        include_revisions=include_revisions,
        score_version=score_version,
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            if output_format == "jsonl":
                for row in rows:
                    payload = row.to_dict(include_lineage=include_lineage)
                    handle.write(json.dumps(payload, sort_keys=True) + "\n")
            else:
                fieldnames = [
                    "id",
                    "market_as_of",
                    "calculated_at",
                    "data_cutoff_at",
                    "score",
                    "regime",
                    "coverage",
                    "score_change_1d",
                    "score_change_3d",
                    "score_version",
                    "ruleset_hash",
                    "input_hash",
                    "code_commit_sha",
                    "revision",
                    "run_type",
                    "is_canonical",
                    "supersedes_run_id",
                    "is_demo",
                    "ai_summary",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow(row.to_dict())
        os.replace(temporary_path, output)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    click.echo(f"Exported {len(rows)} score runs to {output}.")


@sentinel_cli.command("set-margin-debt")
@click.option("--value", type=float, required=True, help="FINRA debit balances in USD millions.")
@click.option("--as-of", "as_of_text", required=True, help="Reference month/date in YYYY-MM-DD.")
@click.option("--source-url", default=None, help="Optional source URL for auditability.")
@click.option("--notes", default=None, help="Optional notes.")
def set_margin_debt(
    value: float,
    as_of_text: str,
    source_url: str | None,
    notes: str | None,
):
    """Store a monthly FINRA margin-debt observation for the structural indicator."""
    try:
        as_of = date.fromisoformat(as_of_text)
    except ValueError as exc:
        raise click.ClickException("--as-of must use YYYY-MM-DD") from exc

    metric = ManualMetric.query.filter_by(
        key="finra_margin_debt_usd_millions",
        as_of=as_of,
    ).one_or_none()
    if metric is None:
        metric = ManualMetric(
            key="finra_margin_debt_usd_millions",
            as_of=as_of,
            value=value,
            unit="USD millions",
        )
        db.session.add(metric)
    metric.value = value
    metric.source_url = source_url
    metric.notes = notes
    db.session.commit()
    click.echo(f"Stored FINRA margin debt {value:,.0f} USD millions for {as_of.isoformat()}.")


@sentinel_cli.command("seed-demo")
def seed_demo():
    """Insert a clearly labelled sample snapshot so the dashboard can be previewed."""
    demo_date = date(2099, 1, 1)
    snapshot = Snapshot.query.filter_by(market_as_of=demo_date).one_or_none()
    if snapshot is None:
        snapshot = Snapshot(market_as_of=demo_date)
        db.session.add(snapshot)
    snapshot.score = 58
    snapshot.regime = "amber"
    snapshot.coverage = 0.90
    snapshot.score_change_1d = 9
    snapshot.score_change_3d = 14
    snapshot.indicators = [
        {
            "key": "demo",
            "label": "Demonstration indicator",
            "category": "Demo data",
            "value": 24.7,
            "unit": "index",
            "display_value": "24.70",
            "points": 6,
            "max_points": 12,
            "status": "elevated",
            "source": "Synthetic demonstration only",
            "as_of": demo_date.isoformat(),
            "description": "Delete this snapshot before using the application operationally.",
            "detail": None,
        }
    ]
    snapshot.triggers = [
        {
            "key": "demo",
            "label": "Synthetic demonstration trigger",
            "active": False,
        }
    ]
    snapshot.source_status = {"demo": True}
    snapshot.ai_summary = (
        "This is synthetic demonstration content. It is not based on live market data and "
        "must not be used for decisions."
    )
    snapshot.is_demo = True
    db.session.flush()
    ResearchHistoryService(RiskEngine()).migrate_snapshot(
        snapshot,
        run_type="simulation",
    )
    db.session.commit()
    click.echo("Demo snapshot inserted with the future date 2099-01-01.")


def _latest_snapshot() -> Snapshot | None:
    snapshot = Snapshot.query.filter_by(is_demo=False).order_by(desc(Snapshot.market_as_of)).first()
    if snapshot is not None:
        return snapshot
    return Snapshot.query.order_by(desc(Snapshot.market_as_of)).first()


def _history_rows(
    *,
    limit: int,
    include_revisions: bool,
    score_version: str | None,
) -> list[ScoreRun]:
    query = ScoreRun.query.filter(ScoreRun.is_demo.is_(False))
    if not include_revisions:
        query = query.filter(ScoreRun.is_canonical.is_(True))
    if score_version:
        query = query.filter(ScoreRun.score_version == score_version.strip())
    rows = (
        query.order_by(desc(ScoreRun.market_as_of), desc(ScoreRun.revision))
        .limit(limit)
        .all()
    )
    rows.reverse()
    return rows
