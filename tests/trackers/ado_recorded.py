"""Recorded and reference-written response bodies for the Azure DevOps work item tests.

A body file is a header (`source`, `page`, `date`) and a `body`; a file without the header
is refused, so a body can be told apart from a live recording.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_build_kit.model import Frozen

RECORDED = Path(__file__).parent / "recorded" / "ado"


class FixtureHeaderMissing(ValueError):
    """A body file with no header, or one lacking its source, page or date."""


class Recorded(Frozen):
    source: str
    page: str
    date: str
    body: dict[str, Any]


def load(name: str, directory: Path = RECORDED) -> Recorded:
    document = json.loads((directory / f"{name}.json").read_text())
    header = document.get("fixture") if isinstance(document, dict) else None
    parts = ("source", "page", "date")
    if not isinstance(header, dict) or not all(header.get(part) for part in parts):
        raise FixtureHeaderMissing(f"{name}: needs a header naming its source, page and date")
    return Recorded(**{part: header[part] for part in parts}, body=document["body"])
