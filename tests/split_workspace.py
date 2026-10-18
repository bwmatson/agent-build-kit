"""A workspace whose repos declare e2e-test splits, and tasks files whose groups name them."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from tests.conftest import make_installation

OPT_OUT = "Acceptance: none — a fixture about e2e-test splits\n"
DECLARED = {"claude_code": {"marker": "runtime_claude_code"}, "acp": {"marker": "runtime_acp"}}


def splits_workspace(
    root: Path, *, top: dict | None = None, own: dict[str, dict] | None = None
) -> Installation:
    """The active workspace: `top` is the top-level `tests.e2e_splits` (`claude_code` and `acp`
    when not given) and `own` gives a repo its own map, which replaces it."""
    declared = DECLARED if top is None else top
    repos = {
        name: {
            "path": str(root / "checkouts" / name),
            "slug": f"example/{name}",
            **({"tests": {"e2e_splits": own[name]}} if own and name in own else {}),
        }
        for name in ("app", "platform")
    }
    return make_installation(root, repos=repos, tests={"e2e_splits": declared})


def group(number: int, *lines: str, repo: str = "app", kind: str = "e2e-test") -> str:
    """One group: its heading, the given lines under it, then two tasks."""
    body = "".join(f"{line}\n" for line in lines)
    heading = f"## {number}. [{repo}] [{kind}] Group {number}\n\n"
    return heading + body + f"\n- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"


def tasks_text(*groups: str, before: str = "") -> str:
    """A `tasks.md` of `groups` (see `group`), with `before` between the opt-out and the first."""
    return f"# Tasks\n\n{OPT_OUT}\n{before}" + "".join(groups)


def line_of(text: str, wanted: str, nth: int = 1) -> int:
    """The 1-based line number of the `nth` line of `text` that is exactly `wanted`."""
    found = [i for i, line in enumerate(text.splitlines(), start=1) if line == wanted]
    return found[nth - 1]
