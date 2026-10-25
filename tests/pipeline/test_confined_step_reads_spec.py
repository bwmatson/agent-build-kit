"""A confined step reads the change it is building, and a refused read of it is said in the run
log (spec: sandbox-spec-reads). The backend is a stand-in that enforces the policy's read list."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.config import models
from agent_build_kit.pipeline.claude_stream import records
from agent_build_kit.pipeline.transcript import TranscriptEvent
from agent_build_kit.pipeline.wiring import build_run, build_run_review, refused_read
from agent_build_kit.runtimes import AgentRequest, AgentResult
from tests.pipeline.test_wiring_sandbox import Recording, install
from tests.sandboxes.policy_support import reads

CHANGE_FILES = ("tasks.md", "proposal.md", "design.md", "specs/cap/spec.md")


class Enforcing(Recording):
    """Reads what the request's policy lists and refuses the rest, as a real backend would; a
    refusal reaches the run as the tool result the agent's read printed."""

    def __init__(self, wanted: list[Path]) -> None:
        super().__init__()
        self.wanted = wanted
        self.read: list[Path] = []
        self.refused: list[Path] = []

    def run(self, request: AgentRequest) -> AgentResult:
        assert request.policy is not None and request.policy.sandbox is not None
        for path in self.wanted:
            if reads(request.policy.sandbox, path):
                self.read.append(path)
            else:
                self.refused.append(path)
                if request.on_record:
                    request.on_record(
                        TranscriptEvent(
                            kind="tool_result", text=f"EACCES: permission denied, open '{path}'"
                        )
                    )
        return super().run(request)


def scene(tmp_path: Path) -> tuple[Path, Path]:
    """The installation, with the specs folder holding two changes; returns both."""
    root, _ = install(tmp_path, enabled=True)
    specs = root / "openspec"
    for change in ("feature", "other"):
        for name in CHANGE_FILES:
            file = specs / "changes" / change / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("text\n")
    return root, specs


def run_step(
    tmp_path: Path, wanted: list[Path], *, changes: tuple[str, ...], lines: list[str]
) -> Enforcing:
    """One build step of `scene`'s installation that tries to read `wanted`."""
    runtime = Enforcing(wanted)
    build_run(
        runtime=runtime,
        planning_repo=tmp_path / "plan",
        sandbox_repo="app",
        sandbox_changes=changes,
        log=lines.append,
    )("Go.", cwd=tmp_path / "main", model=models().implement)
    return runtime


def test_a_confined_step_reads_each_file_of_its_change(tmp_path: Path) -> None:
    _, specs = scene(tmp_path)
    wanted = [specs / "changes" / "feature" / name for name in CHANGE_FILES]

    runtime = run_step(tmp_path, wanted, changes=("feature",), lines=[])

    assert runtime.refused == []
    assert runtime.read == wanted


def test_a_joined_unit_s_build_reads_the_change_it_carries(tmp_path: Path) -> None:
    _, specs = scene(tmp_path)
    wanted = [specs / "changes" / change / "tasks.md" for change in ("feature", "other")]

    runtime = run_step(tmp_path, wanted, changes=("feature", "other"), lines=[])

    assert runtime.refused == []
    assert runtime.read == wanted


def test_a_review_run_reads_the_change_it_reviews_against(tmp_path: Path) -> None:
    _, specs = scene(tmp_path)
    tasks = specs / "changes" / "feature" / "tasks.md"
    runtime = Enforcing([tasks])

    build_run_review(
        runtime=runtime,
        planning_repo=tmp_path / "plan",
        sandbox_repo="app",
        sandbox_changes=("feature",),
    )(cwd=tmp_path / "main")

    assert runtime.refused == []
    assert runtime.read == [tasks]


def test_it_reads_neither_another_change_nor_the_rest_of_the_planning_repo(tmp_path: Path) -> None:
    root, specs = scene(tmp_path)
    own = specs / "changes" / "feature" / "tasks.md"
    (root / "README.md").write_text("text\n")
    others = [specs / "changes" / "other" / "tasks.md", root / "README.md"]

    runtime = run_step(tmp_path, [own, *others], changes=("feature",), lines=[])

    assert runtime.read == [own]
    assert runtime.refused == others


def test_a_refused_read_of_a_change_shows_in_the_log_as_a_sandbox_message(
    tmp_path: Path,
) -> None:
    _, specs = scene(tmp_path)
    refused = specs / "changes" / "feature" / "tasks.md"
    lines: list[str] = []

    # No change is named, so the sandbox refuses the read of one.
    run_step(tmp_path, [refused], changes=(), lines=lines)

    said = [line for line in lines if line.startswith("sandbox:") and str(refused) in line]
    assert said, lines
    assert "does not let this step read" in said[0]


def tool_result(text: str) -> str:
    """What Claude Code's stream carries when a tool call fails: a `user` event."""
    return json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": text}
                ]
            },
        }
    )


@pytest.mark.parametrize(
    "text",
    [
        "EACCES: permission denied, open '{path}'",
        "cat: {path}: Permission denied",
        "Error: EACCES: permission denied, scandir '{path}'.",
        "failed (see {path}), Permission denied",
    ],
    ids=["read-tool", "bash-cat", "trailing-dot", "bracketed"],
)
def test_a_refusal_in_a_recorded_tool_result_names_the_path_under_the_specs(
    tmp_path: Path, text: str
) -> None:
    path = tmp_path / "openspec" / "changes" / "feature" / "tasks.md"
    (event,) = records(json.loads(tool_result(text.format(path=path))))

    assert event.kind == "tool_result"
    assert [refused_read(line, tmp_path / "openspec") for line in event.text.splitlines()] == [
        str(path)
    ]


def test_a_sibling_folder_or_an_unrelated_denial_is_not_a_refused_read(tmp_path: Path) -> None:
    specs = tmp_path / "openspec"

    assert refused_read(f"cat: {tmp_path}/openspec-old/a.md: Permission denied", specs) is None
    assert refused_read(f"cat: {tmp_path}/other/a.md: Permission denied", specs) is None
    assert refused_read(f"read {specs}/changes/a/tasks.md fine", specs) is None
