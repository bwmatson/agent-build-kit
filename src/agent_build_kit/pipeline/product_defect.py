"""A product defect a builder reports in a `product-defect` block of its account, read without
a model: the block's fields, and the checks that decide whether the pipeline can act on it."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Annotated

from pydantic import StringConstraints, ValidationError

from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.pipeline.e2e_scope import is_product_path
from agent_build_kit.pipeline.failure_record import FailureRecord, Recorded
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.flakes import add_needs_to_unit, next_fix_name, open_fix_change
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import PRODUCT_DEFECT_PREFIX
from agent_build_kit.pipeline.untouched_failures import Exists, Write

# A blank id or reproduction names nothing, and "" is found in every failure.
_Stated = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PREFIX = PRODUCT_DEFECT_PREFIX
CAPABILITY = "product-defects"
_BLOCK = re.compile(r"```product-defect[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL)


class ProductDefect(Frozen):
    """What the builder of an `[e2e-test]` unit found wrong in the product under test."""

    test: _Stated
    files: list[str]
    reproduction: _Stated
    sketch: str = ""
    repo: str = ""


class ProductDefectEntry(Recorded):
    """One report of a product defect for a unit, and the change that fixes it."""

    unit: str
    files: list[str]
    reproduction: str
    sketch: str = ""
    at: datetime


def product_defect_record(inst: Installation) -> FailureRecord[ProductDefectEntry]:
    """The record of reported product defects, in the state directory."""
    return FailureRecord(inst.state_dir / "product-defects.jsonl", ProductDefectEntry)


class DefectRefused(Frozen):
    """A report the pipeline will not act on, and why; the unit is stopped with the reason."""

    reason: str


def read_product_defect(
    account: str,
    *,
    failure: str,
    repo: str,
    repos: Mapping[str, RepoConfig],
    support: Sequence[str] = (),
) -> ProductDefect | DefectRefused | None:
    """The defect the last fenced `product-defect` JSON block of `account` reports; None when
    the account has no such block; a refusal for a block that is not valid JSON, lacks `test`
    or `reproduction`, has no `files`, names a test the saved `failure` does not mention, names
    a repo not in `repos` (`repo` is the unit's own, the default), or lists only paths that are
    tests, docs, the changelog or `support`."""
    blocks = _BLOCK.findall(account)
    if not blocks:
        return None
    try:
        report = json.loads(blocks[-1])
    except json.JSONDecodeError as error:
        return DefectRefused(reason=f"the product-defect block is not valid JSON: {error}")
    try:
        defect = ProductDefect.model_validate(report)
    except ValidationError as error:
        fields = sorted({str(problem["loc"][0]) for problem in error.errors() if problem["loc"]})
        return DefectRefused(
            reason=f"the product-defect block is not usable; check its {', '.join(fields)}"
            if fields
            else "the product-defect block is not a JSON object"
        )
    if not defect.files:
        return DefectRefused(reason="the product-defect block lists no files")
    if defect.test not in failure:
        return DefectRefused(
            reason=f"the product-defect block names {defect.test}, "
            "which the failure does not mention"
        )
    named = defect.repo or repo
    if named not in repos:
        return DefectRefused(reason=f"the product-defect block names the undeclared repo {named}")
    if not any(is_product_path(path, repos[named], support) for path in defect.files):
        return DefectRefused(
            reason="the files are all tests, docs or support, so this is a fault in the test: "
            "fix it in place and report no product defect"
        )
    return defect


def preview(inst: Installation, test: str) -> Exists | Write:
    """What filing a fix for `test` would do; reads the changes directory only."""
    name, earlier = open_fix_change(inst, test, PREFIX)
    if name is not None:
        return Exists(change=name)
    return Write(name=next_fix_name(inst, test, PREFIX), earlier=earlier)


def ensure_product_fix(
    inst: Installation, defect: ProductDefect, unit: StoredUnit, *, say: Callable[[str], None]
) -> str:
    """Make sure one open change fixes the defect of `defect.test`, under a lock: say
    `exists: <change>`, or `would write: <change>` then `wrote: <change>`. Returns its name."""
    with file_lock(inst.state_dir / "product-defects.lock"):
        found = preview(inst, defect.test)
        say(found.line)
        if isinstance(found, Exists):
            return found.change
        _write_change(inst, found, defect, unit)
        say(f"wrote: {found.name}")
        return found.name


def wait_on_product_defect(
    inst: Installation, defect: ProductDefect, unit: StoredUnit, *, say: Callable[[str], None]
) -> str | None:
    """Make sure one open change fixes `defect` and give each group of `unit` a `Needs:` line
    on it. Returns the change, or None for a unit of that change itself, which waits on nothing."""
    fix = ensure_product_fix(inst, defect, unit, say=say)
    if unit.change == fix:
        return None
    add_needs_to_unit(inst, unit, fix, f"product defect found by {defect.test}")
    return fix


def _write_change(
    inst: Installation, found: Write, defect: ProductDefect, unit: StoredUnit
) -> None:
    root = inst.changes_dir / found.name
    (root / "specs" / CAPABILITY).mkdir(parents=True)
    (root / "proposal.md").write_text(_proposal(inst, defect, unit, found.earlier))
    (root / "design.md").write_text(_design(defect))
    (root / "tasks.md").write_text(_tasks(defect, unit))
    (root / "specs" / CAPABILITY / "spec.md").write_text(
        _spec(defect, successor=bool(found.earlier))
    )


def _proposal(inst: Installation, defect: ProductDefect, unit: StoredUnit, earlier: str) -> str:
    met = [e for e in product_defect_record(inst).entries() if e.test == defect.test]
    seen = [f"- {e.at:%Y-%m-%d %H:%M} UTC, unit {e.unit}" for e in met]
    if unit.id not in {e.unit for e in met}:
        seen.append(f"- unit {unit.id} (this one)")
    again = (
        f"\nAn earlier change, `{earlier}`, fixed this test and was merged and archived; "
        "it fails again.\n"
        if earlier
        else ""
    )
    sketch = (
        f"\nA sketch of a unit test that reproduces it:\n\n```\n{defect.sketch.strip()}\n```\n"
        if defect.sketch
        else ""
    )
    files = ", ".join(f"`{path}`" for path in defect.files)
    return (
        "## Why\n\n"
        f"The live test `{defect.test}` found a defect in the product, which the builder of an "
        f"`[e2e-test]` unit reported without editing product code.\n{again}\n"
        f"Reproduction: {defect.reproduction}\n{sketch}\n"
        f"The builder believes the fault is in {files}.\n\n"
        "Units that met it:\n\n" + "\n".join(seen) + "\n\n"
        "## What Changes\n\n"
        f"- `{defect.test}` passes against the fixed product.\n\n"
        "## Impact\n\n"
        f"- {defect.repo or unit.repo}: the code the reproduction exercises.\n"
    )


def _design(defect: ProductDefect) -> str:
    return (
        "## Context\n\n"
        f"`{defect.test}` fails because of a defect in the product.\n\n"
        "## Decisions\n\n"
        "- Is the reported file the fault? Decide from the reproduction, then fix that one.\n"
    )


def _tasks(defect: ProductDefect, unit: StoredUnit) -> str:
    sketch = (
        "\n    ```\n"
        + "\n".join(f"    {line}" for line in defect.sketch.strip().splitlines())
        + "\n    ```"
        if defect.sketch
        else ""
    )
    files = ", ".join(f"`{path}`" for path in defect.files)
    return (
        "# Tasks\n\n"
        "Acceptance: none — the e2e-test unit that found it is the check.\n\n"
        f"## 1. [{defect.repo or unit.repo}] [{TestTier.UNIT_TEST}] "
        f"Reproduce `{defect.test}` with a unit test, then fix it\n\n"
        f"Priority: {unit.priority}\n\n"
        "Done when the unit test fails before the fix and passes after it.\n\n"
        "- [ ] 1.1 Test: reproduce the reported behaviour with a unit test that fails every "
        f"time before the fix. Reproduction: {defect.reproduction}{sketch}\n"
        f"- [ ] 1.2 Make it pass. The e2e-test builder believes the fault is in {files}; "
        "that is where to look first, not a contract.\n"
    )


def _spec(defect: ProductDefect, *, successor: bool) -> str:
    # An archive refuses to add a requirement that exists: a successor restates it.
    verb = "MODIFIED" if successor else "ADDED"
    return (
        f"## {verb} Requirements\n\n"
        f"### Requirement: `{defect.test}` passes against the fixed product\n\n"
        "The test SHALL pass against the product.\n\n"
        "#### Scenario: Run the live test\n\n"
        "- **WHEN** the test is run under the e2e-test marker\n"
        "- **THEN** it passes\n"
    )
