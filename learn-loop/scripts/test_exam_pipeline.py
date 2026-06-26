"""Integration test: Send fan-out -> merge -> student_answer."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.config import get_settings, load_personas
from src.graph.nodes.exam import (
    build_persona_exam_input,
    dispatch_persona_exam,
    merge_persona_questions,
    student_answer_batch,
)
from src.graph.routers import route_after_merge_questions
from src.graph.state import LearnLoopState


def mock_persona_exam(state: dict) -> dict:
    pid = state.get("persona_id", "?")
    n = state.get("questions_target", 2)
    qs = [
        {
            "question": f"Q-{pid}-{i}",
            "persona_id": pid,
            "persona_name": state.get("persona_name", pid),
            "evidence_refs": ["chunk_1"],
            "topic_tag": "test",
        }
        for i in range(n)
    ]
    return {"final_questions": qs}


def main():
    g = StateGraph(LearnLoopState)
    g.add_node("persona_exam", mock_persona_exam)
    g.add_node("merge", merge_persona_questions)
    g.add_node("answer", student_answer_batch)
    g.add_conditional_edges(START, dispatch_persona_exam, ["persona_exam"])
    g.add_edge("persona_exam", "merge")
    g.add_conditional_edges(
        "merge",
        route_after_merge_questions,
        {"student_answer_batch": "answer", "finalize": END},
    )
    g.add_edge("answer", END)
    app = g.compile()

    settings = get_settings()
    init = {
        "task_id": "pipe-test",
        "study_material": "test material",
        "study_notes": "notes",
        "raw_chunks": [{"id": "chunk_1", "title": "t", "content": "c"}],
        "macro_iter": 0,
        "exam_batch_index": 0,
        "exam_batches_target": 1,
        "questions_per_persona": 2,
        "final_questions": [],
        "current_batch_questions": [],
        "status": "running",
    }
    out = app.invoke(init)
    print("status:", out.get("status"))
    print("final_questions:", len(out.get("final_questions") or []))
    print("current_batch_questions:", len(out.get("current_batch_questions") or []))
    print("current_batch_qa:", len(out.get("current_batch_qa") or []))
    print("exam_batch_index:", out.get("exam_batch_index"))


if __name__ == "__main__":
    main()
