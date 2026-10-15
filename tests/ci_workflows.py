"""The CI workflow guard's checker and its table (spec: ci-workflows)."""

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# The first major of each action that runs on Node 24.
FIRST_NODE_24_MAJOR: dict[str, int] = {
    "actions/checkout": 5,
    "actions/setup-node": 5,
    "actions/setup-python": 6,
    "astral-sh/setup-uv": 7,
}

RUNNER = "ubuntu-24.04"

POINTER = "see AGENTS.md, CI workflows"


def check_workflow(file: str, text: str) -> list[str]:
    """Problems found in one workflow file's text, each naming file, job and step."""
    raise NotImplementedError
