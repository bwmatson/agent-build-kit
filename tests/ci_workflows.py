"""The CI workflow reader the OpenSpec warm-up step's tests use."""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def ci_jobs() -> dict[str, dict]:
    """The jobs of the repository's ci.yml, as parsed."""
    return yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]
