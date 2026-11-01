"""The layout block of AGENTS.md names every source package and the design documents folder."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "agent_build_kit"


def layout_block() -> str:
    """The first fenced code block after the `## Layout` heading of AGENTS.md."""
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    after = text[text.index("## Layout") :]
    match = re.search(r"```[^\n]*\n(.*?)\n```", after, re.S)
    assert match, "AGENTS.md has no code block under ## Layout"
    return match.group(1)


def names_directory(block: str, name: str) -> bool:
    return re.search(rf"(?<![\w/.-]){re.escape(name)}/", block) is not None


def test_the_layout_block_names_every_source_package() -> None:
    packages = sorted(
        path.name
        for path in PACKAGE_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    )
    assert packages
    block = layout_block()
    missing = [name for name in packages if not names_directory(block, name)]
    assert missing == [], f"AGENTS.md layout block does not name: {missing}"


def test_the_layout_block_names_the_design_documents_folder() -> None:
    assert "docs/designs/" in layout_block()
