"""The CI workflow guard's checker and its table (spec: ci-workflows)."""

import re
from pathlib import Path

import yaml

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


EXACT = re.compile(
    r"^(?P<name>[^/@\s]+/[^/@\s]+)(?:/\S*)?@(?:v(?P<major>\d+)\.\d+\.\d+|[0-9a-f]{40})$"
)
LOOSE = re.compile(r"^(?P<name>[^/@\s]+/[^/@\s]+)(?:/\S*)?@v(?P<major>\d+)(?:\.\d+)*$")
EXPRESSION = re.compile(r"^\$\{\{\s*matrix\.(\w+)\s*\}\}$")


def _problem(where: str, what: str) -> str:
    return f"{where}: {what}; {POINTER}"


def _check_uses(where: str, uses: str) -> list[str]:
    if uses.startswith(("./", "docker://")):
        return []
    found = EXACT.match(uses)
    loose = LOOSE.match(uses)
    named = found or loose
    name = named["name"] if named else None
    major = named["major"] if named else None
    first = FIRST_NODE_24_MAJOR.get(name) if name else None
    reasons = []
    if "${{" in uses or not found:
        reasons.append("is not owner/name@vX.Y.Z or a full commit SHA")
    elif first is None:
        return [_problem(where, f"{uses}: add {name} to the table with its first Node 24 major")]
    if first is not None and major is not None and int(major) < first:
        reasons.append(f"is below {name} v{first}, the first major on Node 24")
    return [_problem(where, f"{uses} " + ", and ".join(reasons))] if reasons else []


def _runner_labels(job: dict, runs_on: object) -> list[object] | None:
    if isinstance(runs_on, str) and (expr := EXPRESSION.match(runs_on)):
        values = ((job.get("strategy") or {}).get("matrix") or {}).get(expr[1])
        return list(values) if isinstance(values, list) else None
    return runs_on if isinstance(runs_on, list) else [runs_on]


def _check_runner(where: str, job: dict) -> list[str]:
    runs_on = job.get("runs-on")
    labels = _runner_labels(job, runs_on)
    if labels is None:
        return [_problem(where, f"runs-on {runs_on} cannot be read")]
    if any(str(label).endswith("-latest") for label in labels):
        return [_problem(where, f"runner {labels} floats; use {RUNNER}")]
    # A list of labels names one machine and must include the pin; a matrix runs each value.
    pinned = (
        RUNNER in labels if isinstance(runs_on, list) else all(label == RUNNER for label in labels)
    )
    return [] if pinned else [_problem(where, f"runner {labels} is not {RUNNER}")]


def check_workflow(file: str, text: str) -> list[str]:
    """Problems found in one workflow file's text, each naming file, job and step."""
    problems: list[str] = []
    jobs = (yaml.safe_load(text) or {}).get("jobs") or {}
    for job_name, job in jobs.items():
        if "uses" in job:
            continue
        where = f"{file}, job {job_name}"
        problems += _check_runner(where, job)
        for number, step in enumerate(job.get("steps") or [], start=1):
            if isinstance(step.get("uses"), str):
                label = step.get("name") or step.get("id") or f"#{number}"
                problems += _check_uses(f"{where}, step {label}", step["uses"])
    return problems
