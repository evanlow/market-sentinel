from __future__ import annotations

import re
from collections import defaultdict

from flask import Blueprint, current_app, jsonify, render_template, request
from sqlalchemy import desc, text

from .extensions import db
from .models import ScoreRun, Snapshot

bp = Blueprint("main", __name__)


@bp.get("/")
def dashboard():
    latest = Snapshot.query.filter_by(is_demo=False).order_by(desc(Snapshot.market_as_of)).first()
    if latest is None:
        latest = Snapshot.query.order_by(desc(Snapshot.market_as_of)).first()

    history = (
        ScoreRun.query.filter_by(is_canonical=True, is_demo=False)
        .order_by(desc(ScoreRun.market_as_of))
        .limit(60)
        .all()
    )
    if not history:
        history_query = Snapshot.query.filter_by(is_demo=False)
        if latest is not None and latest.is_demo:
            history_query = Snapshot.query
        history = history_query.order_by(desc(Snapshot.market_as_of)).limit(60).all()
    history.reverse()

    categories = defaultdict(list)
    if latest:
        for indicator in latest.indicators:
            categories[indicator["category"]].append(indicator)

    chart = {
        "labels": [row.market_as_of.isoformat() for row in history],
        "scores": [row.score for row in history],
    }
    return render_template(
        "dashboard.html",
        latest=latest,
        categories=dict(categories),
        chart=chart,
    )


@bp.get("/api/status")
def api_status():
    latest = Snapshot.query.filter_by(is_demo=False).order_by(desc(Snapshot.market_as_of)).first()
    if latest is None:
        latest = Snapshot.query.order_by(desc(Snapshot.market_as_of)).first()
    if latest is None:
        return jsonify({"status": "no_data", "message": "No snapshot has been collected yet."})

    payload = latest.to_dict()
    research_run = (
        ScoreRun.query.filter_by(
            market_as_of=latest.market_as_of,
            is_canonical=True,
            is_demo=latest.is_demo,
        )
        .order_by(desc(ScoreRun.calculated_at))
        .first()
    )
    if research_run is not None:
        payload["research"] = {
            "score_run_id": research_run.id,
            "score_version": research_run.score_version,
            "revision": research_run.revision,
            "ruleset_hash": research_run.ruleset_hash,
            "input_hash": research_run.input_hash,
        }
    return jsonify(payload)


@bp.get("/api/history")
def api_history():
    try:
        limit = int(request.args.get("limit", "60"))
    except ValueError:
        return _bad_request("limit must be an integer")

    maximum = current_app.config["HISTORY_API_MAX_LIMIT"]
    if limit < 1 or limit > maximum:
        return _bad_request(f"limit must be between 1 and {maximum}")

    include_revisions = _boolean_query_argument("include_revisions", default=False)
    if include_revisions is None:
        return _bad_request("include_revisions must be true or false")

    score_version = request.args.get("score_version")
    if score_version is not None:
        score_version = score_version.strip()
        if not score_version or len(score_version) > 32:
            return _bad_request("score_version must contain between 1 and 32 characters")
        if re.fullmatch(r"[A-Za-z0-9._-]+", score_version) is None:
            return _bad_request("score_version contains unsupported characters")

    query = ScoreRun.query.filter(ScoreRun.is_demo.is_(False))
    if not include_revisions:
        query = query.filter(ScoreRun.is_canonical.is_(True))
    if score_version:
        query = query.filter(ScoreRun.score_version == score_version)

    rows = (
        query.order_by(desc(ScoreRun.market_as_of), desc(ScoreRun.revision))
        .limit(limit)
        .all()
    )
    rows.reverse()
    return jsonify(
        {
            "count": len(rows),
            "include_revisions": include_revisions,
            "score_version": score_version,
            "runs": [row.to_dict() for row in rows],
        }
    )


@bp.get("/api/history/<int:run_id>")
def api_history_detail(run_id: int):
    run = db.session.get(ScoreRun, run_id)
    if run is None or run.is_demo:
        return jsonify({"error": "score run not found"}), 404
    return jsonify(run.to_dict(include_lineage=True))


@bp.get("/healthz")
def healthz():
    db.session.execute(text("SELECT 1"))
    return jsonify({"status": "ok"})


def _boolean_query_argument(name: str, *, default: bool) -> bool | None:
    raw = request.args.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _bad_request(message: str):
    return jsonify({"error": message}), 400
