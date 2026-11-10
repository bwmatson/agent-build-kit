"""The notice a resumed session gets about spec edits carries a diff cut to a whole line."""

from __future__ import annotations

import difflib
from pathlib import Path

from agent_build_kit.pipeline import spec_snapshot
from agent_build_kit.pipeline.units import Member
from tests.artifact_fakes import MemoryArtifacts, given_the_artifacts

OLD = "# Design\n"


def test_a_long_diff_is_cut_at_a_line_end_within_the_limit_and_points_at_the_file(
    tmp_path: Path,
) -> None:
    change = tmp_path / "changes" / "feature"
    change.mkdir(parents=True)
    design = change / "design.md"
    design.write_text(OLD)
    members = [Member(change="feature", groups=(1,))]
    state = tmp_path / "state"
    recorded = spec_snapshot.save(state, "feature/1", "build", members, [change])

    new = OLD + "".join(f"added line {i:04d} {'y' * 30}\n" for i in range(400))
    design.write_text(new)

    text = spec_snapshot.notice(state, "feature/1", "build", recorded, members, [change])

    full = "".join(
        difflib.unified_diff(
            OLD.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile="design.md",
            tofile="design.md",
            n=1,
        )
    )
    assert len(full) > spec_snapshot.DIFF_LIMIT
    carried = text.split("```diff\n", 1)[1].split("\n```", 1)[0]
    assert len(carried) <= spec_snapshot.DIFF_LIMIT
    assert full.startswith(carried)
    assert full[len(carried)] == "\n"
    assert spec_snapshot.REST_CUT.format(limit=spec_snapshot.DIFF_LIMIT, paths=str(design)) in text


# --- over a stand-in Artifacts implementation: nothing is a file ---------------------------


def write_change(tmp_path: Path, design: str) -> tuple[Path, list[Member]]:
    change = tmp_path / "changes" / "feature"
    change.mkdir(parents=True, exist_ok=True)
    (change / "design.md").write_text(design)
    return change, [Member(change="feature", groups=(1,))]


def save_copies(artifacts: MemoryArtifacts, role: str, members: list[Member], change: Path) -> str:
    with given_the_artifacts():
        return spec_snapshot.save(
            artifacts,  # pyrefly: ignore
            "feature/1",
            role,
            members,
            [change],
        )


def test_the_copies_are_kept_under_the_units_role_key(
    tmp_path: Path, memory_artifacts: MemoryArtifacts
) -> None:
    change, members = write_change(tmp_path, OLD)

    save_copies(memory_artifacts, "build", members, change)

    assert memory_artifacts.list("spec-snapshots/") == ["spec-snapshots/feature/1/build/design.md"]
    assert memory_artifacts.get("spec-snapshots/feature/1/build/design.md") == OLD.encode()


def test_a_notice_is_read_from_the_copies_the_artifacts_hold(
    tmp_path: Path, memory_artifacts: MemoryArtifacts
) -> None:
    change, members = write_change(tmp_path, OLD)
    recorded = save_copies(memory_artifacts, "build", members, change)
    (change / "design.md").write_text(OLD + "A new decision.\n")

    with given_the_artifacts():
        text = spec_snapshot.notice(
            memory_artifacts,  # pyrefly: ignore
            "feature/1",
            "build",
            recorded,
            members,
            [change],
        )

    assert "+A new decision." in text


def test_saving_again_replaces_the_copies_and_forgetting_removes_every_role(
    tmp_path: Path, memory_artifacts: MemoryArtifacts
) -> None:
    change, members = write_change(tmp_path, OLD)
    for role in ("build", "review"):
        save_copies(memory_artifacts, role, members, change)
    (change / "design.md").write_text("# Other\n")
    save_copies(memory_artifacts, "build", members, change)

    assert memory_artifacts.get("spec-snapshots/feature/1/build/design.md") == b"# Other\n"

    with given_the_artifacts():
        spec_snapshot.forget(memory_artifacts, "feature/1")  # pyrefly: ignore

    assert memory_artifacts.list("spec-snapshots/") == []
