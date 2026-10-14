"""A pytest plugin: a live-stack test carries at most one runtime tag (spec: tier2-runtime-tags).

At collection it reads every marker an item has (its own, its class's, its module's and a
parameter's), takes the distinct `runtime_<name>` names, and for a `local_stack` item with
two or more fails collection naming each such item and its tags. No tag is the untagged
base; a test that is not `local_stack` is not checked.
"""

from __future__ import annotations

import pytest

PREFIX = "runtime_"


def runtime_tags(item: pytest.Item) -> list[str]:
    return sorted({m.name for m in item.iter_markers() if m.name.startswith(PREFIX)})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    offenders = [
        f"{item.nodeid}: {', '.join(tags)}"
        for item in items
        if item.get_closest_marker("local_stack") is not None
        and len(tags := runtime_tags(item)) > 1
    ]
    if offenders:
        raise pytest.UsageError(
            "a live-stack test carries at most one runtime tag; write a scenario that needs "
            "two runtimes as two tests:\n  " + "\n  ".join(offenders)
        )
