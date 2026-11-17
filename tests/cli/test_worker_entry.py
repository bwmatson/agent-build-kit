"""The worker entry module loads without the dispatcher's command module."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

IMPORT_SCRIPT = """
import sys
import agent_build_kit.cli.worker
print("LOADED:" + ",".join(m for m in sys.modules if m == "agent_build_kit.cli.pipeline"))
"""


def test_importing_the_worker_entry_leaves_the_dispatcher_module_unloaded(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-c", IMPORT_SCRIPT],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1] == "LOADED:"
