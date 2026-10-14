"""The words that identify an installation, and the scrub of a text with them."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation


def terms_for(installation: Installation, *, target: Path | None = None) -> list[str]:
    raise NotImplementedError


def scrub_text(text: str, terms: list[str], *, replacement: str = "<redacted>") -> str:
    raise NotImplementedError
