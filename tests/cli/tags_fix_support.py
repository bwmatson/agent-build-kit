"""A planning repo with changes tagged in the old test-kind spellings, and `abk tags` run over it.

Shared by the `abk tags --fix` tests: the files are written as bytes, so a line ending or a
missing final newline reaches the command as the test wrote it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli.pipeline import plan_digest
from tests.cli.replan_driver import Replan

OLD_UNIT_TEST_TAG = "tier" + "1"
OLD_E2E_TAG = "tier" + "2"

# Prose that mentions the old spellings, which `--fix` leaves alone: a sentence, a code span
# and a heading's title.
SENTENCE = f"this is a {OLD_UNIT_TEST_TAG} concern, see `{OLD_E2E_TAG}`"
TITLE = f"Drive {OLD_UNIT_TEST_TAG} handling"


def tasks_text(
    unit_test_tag: str, e2e_tag: str, *, eol: str = "\n", final_newline: bool = True
) -> bytes:
    """A tasks.md of two groups tagged `unit_test_tag` and `e2e_tag` [acceptance], mentioning the
    old spellings in prose; every line ends in `eol`, the last only when `final_newline`."""
    lines = [
        "# Tasks",
        "",
        f"## 1. [app] [{unit_test_tag}] Add it",
        "",
        "Done when it is added.",
        "",
        f"- [ ] 1.1 Test: {SENTENCE}.",
        "- [ ] 1.2 Add it.",
        "",
        f"## 2. [app] [{e2e_tag}] [acceptance] {TITLE}",
        "",
        "- [ ] 2.1 Test: drive it.",
    ]
    return (eol.join(lines) + (eol if final_newline else "")).encode()


def one_group_text(unit_test_tag: str) -> bytes:
    """A tasks.md of one group tagged `unit_test_tag`."""
    group = f"## 1. [app] [{unit_test_tag}] Only one\n\n- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n"
    return f"# Tasks\n\nAcceptance: none — a fixture about tags\n\n{group}".encode()


def recorded_before_the_tag_was_renamed(text: str) -> str:
    """The digest an earlier release recorded: the text's non-blank lines, hashed as written."""
    lines = "\n".join(line for line in text.splitlines() if line.strip())
    return hashlib.sha256(lines.encode()).hexdigest()


def digest_of(directory: Path, text: str) -> str:
    """The plan digest of `text`, written as a tasks.md under `directory`."""
    path = directory / "digest" / "tasks.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    return plan_digest(path)


def planning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    """A planning repo with no changes yet."""
    return Replan(tmp_path, monkeypatch)


def write_change(run: Replan, change: str, data: bytes) -> Path:
    """Write `data` as `change`'s tasks.md and return its path."""
    path = run.inst.changes_dir / change / "tasks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def run_tags(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    """`abk tags <argv>`: its exit status and everything it printed."""
    capsys.readouterr()
    code = main(["tags", *argv])
    seen = capsys.readouterr()
    return code, seen.out + seen.err


def line_about(out: str, change: str) -> str:
    """The first line of `out` that names `change`, a deprecation warning aside."""
    return next(line for line in out.splitlines() if change in line and "warning" not in line)
