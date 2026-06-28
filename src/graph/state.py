"""LangGraph state definitions."""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict


class QuestionItem(TypedDict, total=False):
    """Question produced by PersonaExam subgraph (no answer yet)."""

    question: str
    evidence_refs: list[str]
    topic_tag: str
    weak_topic_focus: str
    persona_id: str
    persona_name: str


class ExamQA(TypedDict, total=False):
    qa_id: str
    macro_iter: int
    exam_batch: int
    persona_id: str
    persona_name: str
    question: str
    answer: str
    evidence_refs: list[str]
    weak_topic_focus: str
    judge_score: float
    judge_reason: str
    is_correct: bool
    topic_tag: str


class ObservationRecord(TypedDict, total=False):
    """Observer analysis of student study notes (internal report, not fed to student)."""

    macro_iter: int
    learning_patterns: str
    knowledge_framework: str
    note_style_observations: str
    recurring_blind_spots: str
    observer_summary: str


def merge_qa_lists(left: list, right: list) -> list:
    return left + right


class LearnLoopState(TypedDict, total=False):
    task_id: str
    urls: list[str]
    goal: str
    crawl_enabled: bool

    raw_chunks: list[dict]
    study_material: str
    knowledge_cards: list[dict]
    study_notes: str

    macro_iter: Annotated[int, operator.add]
    curriculum_level: int
    difficulty_level: int
    curriculum_advanced: bool
    max_macro_iter: int
    min_macro_iter: int
    consecutive_pass_rounds: int
    target_accuracy: float

    exam_batch_index: int
    exam_batches_target: int
    questions_per_persona: int

    # Subgraph parallel merge (Send fan-in) → parent answers
    final_questions: Annotated[list[QuestionItem], merge_qa_lists]
    current_batch_questions: list[QuestionItem]
    current_batch_qa: Annotated[list[ExamQA], merge_qa_lists]
    all_qa_archive: Annotated[list[ExamQA], merge_qa_lists]

    batch_accuracy: float
    accuracy_history: list[float]
    round_records: Annotated[list[dict], merge_qa_lists]
    weak_topics: list[str]
    judge_report: str

    observations: Annotated[list[ObservationRecord], operator.add]
    latest_observation: ObservationRecord

    phase: str
    status: Literal["running", "success", "max_iter_reached", "stagnated", "failed"]
    error_message: str
