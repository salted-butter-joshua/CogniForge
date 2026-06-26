"""Minimal LangGraph Send + reducer merge test."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from src.graph.state import LearnLoopState, merge_qa_lists
from typing import Annotated


def dispatch(state: LearnLoopState):
    return [Send("worker", {"persona_id": f"P{i}"}) for i in range(3)]


def worker(state: dict):
    pid = state["persona_id"]
    return {"final_questions": [{"question": f"q-{pid}", "persona_id": pid}]}


def merge(state: LearnLoopState):
    qs = state.get("final_questions") or []
    print("MERGE final_questions count:", len(qs))
    for q in qs:
        print(" ", q)
    return {"current_batch_questions": qs}


def main():
    g = StateGraph(LearnLoopState)
    g.add_node("worker", worker)
    g.add_node("merge", merge)
    g.add_conditional_edges(START, dispatch, ["worker"])
    g.add_edge("worker", "merge")
    g.add_edge("merge", END)
    app = g.compile()
    out = app.invoke({"task_id": "t", "final_questions": []})
    print("OUT current_batch_questions:", len(out.get("current_batch_questions") or []))


if __name__ == "__main__":
    main()
