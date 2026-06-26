"""Compile PersonaExam subgraph."""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, StateGraph

from src.graph.subgraphs.persona_exam.nodes import (
    finalize_questions,
    fuse_questions,
    inject_snapshot,
    rag_retrieve,
    validate_questions,
    validate_router,
    web_search,
)
from src.graph.subgraphs.persona_exam.state import PersonaExamState


def build_persona_exam_graph() -> StateGraph:
    graph = StateGraph(PersonaExamState)

    graph.add_node("inject_snapshot", inject_snapshot)
    graph.add_node("rag_retrieve", rag_retrieve)
    graph.add_node("web_search", web_search)
    graph.add_node("fuse_questions", fuse_questions)
    graph.add_node("validate_questions", validate_questions)
    graph.add_node("finalize_questions", finalize_questions)

    graph.set_entry_point("inject_snapshot")
    graph.add_edge("inject_snapshot", "rag_retrieve")
    graph.add_edge("rag_retrieve", "web_search")
    graph.add_edge("web_search", "fuse_questions")
    graph.add_edge("fuse_questions", "validate_questions")
    graph.add_conditional_edges(
        "validate_questions",
        validate_router,
        {
            "finalize_questions": "finalize_questions",
            "fuse_questions": "fuse_questions",
            END: END,
        },
    )
    graph.add_edge("finalize_questions", END)
    return graph


@lru_cache
def get_compiled_persona_exam():
    return build_persona_exam_graph().compile()
