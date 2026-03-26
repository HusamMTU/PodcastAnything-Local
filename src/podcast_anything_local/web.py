"""Built-in web UI routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_WEB_ASSETS_DIR = Path(__file__).resolve().parent / "web_assets"

router = APIRouter(include_in_schema=False)


@router.get("/")
def index() -> FileResponse:
    return FileResponse(_WEB_ASSETS_DIR / "index.html", media_type="text/html")


def mount_web_ui(app: FastAPI) -> None:
    app.mount("/ui-assets", StaticFiles(directory=str(_WEB_ASSETS_DIR)), name="ui-assets")
    app.include_router(router)
