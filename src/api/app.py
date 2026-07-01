"""FastAPI application for CogniForge Console."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.api.job_manager import job_manager
from src.api.models import (
    CrawlPreviewRequest,
    CrawlPreviewResponse,
    CrawlPreviewSeed,
    RunCreateResponse,
    RunParams,
    RunSummary,
)
from src.api.param_schema import get_param_schema
from src.api.run_service import list_summaries, load_summary, reconcile_stale_runs
from src.config import get_settings
from src.models.router import validate_api_keys
from src.tools.web_fetch import probe_crawl_urls

app = FastAPI(
    title="CogniForge Console API",
    description="Loop Engineering — web control plane",
    version="1.0.0",
)

# On startup, any run still marked 'running' belongs to a dead process.
reconcile_stale_runs()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # Must be False when origins is "*": the wildcard + credentials combo is
    # rejected by browsers. This API uses no cookie auth, so disable credentials.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    ok, err = validate_api_keys(get_settings())
    return {
        "status": "ok",
        "active_run": job_manager.active_run_id,
        "api_keys_ok": ok,
        "api_keys_hint": err if not ok else "",
    }


@app.get("/api/config/schema")
def config_schema():
    return get_param_schema()


@app.post("/api/crawl/preview", response_model=CrawlPreviewResponse)
def crawl_preview(body: CrawlPreviewRequest) -> CrawlPreviewResponse:
    """Probe seed URL(s) for discoverable page count without fetching leaf content."""
    urls = [u.strip() for u in body.urls if u.strip()]
    if not urls:
        raise HTTPException(400, "At least one URL required")
    raw = probe_crawl_urls(urls, crawl_enabled=body.crawl_enabled)
    seeds = [CrawlPreviewSeed.model_validate(s) for s in raw.get("seeds") or []]
    return CrawlPreviewResponse(
        seeds=seeds,
        discovered_total=int(raw.get("discovered_total") or 0),
        crawl_enabled=body.crawl_enabled,
    )


@app.get("/api/runs/active", response_model=RunSummary | None)
def get_active_run() -> RunSummary | None:
    run_id = job_manager.active_run_id
    if not run_id:
        return None
    return load_summary(run_id)


@app.get("/api/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    return list_summaries()


@app.get("/api/runs/{run_id}", response_model=RunSummary)
def get_run(run_id: str) -> RunSummary:
    summary = load_summary(run_id)
    if not summary:
        raise HTTPException(404, "Run not found")
    return summary


@app.post("/api/runs", response_model=RunCreateResponse)
def create_run(params: RunParams, label: str = "") -> RunCreateResponse:
    try:
        run_id, task_id = job_manager.start_run(params, label=params.label or label)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RunCreateResponse(run_id=run_id, task_id=task_id, status="running")


@app.post("/api/runs/{run_id}/stop")
def stop_run_endpoint(run_id: str) -> dict:
    summary = load_summary(run_id)
    if summary and summary.status in ("cancelled", "success", "failed", "stagnated", "max_iter_reached", "interrupted"):
        return {"ok": True, "message": "Run already finished"}
    if summary and summary.status == "cancelling":
        return {"ok": True, "message": "Stop already in progress"}
    if job_manager.active_run_id != run_id:
        if summary and summary.status != "running":
            return {"ok": True, "message": "Run already finished"}
        raise HTTPException(404, "Run is not active")
    job_manager.stop_active()
    updated = load_summary(run_id)
    return {
        "ok": True,
        "message": "Stop requested",
        "summary": updated.model_dump() if updated else None,
    }


@app.post("/api/runs/stop")
def stop_active_run() -> dict:
    if not job_manager.stop_active():
        raise HTTPException(404, "No active run")
    return {"ok": True, "run_id": job_manager.active_run_id}


async def _sse_generator(run_id: str):
    import queue as qmod

    bus = job_manager.get_bus(run_id)
    if not bus:
        summary = load_summary(run_id)
        if summary:
            yield f"data: {json.dumps({'type': 'snapshot', 'summary': summary.model_dump()}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': '_eof'})}\n\n"
        return

    event_q = bus.subscribe()
    loop = asyncio.get_event_loop()
    heartbeat = 0

    def _get():
        try:
            return event_q.get(timeout=15.0)
        except qmod.Empty:
            return None

    while True:
        event = await loop.run_in_executor(None, _get)
        if event is None:
            heartbeat += 1
            yield f": heartbeat {heartbeat}\n\n"
            continue
        if event.get("type") == "_eof":
            break
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        if event.get("type") == "run_end":
            break

    summary = load_summary(run_id)
    if summary:
        yield f"data: {json.dumps({'type': 'snapshot', 'summary': summary.model_dump()}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'type': '_eof'})}\n\n"


@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str):
    if not load_summary(run_id) and not job_manager.get_bus(run_id):
        raise HTTPException(404, "Run not found")
    return StreamingResponse(
        _sse_generator(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Mount built frontend if present
_web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
if _web_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_web_dist), html=True), name="static")
