"""Pydantic models for CogniForge Web API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RunParams(BaseModel):
    urls: list[str] = Field(..., min_length=1)
    goal: str = "全面掌握所提供网页的核心知识"
    task_id: str | None = None
    thread_id: str | None = None
    crawl_enabled: bool = True

    # Dev-friendly defaults — faster iteration; use "production" preset for full runs
    target_accuracy: float = Field(0.85, ge=0.5, le=1.0)
    min_macro_iter: int = Field(1, ge=1, le=100)
    max_macro_iter: int = Field(1000, ge=1, le=10000)
    consecutive_pass_rounds: int = Field(1, ge=1, le=20)

    first_round_total_questions: int = Field(50, ge=10, le=500)
    focused_round_questions: int = Field(30, ge=10, le=300)
    questions_per_persona: int = Field(5, ge=1, le=30)

    closed_book_exam: bool = True
    student_notes_max_chars: int = Field(2500, ge=500, le=20000)
    student_notes_study_max_chars: int = Field(8000, ge=1000, le=50000)
    curriculum_pages_per_round: int = Field(12, ge=1, le=200)
    judge_evidence_only: bool = True
    evidence_cap_score: float = Field(0.78, ge=0.5, le=1.0)

    crawl_max_pages: int = Field(20, ge=1, le=500)
    crawl_include_images: bool = False
    judge_batch_size: int = Field(20, ge=1, le=50)
    student_answer_batch_size: int = Field(20, ge=1, le=50)
    max_validate_rounds: int = Field(1, ge=1, le=5)
    label: str = ""


class RunCreateResponse(BaseModel):
    run_id: str
    task_id: str
    status: str


class RunSummary(BaseModel):
    run_id: str
    task_id: str
    status: str
    urls: list[str]
    goal: str
    params: dict[str, Any]
    macro_iter: int = 0
    batch_accuracy: float = 0.0
    accuracy_history: list[float] = Field(default_factory=list)
    weak_topics: list[str] = Field(default_factory=list)
    phase: str = ""
    error_message: str = ""
    created_at: float = 0.0
    finished_at: float | None = None
    label: str = ""


class ParamFieldSchema(BaseModel):
    key: str
    label: str
    description: str
    type: Literal["float", "int", "bool", "text"]
    default: Any
    min: float | None = None
    max: float | None = None
    group: str


class ParamPresetSchema(BaseModel):
    id: str
    label: str
    description: str
    values: dict[str, Any]


class ParamSchemaResponse(BaseModel):
    groups: list[str]
    fields: list[ParamFieldSchema]
    presets: list[ParamPresetSchema] = Field(default_factory=list)
    default_preset: str = "development"
