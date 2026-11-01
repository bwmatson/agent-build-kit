"""The test files a group's tasks name, read from the group and not from one line."""

from __future__ import annotations

from agent_build_kit.pipeline.group_paths import named_test_paths
from agent_build_kit.pipeline.work_graph import validate_tasks_text

TASKS = """\
## 1. [app] [unit-test] Fill lanes

- [ ] 1.1 Test: `tests/lanes/test_gap.py` — a gap is filled, covering `src/app/lanes.py`.
- [ ] 1.2 Tests: `tests/lanes/test_conflict.py`
      and, on the next line, `tests/lanes/test_wrapped.py`. Verify: red.
- [ ] 1.3 Add the fill in `src/app/lanes.py`, checked by `tests/lanes/test_gap.py`.
"""


def test_every_test_file_is_listed_once_and_a_source_file_is_not() -> None:
    (group,), _ = validate_tasks_text(TASKS, "feature", repos=("app",))

    assert named_test_paths(group) == [
        "tests/lanes/test_gap.py",
        "tests/lanes/test_conflict.py",
        "tests/lanes/test_wrapped.py",
    ]
