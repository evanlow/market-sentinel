from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .cli import sentinel_cli
from .config import default_config
from .extensions import db
from .routes import bp


def create_app(test_config: dict | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(default_config())
    if test_config:
        app.config.update(test_config)

    if (
        app.config["APP_ENV"] == "production"
        and app.config["SECRET_KEY"] == "dev-only-change-me"
    ):
        raise RuntimeError("Set a strong SECRET_KEY before starting in production")

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if app.config["APP_ENV"] == "development" else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db.init_app(app)
    app.register_blueprint(bp)
    app.cli.add_command(sentinel_cli)
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
    )  # type: ignore[method-assign]

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "connect-src 'self'; img-src 'self' data:;",
        )
        return response

    return app
