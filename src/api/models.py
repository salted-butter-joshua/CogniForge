"""Pydantic models for CogniForge Web API."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class RunParams(BaseModel):
    urls: List[str] = Field(..., min_length=1)
    goal: str = "全面掌握所提供网页的核心知识"
    task_id: Optional[str] = None
    thread_id: Optional[str] = None
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
    student_notes_max_chars: int = Field(6000, ge=500, le=20000)
    student_notes_study_max_chars: int = Field(8000, ge=1000, le=50000)
    curriculum_pages_per_round: int = Field(12, ge=1, le=200)
    judge_evidence_only: bool = True
    evidence_cap_score: float = Field(0.88, ge=0.5, le=1.0)
    judge_semantic_lenient: bool = True
    judge_temperature: float = Field(0.2, ge=0.0, le=1.5)
    student_exam_temperature: float = Field(0.25, ge=0.0, le=1.5)

    # Chapter mastery mode (default on; set use_chapter_mastery=false for legacy page mode)
    use_chapter_mastery: bool = True
    chapter_mastery_accuracy: float = Field(0.98, ge=0.5, le=1.0)
    short_term_notes_max_chars: int = Field(6000, ge=500, le=50000)
    long_term_notes_max_chars: int = Field(6000, ge=1000, le=50000)
    chapter_review_ratio: float = Field(0.1, ge=0.0, le=0.5)
    exam_long_term_ratio: float = Field(0.50, ge=0.2, le=0.95)
    exam_working_layer_ratio: float = Field(0.45, ge=0.0, le=0.5)
    reinforce_pool_ratio: float = Field(0.5, ge=0.1, le=0.8)

    crawl_max_pages: int = Field(0, ge=0, le=500)
    crawl_include_images: bool = False
    judge_batch_size: int = Field(20, ge=1, le=50)
    student_answer_batch_size: int = Field(20, ge=1, le=50)
    max_validate_rounds: int = Field(1, ge=1, le=5)
    label: str = ""


class RunCreateResponse(BaseModel):
    run_id: str
    task_id: str
    status: str


class CrawlPreviewRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1)
    crawl_enabled: bool = True


class CrawlPreviewSeed(BaseModel):
    url: str
    discovered_total: int = 1
    curriculum_mode: str = "exact_urls"
    parts: List[str] = Field(default_factory=list)
    entries_preview: List[Dict[str, Any]] = Field(default_factory=list)
    error: str = ""


class CrawlPreviewResponse(BaseModel):
    seeds: List[CrawlPreviewSeed]
    discovered_total: int
    crawl_enabled: bool


class RunSummary(BaseModel):
    run_id: str
    task_id: str
    status: str
    urls: List[str]
    goal: str
    params: Dict[str, Any]
    macro_iter: int = 0
    batch_accuracy: float = 0.0
    current_questions: int = 0
    token_total: int = 0
    token_input: int = 0
    token_output: int = 0
    token_calls: int = 0
    tokens_by_step: Dict[str, int] = Field(default_factory=dict)
    accuracy_history: List[float] = Field(default_factory=list)
    round_records: List[dict] = Field(default_factory=list)
    chapter_mastery: Dict[str, Any] = Field(default_factory=dict)
    chapter_progress: List[dict] = Field(default_factory=list)
    current_chapter_index: int = 0
    learning_mode: str = "chapter_mastery"
    weak_topics: List[str] = Field(default_factory=list)
    phase: str = ""
    error_message: str = ""
    created_at: float = 0.0
    finished_at: Optional[float] = None
    label: str = ""


class ParamFieldSchema(BaseModel):
    key: str
    label: str
    description: str
    type: Literal["float", "int", "bool", "text"]
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    group: str
    visible_when_key: Optional[str] = None
    visible_when_equals: Any = None


class ParamPresetSchema(BaseModel):
    id: str
    label: str
    description: str
    values: Dict[str, Any]


class ParamSchemaResponse(BaseModel):
    groups: List[str]
    fields: List[ParamFieldSchema]
    presets: List[ParamPresetSchema] = Field(default_factory=list)
    default_preset: str = "development"
