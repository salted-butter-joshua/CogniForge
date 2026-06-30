"""PersonaExam subgraph — private state (semi-isolation).

Field names must NOT overlap parent LearnLoopState keys (except final_questions
with reducer), or Send fan-out causes InvalidUpdateError.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class QuestionDraft(TypedDict, total=False):
    question: str
    evidence_refs: list[str]
    topic_tag: str
    weak_topic_focus: str
    persona_id: str
    persona_name: str


class PersonaExamState(TypedDict, total=False):
    # --- injected read-only from parent ---
    persona_id: str
    persona_name: str
    persona_style: str
    persona_prompt_hint: str
    material_snapshot: str
    chunks_snapshot: list[dict]
    weak_topics_snapshot: list[str]
    focus_hint: str
    chapter_scope_label: str
    allowed_evidence_ids: list[str]
    macro_iter_snapshot: int
    difficulty_level_snapshot: int
    curriculum_level_snapshot: int
    exam_batch_index_snapshot: int
    questions_target: int

    # --- private working memory ---
    retrieved_chunks: list[dict]
    search_queries: list[str]
    search_results: list[dict]
    draft_questions: list[QuestionDraft]
    validate_round: int
    max_validate_rounds: int
    validation_errors: list[str]
    validation_passed: bool

    # --- subgraph output (merged to parent via reducer) ---
    final_questions: list[QuestionDraft]

    persona_status: Literal["running", "failed"]
    persona_error: str
