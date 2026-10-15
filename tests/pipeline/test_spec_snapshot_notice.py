"""The notice a resumed session gets about spec edits carries a diff cut to a whole line."""

from __future__ import annotations

import difflib
from pathlib import Path

from agent_build_kit.pipeline import spec_snapshot
from agent_build_kit.pipeline.units import Member

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
