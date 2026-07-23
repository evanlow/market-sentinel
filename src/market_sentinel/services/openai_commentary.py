from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAICommentaryService:
    PROVIDER = "openai"
    PROMPT_VERSION = "1.0.0"

    def __init__(
        self,
        *,
        enabled: bool,
        api_key: str,
        model: str,
        timeout: float = 30.0,
    ) -> None:
        self.enabled = enabled and bool(api_key)
        self.model = model
        self.client = (
            OpenAI(api_key=api_key, timeout=timeout, max_retries=2) if self.enabled else None
        )

    def generate(self, payload: dict[str, Any]) -> str | None:
        if self.client is None:
            return None

        compact = {
            "market_as_of": payload.get("market_as_of"),
            "score": payload.get("score"),
            "regime": payload.get("regime"),
            "coverage": payload.get("coverage"),
            "score_change_1d": payload.get("score_change_1d"),
            "score_change_3d": payload.get("score_change_3d"),
            "indicators": [
                {
                    "label": item.get("label"),
                    "value": item.get("display_value"),
                    "points": item.get("points"),
                    "max_points": item.get("max_points"),
                    "status": item.get("status"),
                }
                for item in payload.get("indicators", [])
            ],
            "active_triggers": [
                item.get("label") for item in payload.get("triggers", []) if item.get("active")
            ],
        }

        instructions = (
            "You are the commentary layer for a deterministic market-risk monitor. "
            "The numerical score and trigger states are authoritative; never change them. "
            "Write 120 to 180 words in plain English with three short paragraphs: "
            "what deteriorated, what is containing risk, and what to monitor next. "
            "Do not predict a crash, give trading instructions, or present this as "
            "investment advice. Explicitly distinguish vulnerability from an immediate "
            "trigger and mention missing-data "
            "coverage when it is below 90%."
        )
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=json.dumps(compact, separators=(",", ":")),
                max_output_tokens=350,
            )
            text = (response.output_text or "").strip()
            return text or None
        except Exception:  # pragma: no cover - external API failure
            logger.exception("OpenAI commentary generation failed")
            return None
