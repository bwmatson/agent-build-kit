"""A source and a destination installation for the `--remove` and rerun tests of the split."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.cli.pipeline import record_plans
from agent_build_kit.installation import Installation
from tests.factories import new_unit
from tests.planning_split_support import load, write_installation
from tests.split_sources import write_change, write_spec, write_units

__all__ = ["declare_project", "entry_lines", "mtimes", "populate", "trees", "unit_ids"]

PLAN = {"hash": "h", "attempts": 0, "ok": True}


def trees(tmp_path: Path, *, source_repos=None) -> tuple[Path, Path]:
    """A source declaring `app` (consuming `lib`, unless `source_repos` says otherwise) and
    `lib`, and a destination declaring only `lib`."""
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    write_installation(source, *([source_repos] if source_repos else []))
    write_installation(destination, dict(lib=()))
    return source, destination


def populate(source: Path) -> Installation:
    """Two `app` changes with units and plan records, an archived one, a staying `lib` change,
    and the runtime files a split must never touch."""
    installation = load(source)
    write_change(installation, "one", ["app"], deltas=["capability"])
    write_change(installation, "two", ["app"])
    write_change(installation, "old", ["app"], archived="2025-01-01")
    write_change(installation, "stays", ["lib"])
    write_spec(installation, "capability")
    write_units(
        installation,
        new_unit("one/1", state="merged", run_log="one-1.log"),
        new_unit("two/1", state="failed"),
        new_unit("stays/1", repo="lib", state="merged"),
    )
    record_plans(installation, dict(one=PLAN, two=PLAN, stays=PLAN))
    state = installation.state_dir
    for relative in ("usage-ledger.jsonl", "spec-snapshots/one/1/tasks.md", "logs/one-1.log"):
        (state / relative).parent.mkdir(parents=True, exist_ok=True)
        (state / relative).write_text(f"{relative}\n")
    return installation


def declare_project(root: Path, repo: str, project: str) -> None:
    """Add a declared project to a repo's block in the installation's `abk.yaml`."""
    config = root / "abk.yaml"
    marker = f"    slug: example/{repo}\n"
    config.write_text(
        config.read_text().replace(marker, f"{marker}    projects:\n      - path: {project}\n")
    )


def unit_ids(installation: Installation) -> list[str]:
    records = json.loads((installation.state_dir / "units.json").read_text())["units"]
    return [record["id"] for record in records]


def entry_lines(text: str, repo: str) -> str:
    """The text of `repo`'s block under `repos:`."""
    lines = text.splitlines(keepends=True)
    start = lines.index(f"  {repo}:\n")
    end = next(
        (i for i in range(start + 1, len(lines)) if not lines[i].startswith("   ")), len(lines)
    )
    return "".join(lines[start:end])


def mtimes(root: Path) -> dict[str, int]:
    """Every path under `root` with its modification time, to prove nothing was touched."""
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in sorted(root.rglob("*"))}
