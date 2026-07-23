from __future__ import annotations

from market_sentinel.services.alerts import AlertPolicy


def triggers(active_count):
    return [
        {"key": f"t{index}", "label": f"Trigger {index}", "active": index < active_count}
        for index in range(7)
    ]


def test_alert_is_suppressed_when_coverage_is_low():
    decision = AlertPolicy(0.7).evaluate(
        score=90,
        coverage=0.6,
        score_change_1d=20,
        score_change_3d=30,
        triggers=triggers(7),
        previous_score=80,
    )
    assert not decision.should_send


def test_three_active_triggers_generate_red_alert():
    decision = AlertPolicy(0.7).evaluate(
        score=55,
        coverage=0.9,
        score_change_1d=5,
        score_change_3d=10,
        triggers=triggers(3),
        previous_score=45,
    )
    assert decision.should_send
    assert decision.severity == "red"


def test_critical_score_generates_critical_alert():
    decision = AlertPolicy().evaluate(
        score=88,
        coverage=1.0,
        score_change_1d=12,
        score_change_3d=20,
        triggers=triggers(2),
        previous_score=70,
    )
    assert decision.should_send
    assert decision.severity == "critical"
