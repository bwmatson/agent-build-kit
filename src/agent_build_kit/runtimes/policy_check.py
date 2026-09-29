"""Whether the active runtime refuses what abk forbids, asked at most once a
short while.

`check_policy` may cost an agent call (a probe run), and `doctor` and `init`
ask it every time they run, so an answer is kept in a file beside the usage
reading and reused while it is fresh. A caller that has just changed what the
answer depends on — `init`, after running the installation's fix — asks for a
fresh one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.runtimes.base import AgentRuntime, PolicyReport

# The cache's file name in the planning repo's state directory.
CACHE_NAME = "policy-check.json"

# How long an answer is reused before the runtime is asked again.
MAX_AGE = timedelta(minutes=15)


def checked(
    runtime: AgentRuntime,
    cwd: Path,
    *,
    cache: Path,
    now: datetime | None = None,
    fresh: bool = False,
) -> PolicyReport:
    """`runtime.check_policy(cwd)`, or the answer it gave within `MAX_AGE`.

    Answers are kept per runtime, so switching runtimes never reuses the
    other's. An unreadable cache is a cache miss."""
    now = now or datetime.now(UTC)
    try:
        kept = json.loads(cache.read_text())
        if not isinstance(kept, dict):
            kept = {}
    except (OSError, ValueError):
        kept = {}

    if not fresh:
        try:
            entry = kept[runtime.name]
            if now - datetime.fromisoformat(entry["checked_at"]) < MAX_AGE:
                return PolicyReport.model_validate(entry["report"])
        except (KeyError, TypeError, ValueError):
            pass  # Nothing usable kept for this runtime: ask it.

    report = runtime.check_policy(cwd)
    kept[runtime.name] = {"checked_at": now.isoformat(), "report": report.model_dump(mode="json")}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(kept, indent=2))
    return report
