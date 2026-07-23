from __future__ import annotations

from dataclasses import dataclass

import requests


@dataclass(slots=True)
class MailResult:
    success: bool
    provider_id: str | None = None
    error: str | None = None


class MailgunMailer:
    def __init__(
        self,
        *,
        api_key: str,
        domain: str,
        sender: str,
        api_base: str = "https://api.mailgun.net",
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key
        self.domain = domain
        self.sender = sender
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.domain and self.sender)

    def send(
        self,
        *,
        recipients: list[str],
        subject: str,
        text: str,
        html: str | None = None,
        tags: list[str] | None = None,
    ) -> MailResult:
        if not self.configured:
            return MailResult(False, error="Mailgun is not fully configured")
        if not recipients:
            return MailResult(False, error="No email recipients are configured")

        data: list[tuple[str, str]] = [
            ("from", self.sender),
            ("subject", subject),
            ("text", text),
        ]
        data.extend(("to", recipient) for recipient in recipients)
        if html:
            data.append(("html", html))
        data.extend(("o:tag", tag) for tag in (tags or []))

        endpoint = f"{self.api_base}/v3/{self.domain}/messages"
        try:
            response = requests.post(
                endpoint,
                auth=("api", self.api_key),
                data=data,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return MailResult(True, provider_id=payload.get("id"))
        except (requests.RequestException, ValueError) as exc:
            return MailResult(False, error=str(exc))
