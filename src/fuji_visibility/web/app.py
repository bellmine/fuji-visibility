"""FastAPI application factory for Fuji Visibility."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..services import DashboardService
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
    try:
        from ..time_utils import display_datetime, parse_datetime

        return display_datetime(parse_datetime(value) if isinstance(value, str) else value)
    except (AttributeError, TypeError, ValueError):
        return str(value)


def create_app(settings: DashboardSettings | None = None) -> FastAPI:
    app = FastAPI(
        title="Mt. Fuji Visibility",
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
