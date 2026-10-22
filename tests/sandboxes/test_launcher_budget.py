"""The launcher starts in every step, so it imports almost nothing and starts quickly."""

from __future__ import annotations

import os
import time

from agent_build_kit import sandboxes
from tests.sandboxes.landlock_support import Scene, require_working, run_confined

# What one start may cost, best of several so a busy machine does not fail it. The measured
# cost is about 21 ms over the interpreter's own start; this leaves room for a loaded runner.
START_BUDGET_SECONDS = 0.25
STARTS = 5

# Modules whose import is the difference between a 21 ms start and a 70 ms one.
HEAVY = ("argparse", "json", "pydantic")


def _imported(stderr: str) -> set[str]:
    """The module names in `PYTHONPROFILEIMPORTTIME` output (`import time: self | cum | name`)."""
    names = set()
    for line in stderr.splitlines():
        if line.startswith("import time:") and "|" in line:
            names.add(line.rsplit("|", 1)[1].strip().split(".")[0])
    return names


def test_the_launcher_imports_no_argparse_and_no_json(scene: Scene) -> None:
    backend = sandboxes.get("landlock")
    require_working(backend)
    env = {**os.environ, "PYTHONPROFILEIMPORTTIME": "1"}

    result = run_confined(backend, scene.policy(), ["true"], env=env)

    assert result.returncode == 0, result.stderr
    imported = _imported(result.stderr)
    assert imported, "no import times were reported"
    assert not imported & set(HEAVY), sorted(imported & set(HEAVY))


def test_the_launcher_starts_within_its_budget(scene: Scene) -> None:
    backend = sandboxes.get("landlock")
    require_working(backend)
    times = []
    for _ in range(STARTS):
        began = time.perf_counter()
        result = run_confined(backend, scene.policy(), ["true"])
        times.append(time.perf_counter() - began)
        assert result.returncode == 0, result.stderr

    assert min(times) < START_BUDGET_SECONDS, times
