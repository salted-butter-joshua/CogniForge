"""Application settings loaded from environment and YAML."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT_DIR / "config"

LlmRouter = Literal["litellm", "openrouter", "anthropic", "openai", "minimax"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Router
    llm_router: LlmRouter = Field(default="litellm", alias="LLM_ROUTER")
    model_preset: str = Field(default="minimax_default", alias="MODEL_PRESET")

    # API keys
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    minimax_api_key: str = Field(default="", alias="MINIMAX_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # Base URLs
    minimax_base_url: str = Field(
        default="https://api.minimaxi.com/v1", alias="MINIMAX_BASE_URL"
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", alias="OPENAI_BASE_URL"
    )

    # Per-role models (used when MODEL_PRESET=custom)
    student_model: str = Field(default="minimax/MiniMax-M2.7", alias="STUDENT_MODEL")
    persona_model: str = Field(
        default="minimax/MiniMax-M2.7-highspeed", alias="PERSONA_MODEL"
    )
    judge_model: str = Field(default="minimax/MiniMax-M3", alias="JUDGE_MODEL")
    observer_model: str = Field(default="minimax/MiniMax-M3", alias="OBSERVER_MODEL")
    material_model: str = Field(default="minimax/MiniMax-M2.7", alias="MATERIAL_MODEL")

    max_macro_iter: int = Field(default=1000, alias="MAX_MACRO_ITER")
    target_accuracy: float = Field(default=0.95, alias="TARGET_ACCURACY")
    questions_per_persona: int = Field(default=10, alias="QUESTIONS_PER_PERSONA")
    first_round_total_questions: int = Field(
        default=150, alias="FIRST_ROUND_TOTAL_QUESTIONS"
    )
    focused_round_questions: int = Field(default=50, alias="FOCUSED_ROUND_QUESTIONS")
    judge_batch_size: int = Field(default=10, alias="JUDGE_BATCH_SIZE")
    student_answer_batch_size: int = Field(default=10, alias="STUDENT_ANSWER_BATCH_SIZE")

    min_macro_iter: int = Field(default=3, alias="MIN_MACRO_ITER")
    consecutive_pass_rounds: int = Field(default=2, alias="CONSECUTIVE_PASS_ROUNDS")
    closed_book_exam: bool = Field(default=True, alias="CLOSED_BOOK_EXAM")
    student_notes_max_chars: int = Field(default=6000, alias="STUDENT_NOTES_MAX_CHARS")
    student_notes_study_max_chars: int = Field(default=8000, alias="STUDENT_NOTES_STUDY_MAX_CHARS")
    student_material_study_max_chars: int = Field(
        default=6000, alias="STUDENT_MATERIAL_STUDY_MAX_CHARS"
    )
    material_context_max_chars: int = Field(
        default=24000, alias="MATERIAL_CONTEXT_MAX_CHARS"
    )
    curriculum_pages_per_round: int = Field(default=12, alias="CURRICULUM_PAGES_PER_ROUND")
    curriculum_advance_accuracy: float = Field(
        default=0.85, alias="CURRICULUM_ADVANCE_ACCURACY"
    )
    difficulty_advance_accuracy: float = Field(
        default=0.90, alias="DIFFICULTY_ADVANCE_ACCURACY"
    )
    difficulty_retreat_accuracy: float = Field(
        default=0.50, alias="DIFFICULTY_RETREAT_ACCURACY"
    )
    judge_evidence_only: bool = Field(default=True, alias="JUDGE_EVIDENCE_ONLY")
    judge_evidence_max_chars: int = Field(default=12000, alias="JUDGE_EVIDENCE_MAX_CHARS")
    evidence_cap_score: float = Field(default=0.88, alias="EVIDENCE_CAP_SCORE")
    judge_semantic_lenient: bool = Field(default=True, alias="JUDGE_SEMANTIC_LENIENT")
    judge_temperature: float = Field(default=0.2, alias="JUDGE_TEMPERATURE")
    student_exam_temperature: float = Field(default=0.25, alias="STUDENT_EXAM_TEMPERATURE")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    output_dir: str = Field(default="./outputs", alias="OUTPUT_DIR")

    single_llm_timeout: int = Field(default=120, alias="SINGLE_LLM_TIMEOUT")
    exam_batch_timeout: int = Field(default=600, alias="EXAM_BATCH_TIMEOUT")
    macro_iter_timeout: int = Field(default=3600, alias="MACRO_ITER_TIMEOUT")

    crawl_enabled: bool = Field(default=True, alias="CRAWL_ENABLED")
    crawl_max_pages: int = Field(default=0, alias="CRAWL_MAX_PAGES")
    crawl_include_images: bool = Field(default=True, alias="CRAWL_INCLUDE_IMAGES")

    # Chapter mastery learning mode
    learning_mode: str = Field(default="chapter_mastery", alias="LEARNING_MODE")
    chapter_mastery_accuracy: float = Field(
        default=0.98, alias="CHAPTER_MASTERY_ACCURACY"
    )
    chapter_max_chars: int = Field(default=8000, alias="CHAPTER_MAX_CHARS")
    long_term_notes_max_chars: int = Field(
        default=6000, alias="LONG_TERM_NOTES_MAX_CHARS"
    )
    short_term_notes_max_chars: int = Field(
        default=6000, alias="SHORT_TERM_NOTES_MAX_CHARS"
    )
    chapter_review_ratio: float = Field(default=0.1, alias="CHAPTER_REVIEW_RATIO")
    reinforce_pool_ratio: float = Field(default=0.5, alias="REINFORCE_POOL_RATIO")
    # Closed-book exam memory budget split (must sum <= 1.0)
    exam_long_term_ratio: float = Field(default=0.50, alias="EXAM_LONG_TERM_RATIO")
    exam_working_layer_ratio: float = Field(
        default=0.45, alias="EXAM_WORKING_LAYER_RATIO"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml_config(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_personas() -> list[dict]:
    data = load_yaml_config("personas.yaml")
    return data.get("personas", [])


def load_rubric() -> dict:
    return load_yaml_config("rubric.yaml")


def load_loop_config() -> dict:
    return load_yaml_config("settings.yaml")


def load_models_config() -> dict:
    return load_yaml_config("models.yaml")


def ensure_output_dir(task_id: str) -> Path:
    base = Path(get_settings().output_dir)
    task_dir = base / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir
