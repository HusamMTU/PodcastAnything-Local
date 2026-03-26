"""Rewrite provider interface."""

from __future__ import annotations

from typing import Protocol


class RewriteProviderError(RuntimeError):
    """Raised when script rewriting fails."""


class RewriteProvider(Protocol):
    def rewrite(
        self,
        *,
        source_text: str,
        title: str | None = None,
        style: str = "podcast",
        source_type: str | None = None,
        script_mode: str = "single",
        podcast_length: str = "medium",
    ) -> str:
        """Rewrite source material into a podcast script."""

    def generate_title(
        self,
        *,
        script_text: str,
        source_type: str | None = None,
        script_mode: str = "single",
    ) -> str:
        """Generate a concise podcast title from the script."""
