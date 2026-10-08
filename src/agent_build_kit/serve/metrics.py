"""The metrics page's catalogue and its two sources (spec: web-ui)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import Frozen


class Instrument(Frozen):
    """One metric the code emits: its name, its type and the attributes it carries."""

    name: str
    type: str  # "counter", "histogram" or "gauge"
    attributes: tuple[str, ...]


def catalogue(root: Path | None = None) -> list[Instrument]:
    """Every instrument the telemetry calls under `root` (the package by default) define."""
    raise NotImplementedError
