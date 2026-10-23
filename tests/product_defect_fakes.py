"""A reported product defect, the account that carries it, and the hook that files its fix,
for the tests of what the pipeline does with a report."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import fix_change_name
from agent_build_kit.pipeline.product_defect import ProductDefect
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PRODUCT_DEFECT_PREFIX, Unit
from agent_build_kit.pipeline.wiring import build_on_product_defect
from tests.pipeline.test_flake_fix_change import change_with_unit

TEST = "tests/e2e/test_route.py::test_stream"
PRODUCT = "src/app/route.py"
REPRODUCTION = "GET /route/stream answers 500; it should answer 200 with the first chunk"
SKETCH = "def test_stream_answers_200(client):\n    assert client.get('/route/stream').ok\n"
PREFIX = PRODUCT_DEFECT_PREFIX
FIX = fix_change_name(TEST, PREFIX)

Hook = Callable[[Unit, ProductDefect], str | None]


def defect(**fields: Any) -> ProductDefect:
    """The defect a builder reports for `TEST`, with `fields` replacing any of its own."""
    return ProductDefect.model_validate(
        {
            "test": TEST,
            "files": [PRODUCT],
            "reproduction": REPRODUCTION,
            "sketch": SKETCH,
            **fields,
        }
    )


def account(report: ProductDefect) -> str:
    """A builder's account that ends in `report` as a fenced `product-defect` block."""
    return (
        "The product is at fault, not the test.\n\n"
        f"```product-defect\n{report.model_dump_json()}\n```\n"
    )


def met_by(inst: Installation, change: str, uid: str, *, priority: int = 2) -> StoredUnit:
    """A unit of `change` (one group, in the planning repo) at `priority`."""
    return change_with_unit(inst, change, uid).model_copy(update={"priority": priority})


def reporter(
    inst: Installation, *units: StoredUnit, log: list[str] | None = None
) -> tuple[Hook, UnitStore]:
    """The runner's hook over a store holding `units`, and that store."""
    store = UnitStore(inst.root / "units.json")
    store.upsert(list(units))
    lines = log if log is not None else []
    return build_on_product_defect(store, inst, log=lines.append), store
