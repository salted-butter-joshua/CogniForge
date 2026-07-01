"""Tests for per-round token tracking."""

from src.tools.token_tracker import tracker


def test_snapshot_round_delta_and_cumulative():
    tracker.reset()
    tracker.add("student_study", 1000, 200)
    tracker.add("judge_score", 500, 100)
    r0 = tracker.snapshot_round(0)
    assert r0["token_round_total"] == 1800
    assert r0["token_cumulative_total"] == 1800
    assert r0["tokens_by_step_round"]["student_study"] == 1200

    tracker.add("student_study", 800, 150)
    tracker.add("judge_score", 400, 80)
    r1 = tracker.snapshot_round(1)
    assert r1["token_round_total"] == 1430
    assert r1["token_cumulative_total"] == 3230
    assert r1["token_round_input"] == 1200
    assert r1["token_round_output"] == 230
    assert len(tracker.round_history_snapshot()) == 2
