"""A planning repo with changes, a stand-in planner, and `abk replan` run against them.

The planner is faked at its boundary: the runtime answers in the raw shape a model
sends (prose, then a JSON graph), and what was asked of it is counted in `calls`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.work_graph import specification_text
from tests.conftest import make_installation
from tests.runtimes.stand_in import StandInRuntime

OPT_OUT = "Acceptance: none — a fixture about replanning\n"


def tasks_md(groups: int = 2, *, needs: dict[int, str] | None = None) -> str:
    text = f"# Tasks\n\n{OPT_OUT}\n"
    for number in range(1, groups + 1):
        text += f"## {number}. [app] [unit-test] Group {number}\n\n"
        if needs and number in needs:
            text += f"Needs: {needs[number]} — a reason\n\n"
        text += f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
    return text


def tagged_md(*tags: str, repo: str = "app") -> str:
    """A tasks.md with one group per tag, each headed `## <n>. [<repo>] [<tag>] Group <n>`."""
    text = f"# Tasks\n\n{OPT_OUT}\n"
    for number, tag in enumerate(tags, start=1):
        text += f"## {number}. [{repo}] [{tag}] Group {number}\n\n- [ ] {number}.1 Test: it.\n"
        text += f"- [ ] {number}.2 Do it.\n\n"
    return text


def needs_md(*lines: str) -> str:
    text = f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [unit-test] The work\n\n"
    text += "".join(f"Needs: {line} — a reason\n" for line in lines)
    return text + "\n- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n"


def planned(
    uid: str, groups: tuple[int, ...], *, depends_on: tuple[str, ...] = (), lines: int = 80
) -> dict:
    return {
        "id": uid,
        "change": uid.split("/")[0],
        "title": "A unit",
        "repo": "app",
        "tier": "unit-test",
        "depends_on": list(depends_on),
        "estimated_lines": lines,
        "groups": list(groups),
    }


def answer(*units: dict, joins: list[dict] | None = None) -> str:
    return "Here is the plan.\n\n" + json.dumps({"units": list(units), "joins": joins or []})


def record_plan(inst: Installation, change: str, **fields) -> None:
    """Record `change` as planned at its current `tasks.md`, with `fields` changed."""
    text = (inst.changes_dir / change / "tasks.md").read_text()
    digest = hashlib.sha256(specification_text(text).encode()).hexdigest()
    entry = {"hash": digest, "attempts": 0, "ok": True, **fields}
    path = inst.state_dir / "planned.json"
    records = json.loads(path.read_text()) if path.exists() else {}
    path.write_text(json.dumps({**records, change: entry}))


class Replan:
    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        limits: dict | None = None,
        repos: dict | None = None,
        **changes: str,
    ) -> None:
        self.inst = make_installation(
            tmp_path / "planning",
            planning={"state_dir": ".", "worktree_root": str(tmp_path / "trees")},
            **({"limits": limits} if limits else {}),
            **({"repos": repos} if repos else {}),
        )
        (self.inst.root / "abk.yaml").write_text(dump(self.inst.config))
        monkeypatch.chdir(self.inst.root)
        for change, text in changes.items():
            self.write(change, text)
        self.store = UnitStore(self.inst.state_dir / "units.json")
        self.runtime = StandInRuntime()
        monkeypatch.setattr(runtimes, "active", lambda: self.runtime)

    def write(self, change: str, text: str) -> None:
        (self.inst.changes_dir / change).mkdir(parents=True, exist_ok=True)
        (self.inst.changes_dir / change / "tasks.md").write_text(text)

    @property
    def calls(self) -> int:
        return len(self.runtime.requests)

    @property
    def records(self) -> dict:
        path = self.inst.state_dir / "planned.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def record(self, change: str, **fields) -> None:
        """Record `change` as planned at its current `tasks.md`, with `fields` changed."""
        record_plan(self.inst, change, **fields)

    def run(
        self, capsys: pytest.CaptureFixture[str], *argv: str, reply: str = ""
    ) -> tuple[int, str]:
        if reply:
            self.runtime.answer = reply
        capsys.readouterr()
        code = main(["replan", *argv])
        seen = capsys.readouterr()
        return code, seen.out + seen.err
