"""What a package's tests folder takes over from the root conftest, in one place.

A package's `tests/conftest.py` star-imports this module, so the suite's guards and fixtures
apply to its tests as they do to the tests under `tests/`.

The root conftest's fixtures and plugin list are taken over by name. Its collection hook is not:
when a run collects both trees the root conftest is loaded too and runs it over every item, and a
second registration would run it twice. A run of a package's tree alone has no root conftest, so
the hook is run from here then.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import conftest as shared

ROOT_CONFTEST = Path(shared.__file__).resolve()
HOOK = "pytest_collection_modifyitems"

globals().update(
    {
        name: value
        for name, value in vars(shared).items()
        if name != HOOK and not name.startswith("__")
    }
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Hold the tests built on a faked pass to the loaded time limit, as the root conftest does,
    when a run of a package's tree alone has no root conftest to do it."""
    loaded = any(
        Path(str(name)).resolve() == ROOT_CONFTEST
        for name, _ in config.pluginmanager.list_name_plugin()
    )
    if not loaded:
        shared.pytest_collection_modifyitems(items)
