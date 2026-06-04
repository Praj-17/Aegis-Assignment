"""HTTP endpoints. Handlers stay thin; real work lives in `pipeline.py`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from aegis_discovery.api.dependencies import get_app_settings, get_repository
from aegis_discovery.config.settings import Settings
from aegis_discovery.graph.builder import build_graph
from aegis_discovery.ingestion.ingestor import IngestionError
from aegis_discovery.pipeline import ingest_and_process, run_full_pipeline
from aegis_discovery.schemas import Agent, AgentGraph, IngestResponse
from aegis_discovery.storage.database import Repository


router = APIRouter()


@router.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/metadata", tags=["meta"])
def metadata(settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    return {
        "app": settings.app.model_dump(),
        "correlation_window_seconds": settings.correlation.time_window_seconds,
        "policies": [p.model_dump() for p in settings.policies.catalog],
        "external_llm_destinations": settings.risk.external_llm_destinations,
    }


@router.post("/events", response_model=IngestResponse, tags=["pipeline"])
def post_events(
    payload: Any = Body(...),
    repo: Repository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> IngestResponse:
    try:
        agents = ingest_and_process(repo, settings, payload)
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IngestResponse(
        accepted_events=len(repo.list_events()),
        new_or_updated_agents=len(agents),
        agents=agents,
    )


@router.post("/events/upload", response_model=IngestResponse, tags=["pipeline"])
async def upload_events(
    file: UploadFile,
    repo: Repository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> IngestResponse:
    import json

    body = await file.read()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    try:
        agents = ingest_and_process(repo, settings, payload)
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IngestResponse(
        accepted_events=len(repo.list_events()),
        new_or_updated_agents=len(agents),
        agents=agents,
    )


@router.post("/pipeline/run", response_model=list[Agent], tags=["pipeline"])
def run_pipeline_endpoint(
    repo: Repository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> list[Agent]:
    return run_full_pipeline(repo, settings)


@router.delete("/events", tags=["pipeline"])
def reset_events(repo: Repository = Depends(get_repository)) -> JSONResponse:
    repo.clear()
    return JSONResponse({"status": "cleared"})


@router.get("/agents", response_model=list[Agent], tags=["agents"])
def list_agents(repo: Repository = Depends(get_repository)) -> list[Agent]:
    return repo.list_agents()


@router.get("/agents/{agent_id}", response_model=Agent, tags=["agents"])
def get_agent(
    agent_id: str,
    repo: Repository = Depends(get_repository),
) -> Agent:
    agent = repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.get("/agents/{agent_id}/graph", response_model=AgentGraph, tags=["agents"])
def get_agent_graph(
    agent_id: str,
    repo: Repository = Depends(get_repository),
) -> AgentGraph:
    agent = repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return build_graph(agent)
