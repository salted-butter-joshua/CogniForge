"""Background job orchestration for web runs."""

from __future__ import annotations

import threading
import uuid
from typing import Any

from src.api.event_bus import RunEventBus
from src.api.models import RunParams, RunSummary
from src.api.run_service import execute_run, load_summary, mark_run_cancelling, stop_run
from src.config import get_settings
from src.models.router import validate_api_keys


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buses: dict[str, RunEventBus] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._active_run_id: str | None = None

    @property
    def active_run_id(self) -> str | None:
        with self._lock:
            return self._active_run_id

    def get_bus(self, run_id: str) -> RunEventBus | None:
        with self._lock:
            return self._buses.get(run_id)

    def _wait_for_thread(self, run_id: str, timeout: float = 120.0) -> bool:
        thread = self._threads.get(run_id)
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        return not (thread and thread.is_alive())

    def _clear_stale_active(self) -> None:
        """Drop active_run_id when the worker is gone or registry is terminal."""
        with self._lock:
            run_id = self._active_run_id
            if not run_id:
                return
            summary = load_summary(run_id)
            thread = self._threads.get(run_id)
            alive = bool(thread and thread.is_alive())
            if not alive:
                self._active_run_id = None
                return
            if summary and summary.status not in ("running", "cancelling"):
                self._active_run_id = None

    def _ensure_previous_run_stopped(self, timeout: float = 120.0) -> None:
        """Wait for a cancelling/stale worker before starting a new run."""
        with self._lock:
            prev_id = self._active_run_id
        if not prev_id:
            return

        summary = load_summary(prev_id)
        if summary and summary.status == "running":
            raise RuntimeError(
                f"Run {prev_id} is still active. Stop it first."
            )

        if not self._wait_for_thread(prev_id, timeout=timeout):
            raise RuntimeError(
                "Previous run is still stopping. Wait a moment and try again."
            )

        with self._lock:
            if self._active_run_id == prev_id:
                self._active_run_id = None

    def start_run(self, params: RunParams, label: str = "") -> tuple[str, str]:
        ok, err = validate_api_keys(get_settings())
        if not ok:
            raise RuntimeError(
                err
                or "LLM API key not configured. Copy .env.example to .env and set MINIMAX_API_KEY (or another provider key)."
            )

        self._clear_stale_active()
        self._ensure_previous_run_stopped()

        run_id = uuid.uuid4().hex[:12]
        if not params.task_id:
            params = params.model_copy(update={"task_id": f"web_{run_id[:8]}"})
        bus = RunEventBus(run_id)

        with self._lock:
            self._buses[run_id] = bus
            self._active_run_id = run_id

        def _worker() -> None:
            try:
                execute_run(run_id, params, bus, label=label)
            except Exception as exc:
                bus.publish({"type": "error", "message": str(exc)})
                bus.close({"status": "failed", "error_message": str(exc)})
            finally:
                with self._lock:
                    if self._active_run_id == run_id:
                        self._active_run_id = None

        thread = threading.Thread(target=_worker, name=f"cogniforge-{run_id}", daemon=True)
        with self._lock:
            self._threads[run_id] = thread
        thread.start()
        return run_id, params.task_id or f"web_{run_id[:8]}"

    def stop_active(self) -> bool:
        run_id = self.active_run_id
        if not run_id:
            return False

        summary = mark_run_cancelling(run_id)
        stop_run()
        bus = self.get_bus(run_id)
        if bus:
            payload: dict[str, Any] = {
                "type": "stop_requested",
                "message": "停止信号已发送",
            }
            if summary:
                payload["summary"] = summary.model_dump()
            bus.publish(payload)
        return True

    def wait_for_events(self, run_id: str, timeout: float = 30.0) -> Any:
        """Blocking get for SSE bridge (used from async generator)."""
        bus = self.get_bus(run_id)
        if not bus:
            summary = load_summary(run_id)
            if summary:
                return {"type": "_eof", "summary": summary.model_dump()}
            return {"type": "_eof"}
        q = bus.subscribe()
        try:
            return q.get(timeout=timeout)
        except Exception:
            return None


job_manager = JobManager()
