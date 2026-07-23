from __future__ import annotations

from .types import AlertDecision


class AlertPolicy:
    def __init__(self, minimum_coverage: float = 0.70) -> None:
        self.minimum_coverage = minimum_coverage

    def evaluate(
        self,
        *,
        score: int,
        coverage: float,
        score_change_1d: float | None,
        score_change_3d: float | None,
        triggers: list[dict],
        previous_score: int | None,
    ) -> AlertDecision:
        if coverage < self.minimum_coverage:
            return AlertDecision(False, None, ["Data coverage is below the alert threshold."])

        active = [item["label"] for item in triggers if item.get("active")]
        reasons: list[str] = []
        severity: str | None = None

        if score >= 85:
            severity = "critical"
            reasons.append(f"Market Stress Score reached {score}/100.")
        elif len(active) >= 5:
            severity = "critical"
            reasons.append(f"{len(active)} critical market triggers are active together.")
        elif score >= 75:
            severity = "red"
            reasons.append(f"Market Stress Score reached {score}/100.")
        elif score >= 70 and previous_score is not None and previous_score >= 70:
            severity = "red"
            reasons.append("The score remained in the red regime for two consecutive market dates.")
        elif score_change_3d is not None and score_change_3d >= 15 and score >= 50:
            severity = "red"
            reasons.append(
                f"The score rose {score_change_3d:.0f} points over three market sessions."
            )
        elif len(active) >= 3:
            severity = "red"
            reasons.append(f"{len(active)} critical market triggers are active together.")

        if severity is None:
            return AlertDecision(False, None, [])

        if score_change_1d is not None and score_change_1d >= 10:
            reasons.append(
                f"The score rose {score_change_1d:.0f} points from the previous market date."
            )
        reasons.extend(active[:5])
        return AlertDecision(True, severity, reasons)
