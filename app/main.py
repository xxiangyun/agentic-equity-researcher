from __future__ import annotations

import asyncio
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.models import RunConfig, RunInput, RunMode
from app.pipeline import AutoResearchRunner
from app.storage import Storage

app = FastAPI(title=settings.app_name)
storage = Storage(settings.db_path)
runner = AutoResearchRunner(storage=storage, run_dir=settings.run_dir)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.get("/")
async def home(request: Request) -> JSONResponse:
    runs = storage.list_runs()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "runs": runs,
            "today": date.today().isoformat(),
            "defaults": settings,
        },
    )


@app.post("/runs")
async def create_run(
    request: Request,
    ticker: str = Form(...),
    mode: str = Form("review"),
    event_date: str = Form(""),
    peer_set: str = Form(""),
    prior_view: str = Form(""),
) -> RedirectResponse:
    clean_peers = [item.strip().upper() for item in peer_set.split(",") if item.strip()]
    parsed_mode = RunMode.PREVIEW if mode == "preview" else RunMode.REVIEW
    resolved_event_date = date.fromisoformat(event_date) if event_date else date.today()
    payload = RunInput(
        ticker=ticker.strip().upper(),
        mode=parsed_mode,
        event_date=resolved_event_date,
        peer_set=clean_peers,
        prior_view=prior_view.strip() or None,
    )
    config = RunConfig(
        max_iterations=settings.max_iterations,
        target_score=settings.target_score,
        min_improvement=settings.min_improvement,
        patience=settings.patience,
    )
    run_id = uuid.uuid4().hex[:12]
    storage.create_run(run_id=run_id, payload=payload, config=config)
    asyncio.create_task(runner.execute(run_id=run_id, run_input=payload, config=config))
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.get("/runs/{run_id}")
async def run_detail(request: Request, run_id: str) -> JSONResponse:
    run = storage.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    iterations = storage.list_iterations(run_id)
    featured = None
    if iterations:
        featured = next((item for item in iterations if item.index == run.best_iteration), iterations[-1])
    return templates.TemplateResponse(
        request=request,
        name="run.html",
        context={
            "request": request,
            "run": run,
            "iterations": iterations,
            "featured": featured,
        },
    )


@app.get("/api/runs/{run_id}")
async def run_status(run_id: str) -> JSONResponse:
    run = storage.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    iterations = storage.list_iterations(run_id)
    payload = {
        "run_id": run.run_id,
        "state": run.state,
        "best_iteration": run.best_iteration,
        "best_score": run.best_score,
        "stop_reason": run.stop_reason,
        "summary": run.summary,
        "iterations": [item.model_dump(mode="json") for item in iterations],
    }
    if iterations:
        featured = next((item for item in iterations if item.index == run.best_iteration), iterations[-1])
        payload["featured"] = featured.model_dump(mode="json")
    return JSONResponse(payload)
