"""Build and compile the Learn Loop LangGraph."""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.config import get_settings
from src.graph.node_logging import logged_node
from src.logging_config import get_loop_logger
from src.graph.nodes.aggregate import aggregate_qa
from src.graph.nodes.exam import (
    begin_persona_fanout,
    fanout_persona_exams,
    student_answer_batch,
)
from src.graph.nodes.judge import judge_score, observer_analyze
from src.graph.nodes.material import (
    fetch_pages,
    generate_material,
    prepare_exam,
    refine_material,
    student_study,
)
from src.graph.routers import (
    exam_batch_router,
    finalize_status,
    macro_router,
    route_after_fetch,
    route_after_material,
    route_after_fanout,
    route_after_aggregate,
    route_after_study,
)
from src.graph.state import LearnLoopState

logger = get_loop_logger()


_cm_holder: list = []


def _get_checkpointer():
    settings = get_settings()
    try:
        from langgraph.checkpoint.redis import RedisSaver

        cm = RedisSaver.from_conn_string(settings.redis_url)
        checkpointer = cm.__enter__()
        try:
            checkpointer.setup()
        except Exception as setup_exc:
            # Plain Redis without RediSearch/Redis Stack cannot run setup()
            if "FT._LIST" in str(setup_exc) or "unknown command" in str(setup_exc):
                logger.warning(
                    "checkpoint=MemorySaver | reason=Redis lacks RediSearch | url=%s",
                    settings.redis_url,
                )
                cm.__exit__(None, None, None)
                return MemorySaver()
            raise
        _cm_holder.append(cm)
        logger.info("checkpoint=Redis | url=%s", settings.redis_url)
        return checkpointer
    except Exception as exc:
        logger.warning("checkpoint=MemorySaver | reason=%s", exc)
        return MemorySaver()


def build_graph():
    graph = StateGraph(LearnLoopState)

    graph.add_node("fetch_pages", logged_node("fetch_pages")(fetch_pages))
    graph.add_node("generate_material", logged_node("generate_material")(generate_material))
    graph.add_node("student_study", logged_node("student_study")(student_study))
    graph.add_node("prepare_exam", logged_node("prepare_exam")(prepare_exam))
    graph.add_node("begin_persona_fanout", logged_node("begin_persona_fanout")(begin_persona_fanout))
    graph.add_node("fanout_persona_exams", logged_node("fanout_persona_exams")(fanout_persona_exams))
    graph.add_node("student_answer_batch", logged_node("student_answer_batch")(student_answer_batch))
    graph.add_node("aggregate_qa", logged_node("aggregate_qa")(aggregate_qa))
    graph.add_node("judge_score", logged_node("judge_score")(judge_score))
    graph.add_node("observer_analyze", logged_node("observer_analyze")(observer_analyze))
    graph.add_node("refine_material", logged_node("refine_material")(refine_material))
    graph.add_node("finalize", logged_node("finalize")(finalize_status))

    graph.set_entry_point("fetch_pages")

    graph.add_conditional_edges(
        "fetch_pages",
        route_after_fetch,
        {"generate_material": "generate_material", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "generate_material",
        route_after_material,
        {"student_study": "student_study", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "student_study",
        route_after_study,
        {"prepare_exam": "prepare_exam", "finalize": "finalize"},
    )

    graph.add_edge("prepare_exam", "fanout_persona_exams")
    graph.add_conditional_edges(
        "fanout_persona_exams",
        route_after_fanout,
        {"student_answer_batch": "student_answer_batch", "finalize": "finalize"},
    )

    graph.add_conditional_edges(
        "student_answer_batch",
        exam_batch_router,
        {
            "begin_persona_fanout": "begin_persona_fanout",
            "aggregate_qa": "aggregate_qa",
            "finalize": "finalize",
        },
    )
    graph.add_edge("begin_persona_fanout", "fanout_persona_exams")

    graph.add_conditional_edges(
        "aggregate_qa",
        route_after_aggregate,
        {"judge_score": "judge_score", "finalize": "finalize"},
    )
    graph.add_edge("judge_score", "observer_analyze")
    graph.add_conditional_edges(
        "observer_analyze",
        macro_router,
        {"refine_material": "refine_material", "finalize": "finalize"},
    )

    graph.add_edge("refine_material", "student_study")
    graph.add_edge("finalize", END)

    checkpointer = _get_checkpointer()
    return graph.compile(checkpointer=checkpointer)
