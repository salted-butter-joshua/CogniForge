"""Tests for web job stop / restart orchestration."""

from __future__ import annotations

import time

import pytest

from src.api import run_service
from src.api.models import RunSummary


@pytest.fixture
def registry_dir(tmp_path, monkeypatch):
    reg = tmp_path / ".registry"
    reg.mkdir()
    monkeypatch.setattr(run_service, "_registry_dir", lambda: reg)
    return reg


def _save(run_id: str, status: str) -> RunSummary:
    summary = RunSummary(
        run_id=run_id,
        task_id=f"web_{run_id[:8]}",
        status=status,
        urls=["https://example.com"],
        goal="test",
        params={},
        macro_iter=0,
        batch_accuracy=0.0,
        accuracy_history=[],
        weak_topics=[],
        phase="",
        error_message="",
        created_at=time.time(),
        label="test",
    )
    run_service._save_summary(summary)
    return summary


def test_mark_run_cancelling(registry_dir):
    _save("abc123", "running")
    updated = run_service.mark_run_cancelling("abc123")
    assert updated is not None
    assert updated.status == "cancelling"
    again = run_service.mark_run_cancelling("abc123")
    assert again is not None
    assert again.status == "cancelling"
