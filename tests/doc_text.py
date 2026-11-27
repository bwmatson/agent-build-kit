"""Shared helpers for the tests that read the documents."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def squashed(text: str) -> str:
    """The text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(text.replace("`", "").split())
