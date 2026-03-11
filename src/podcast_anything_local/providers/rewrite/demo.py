"""Development rewrite provider that produces a deterministic sample script."""

from __future__ import annotations

import re


class DemoRewriteProvider:
    """Generate a readable script without relying on external models."""

    def rewrite(
        self,
        *,
        source_text: str,
        title: str | None = None,
        style: str = "podcast",
        source_type: str | None = None,
        script_mode: str = "single",
    ) -> str:
        cleaned = re.sub(r"\s+", " ", source_text).strip()
        excerpt = cleaned[:1200]
        if script_mode == "duo":
            return self._rewrite_duo(excerpt=excerpt, title=title, style=style, source_type=source_type)
        return self._rewrite_single(
            excerpt=excerpt,
            title=title,
            style=style,
            source_type=source_type,
        )

    def generate_title(
        self,
        *,
        script_text: str,
        source_type: str | None = None,
        script_mode: str = "single",
    ) -> str:
        if script_mode == "duo":
            return "Local Podcast Conversation"
        return "Local Podcast Draft"

    def _rewrite_single(
        self,
        *,
        excerpt: str,
        title: str | None,
        style: str,
        source_type: str | None,
    ) -> str:
        label = title or "today's topic"
        source_label = source_type or "source"
        return (
            f"Welcome back. Today we're digging into {label}.\n\n"
            f"This is a {style} recap built from a {source_label} input. "
            "I'll walk through the main ideas, what matters, and the practical takeaway.\n\n"
            f"Here is the core material in plain language: {excerpt}\n\n"
            "That gives us the big picture. The next step is turning this into a stronger, "
            "provider-backed script once the rewrite model is configured.\n\n"
            "Thanks for listening."
        )

    def _rewrite_duo(
        self,
        *,
        excerpt: str,
        title: str | None,
        style: str,
        source_type: str | None,
    ) -> str:
        label = title or "today's topic"
        source_label = source_type or "source"
        return "\n".join(
            [
                f"HOST_A: Welcome back. Today we're unpacking {label}.",
                (
                    f"HOST_B: This first pass uses the demo rewrite provider, but it still "
                    f"keeps the {style} structure and works from the {source_label} input."
                ),
                f"HOST_A: Here is the condensed source material: {excerpt}",
                (
                    "HOST_B: The main goal of this scaffold is proving the pipeline shape, "
                    "job lifecycle, and artifact flow before the real LLM provider is wired in."
                ),
                "HOST_A: That is enough context for a future UI and provider integration layer.",
                "HOST_B: Thanks for listening.",
            ]
        )
