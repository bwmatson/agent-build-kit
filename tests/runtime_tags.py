"""A pytest plugin: a live-stack test carries at most one runtime tag (spec: e2e-runtime-tags).

At collection it reads every marker an item has (its own, its class's, its module's and a
parameter's), takes the distinct `runtime_<name>` names, and for a `local_stack` item with
two or more fails collection naming each such item and its tags. No tag is the untagged
base; a test that is not `local_stack` is not checked.
"""

from __future__ import annotations

import pytest

from agent_build_kit.config import E2eDimensionValue
from agent_build_kit.pipeline.e2e_exclusive import values_carried_twice

PREFIX = "runtime_"


def runtime_tags(item: pytest.Item) -> list[str]:
    return sorted({m.name for m in item.iter_markers() if m.name.startswith(PREFIX)})


def tags_carried_twice(item: pytest.Item) -> list[str]:
    """The runtime tags of `item` when it carries two or more, by the one rule of
    `values_carried_twice` over a `runtime` dimension built from its `runtime_*` markers."""
    names = runtime_tags(item)
    dimensions = {
        "runtime": {name[len(PREFIX) :]: E2eDimensionValue(marker=name) for name in names}
    }
    found = values_carried_twice(names, dimensions).get("runtime", ())
    return [PREFIX + value for value in found]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    offenders = [
        f"{item.nodeid}: {', '.join(tags)}"
        for item in items
        if item.get_closest_marker("local_stack") is not None and (tags := tags_carried_twice(item))
    ]
    if offenders:
        raise pytest.UsageError(
            "a live-stack test carries at most one runtime tag; write a scenario that needs "
            "two runtimes as two tests:\n  " + "\n  ".join(offenders)
        )
