"""FastAPI app factory + static UI mount.

Entrypoint for `uvicorn app:app --reload` from the project root.

The `aegis_discovery` package lives under `src/`, so we make sure that
directory is on `sys.path` before importing from it. This lets the file run
directly without requiring callers to set `PYTHONPATH=src`.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from aegis_discovery.api.routes import router as api_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Aegis Discovery",
        version="0.1.0",
        description=(
            "Normalize partial agent signals from runtime, IAM, repo scans, and "
            "SaaS audits into canonical Agent records with risk score, evidence, "
            "and recommended policy."
        ),
    )

    # CORS open for local dev / the single-page UI.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    index_html = PROJECT_ROOT / "web" / "index.html"

    @app.get("/", include_in_schema=False)
    def root_index() -> FileResponse:
        return FileResponse(index_html)

    @app.get("/index.html", include_in_schema=False)
    def index_html_route() -> FileResponse:
        return FileResponse(index_html)

    return app


app = create_app()
