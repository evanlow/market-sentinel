from __future__ import annotations

from collections import defaultdict

from flask import Blueprint, jsonify, render_template
from sqlalchemy import desc, text

from .extensions import db
from .models import Snapshot

bp = Blueprint("main", __name__)


@bp.get("/")
def dashboard():
    latest = Snapshot.query.order_by(desc(Snapshot.market_as_of)).first()
    history = Snapshot.query.order_by(desc(Snapshot.market_as_of)).limit(60).all()
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
    latest = Snapshot.query.order_by(desc(Snapshot.market_as_of)).first()
    if latest is None:
        return jsonify({"status": "no_data", "message": "No snapshot has been collected yet."})
    return jsonify(latest.to_dict())


@bp.get("/healthz")
def healthz():
    db.session.execute(text("SELECT 1"))
    return jsonify({"status": "ok"})
