"""Small API schemas for predictable browser-facing errors and refresh results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    error: str
    message: str


class RefreshResponse(BaseModel):
    status: str
    message: str
    snapshot_ids: list[int] = Field(default_factory=list)
    successful_models: list[str] = Field(default_factory=list)
    failures: list[dict[str, str]] = Field(default_factory=list)
