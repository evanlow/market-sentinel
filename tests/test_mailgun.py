from __future__ import annotations

from market_sentinel.services.mailgun import MailgunMailer


def test_unconfigured_mailgun_returns_error_without_network_call():
    result = MailgunMailer(api_key="", domain="", sender="").send(
        recipients=["test@example.com"],
        subject="Test",
        text="Body",
    )
    assert not result.success
    assert "not fully configured" in result.error
