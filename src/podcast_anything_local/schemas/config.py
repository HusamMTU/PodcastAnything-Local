"""Public application configuration schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AppConfigResponse(BaseModel):
    app_name: str
    default_web_extractor: str
    script_writer: str
    default_tts_provider: str
    default_style: str
    supported_web_extractors: list[str] = Field(default_factory=list)
    supported_tts_providers: list[str] = Field(default_factory=list)
