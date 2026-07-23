from __future__ import annotations

import pytest

from market_sentinel import create_app
from market_sentinel.extensions import db


@pytest.fixture()
def app(tmp_path):
    database_path = tmp_path / "test.sqlite"
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "testing",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            "OPENAI_ENABLED": False,
            "ALERTS_ENABLED": False,
            "DAILY_EMAIL_ENABLED": False,
            "MAILGUN_RECIPIENTS": "test@example.com",
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()
