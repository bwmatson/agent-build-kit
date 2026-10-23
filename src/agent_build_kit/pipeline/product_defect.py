"""A product defect a builder reports in a `product-defect` block of its account, read without
a model: the block's fields, and the checks that decide whether the pipeline can act on it."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated

from pydantic import StringConstraints, ValidationError

from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.e2e_scope import is_product_path
from agent_build_kit.pipeline.failure_record import FailureRecord, Recorded

# A blank id or reproduction names nothing, and "" is found in every failure.
_Stated = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
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
    raise NotImplementedError


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
