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
EXPRESSION = re.compile(r"^\$\{\{\s*matrix\.(\w+)\s*\}\}$")


def _problem(where: str, what: str) -> str:
    return f"{where}: {what}; {POINTER}"


def _check_uses(where: str, uses: str) -> list[str]:
    if uses.startswith(("./", "docker://")):
        return []
    found = EXACT.match(uses)
    if "${{" in uses or not found:
        return [_problem(where, f"{uses} is not owner/name@vX.Y.Z or a full commit SHA")]
    name, major = found["name"], found["major"]
    first = FIRST_NODE_24_MAJOR.get(name)
    if first is None:
        return [_problem(where, f"{uses}: add {name} to the table with its first Node 24 major")]
    if major is not None and int(major) < first:
        return [_problem(where, f"{uses} is below {name} v{first}, the first major on Node 24")]
    return []


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
    scalar = not isinstance(runs_on, list)
    problems = []
    for label in labels:
        if str(label).endswith("-latest"):
            problems.append(_problem(where, f"runner {label} floats; use {RUNNER}"))
        elif scalar and label != RUNNER:
            problems.append(_problem(where, f"runner {label} is not {RUNNER}"))
    return problems


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
