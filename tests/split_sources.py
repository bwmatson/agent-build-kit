"""Builders for a temporary source installation the split tests plan over."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from tests.conftest import make_installation

__all__ = ["snapshot_tree", "source_installation", "write_change", "write_spec", "write_units"]


def source_installation(root: Path, **projects: Sequence[str]) -> Installation:
    """A planning root declaring repos `app` and `lib`; `projects` maps a repo to the
    project paths it declares."""
    repos = {
        name: dict(
            path=str(root / "checkouts" / name),
            slug=f"example/{name}",
            projects=[dict(path=path) for path in projects.get(name, ())],
        )
        for name in ("app", "lib")
    }
    return make_installation(root, repos=repos)


def write_change(
    source: Installation,
    name: str,
    tags: Sequence[str],
    *,
    archived: str | None = None,
    deltas: Sequence[str] = (),
    tasks: bool = True,
) -> Path:
    """A change under the source's changes directory (or its archive, as `<archived>-<name>`),
    one group per tag, with a `proposal.md` and a delta spec directory per name in `deltas`."""
    directory = source.changes_dir / (f"archive/{archived}-{name}" if archived else name)
    directory.mkdir(parents=True)
    (directory / "proposal.md").write_text(f"# {name}\n")
    if tasks:
        sections = [
            f"## {number}. [{tag}] [tier1] Group {number}\n\n- [ ] {number}.1 Test: it\n"
            for number, tag in enumerate(tags, start=1)
        ]
        (directory / "tasks.md").write_text("# Tasks\n\n" + "\n".join(sections))
    for capability in deltas:
        (directory / "specs" / capability).mkdir(parents=True)
        (directory / "specs" / capability / "spec.md").write_text(f"## ADDED {name}\n")
    return directory


def write_spec(source: Installation, capability: str) -> Path:
    """A main spec of the source."""
    directory = source.specs_dir / "specs" / capability
    directory.mkdir(parents=True)
    (directory / "spec.md").write_text(f"# {capability}\n")
    return directory


def write_units(source: Installation, *units: StoredUnit) -> UnitStore:
    """The source's unit store holding `units` as given, state and free text included (`upsert`
    drops both)."""
    store = UnitStore(source.state_dir / "units.json")
    store.import_units(units)
    return store


def snapshot_tree(root: Path) -> dict[str, bytes]:
    """Every file under `root` by relative path, to compare a tree before and after."""
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }
