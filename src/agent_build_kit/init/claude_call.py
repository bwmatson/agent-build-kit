"""One `claude -p` call whose whole argv the caller builds.

The pipeline's runners (pipeline/wiring.py) fix the flags for a build; the
init steps each need a different tool set — research reads the web and
writes nothing, a proposal writes into the planning repo — so here the
caller passes the argv and only the running is shared. Tests inject a
`RunClaude` and see the exact argv; nothing in this package calls the real
binary during a test.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from agent_build_kit.pipeline.usage_guard import check_refusal

# (argv, *, cwd=None) -> the model's text output.
RunClaude = Callable[..., str]


def claude_text(argv: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    check_refusal(result)
    return result.stdout
