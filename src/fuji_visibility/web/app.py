"""FastAPI application factory for Fuji Visibility."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..services import DashboardService
from .i18n import localized_datetime
from .routes import register_routes
from .settings import DashboardSettings

WEB_ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_ROOT / "templates"
STATIC_DIR = WEB_ROOT / "static"


def _number(value: object, digits: int = 0) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.{digits}f}"


def _percent(value: object, digits: int = 0) -> str:
    rendered = _number(value, digits)
    return "—" if rendered == "—" else f"{rendered}%"


def _kilometers(value: object, digits: int = 1) -> str:
    rendered = _number(value, digits)
    return "—" if rendered == "—" else f"{rendered} km"


def _local_datetime(value: object) -> str:
    if not value:
        return "—"
    return localized_datetime(value)  # type: ignore[arg-type]


def create_app(settings: DashboardSettings | None = None) -> FastAPI:
    app = FastAPI(
        title="富士山能见度",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["number"] = _number
    templates.env.filters["percent"] = _percent
    templates.env.filters["kilometers"] = _kilometers
    templates.env.filters["local_datetime"] = _local_datetime
    app.state.dashboard_service = DashboardService(settings)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    register_routes(app, templates)
    return app


app = create_app()
