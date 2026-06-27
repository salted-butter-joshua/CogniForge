"""Conditional routing functions."""

from __future__ import annotations

from src.config import get_settings, load_loop_config
from src.graph.state import LearnLoopState

loop_cfg = load_loop_config()


def route_after_fetch(state: LearnLoopState) -> str:
    if state.get("status") == "failed":
        return "finalize"
    return "generate_material"


def route_after_material(state: LearnLoopState) -> str:
    if state.get("status") == "failed":
        return "finalize"
    return "student_study"


def route_after_study(state: LearnLoopState) -> str:
    if state.get("status") == "failed":
        return "finalize"
    return "prepare_exam"


def route_after_fanout(state: LearnLoopState) -> str:
    if state.get("status") == "failed":
        return "finalize"
    return "student_answer_batch"


def route_after_aggregate(state: LearnLoopState) -> str:
    if state.get("status") == "failed":
        return "finalize"
    return "judge_score"


def route_after_merge_questions(state: LearnLoopState) -> str:
    return route_after_fanout(state)


def exam_batch_router(state: LearnLoopState) -> str:
    if state.get("status") == "failed":
        return "finalize"
    done = state.get("exam_batch_index", 0)
    target = state.get("exam_batches_target", 1)
    if done < target:
        return "begin_persona_fanout"
    return "aggregate_qa"


def _learning_cfg() -> dict:
    return loop_cfg.get("learning", {})


def _min_macro_iter(state: LearnLoopState) -> int:
    return int(
        state.get("min_macro_iter")
        or _learning_cfg().get("min_macro_iter")
        or get_settings().min_macro_iter
    )


def _consecutive_pass_rounds(state: LearnLoopState) -> int:
    return int(
        state.get("consecutive_pass_rounds")
        or _learning_cfg().get("consecutive_pass_rounds")
        or get_settings().consecutive_pass_rounds
    )


def _meets_success_criteria(state: LearnLoopState) -> bool:
    """Require min macro rounds and consecutive passes at/above target."""
    settings = get_settings()
    accuracy = state.get("batch_accuracy", 0.0)
    macro = state.get("macro_iter", 0)
    target = state.get("target_accuracy", settings.target_accuracy)
    min_iter = _min_macro_iter(state)
    streak_need = _consecutive_pass_rounds(state)
    history = state.get("accuracy_history") or []

    if macro + 1 < min_iter:
        return False
    if accuracy < target:
        return False
    if len(history) < streak_need:
        return False
    recent = history[-streak_need:]
    return all(h >= target for h in recent)


def macro_router(state: LearnLoopState) -> str:
    if state.get("status") == "failed":
        return "finalize"

    settings = get_settings()
    macro = state.get("macro_iter", 0)
    max_iter = state.get("max_macro_iter", settings.max_macro_iter)

    if _meets_success_criteria(state):
        return "finalize"

    if macro >= max_iter:
        return "finalize"

    stagnation_rounds = loop_cfg.get("loop", {}).get("stagnation_rounds", 3)
    min_delta = loop_cfg.get("loop", {}).get("stagnation_min_delta", 0.01)
    history = state.get("accuracy_history") or []
    if len(history) >= stagnation_rounds:
        recent = history[-stagnation_rounds:]
        deltas = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
        if all(abs(d) < min_delta for d in deltas):
            return "finalize"

    return "refine_material"


def finalize_status(state: LearnLoopState) -> dict:
    """Set terminal status when graph reaches END via macro_router."""
    settings = get_settings()
    macro = state.get("macro_iter", 0)
    max_iter = state.get("max_macro_iter", settings.max_macro_iter)

    if state.get("status") == "failed":
        return {"phase": "done"}

    if _meets_success_criteria(state):
        return {"status": "success", "phase": "done"}

    history = state.get("accuracy_history") or []
    stagnation_rounds = loop_cfg.get("loop", {}).get("stagnation_rounds", 3)
    min_delta = loop_cfg.get("loop", {}).get("stagnation_min_delta", 0.01)
    if len(history) >= stagnation_rounds:
        recent = history[-stagnation_rounds:]
        deltas = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
        if all(abs(d) < min_delta for d in deltas):
            return {"status": "stagnated", "phase": "done"}

    if macro >= max_iter:
        return {"status": "max_iter_reached", "phase": "done"}

    return {"status": "max_iter_reached", "phase": "done"}
