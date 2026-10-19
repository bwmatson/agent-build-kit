"""`tests.e2e_dimensions` and `tests.e2e_available`: loaded at the top level and per repo,
refused when a marker is shared or an availability names something undeclared, and read from
the committed file and the machine-local overlay (spec: e2e-dimensions)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.config import (
    ConfigError,
    WorkspaceConfig,
    e2e_dimensions,
    load,
    unavailable_markers,
)

RUNTIME = {
    "claude_code": {"marker": "runtime_claude_code"},
    "acp": {"marker": "runtime_acp"},
}
TELEMETRY = {"otel": {"marker": "telemetry_otel"}, "local": {"marker": "telemetry_local"}}
DIMENSIONS = {"runtime": RUNTIME, "telemetry": TELEMETRY}


def document(
    dimensions: Any = None,
    *,
    available: Any = None,
    own: Any = None,
    splits: Any = None,
) -> dict[str, Any]:
    app: dict[str, Any] = {"path": "/work/app", "slug": "example/app"}
    if own is not None:
        app["tests"] = {"e2e_dimensions": own}
    tests: dict[str, Any] = {}
    if dimensions is not None:
        tests["e2e_dimensions"] = dimensions
    if available is not None:
        tests["e2e_available"] = available
    if splits is not None:
        tests["e2e_splits"] = splits
    return {
        "tests": tests,
        "repos": {
            "app": app,
            "platform": {"path": "/work/platform", "slug": "example/platform"},
        },
    }


def config(*args: Any, **kwargs: Any) -> Any:
    return WorkspaceConfig.model_validate(document(*args, **kwargs))


def markers(loaded: Any, repo: str = "app") -> dict[str, dict[str, str]]:
    return {
        dimension: {value: entry.marker for value, entry in values.items()}
        for dimension, values in e2e_dimensions(loaded.repos[repo], loaded).items()
    }


def test_the_dimensions_load_at_the_top_level() -> None:
    assert markers(config(DIMENSIONS)) == {
        "runtime": {"claude_code": "runtime_claude_code", "acp": "runtime_acp"},
        "telemetry": {"otel": "telemetry_otel", "local": "telemetry_local"},
    }


def test_nothing_declared_gives_no_dimensions() -> None:
    assert markers(config()) == {}


def test_a_repos_own_dimensions_replace_the_top_levels() -> None:
    loaded = config(DIMENSIONS, own={"runtime": {"acp": {"marker": "app_acp"}}})

    assert markers(loaded) == {"runtime": {"acp": "app_acp"}}
    assert set(markers(loaded, "platform")) == {"runtime", "telemetry"}


def test_a_marker_shared_by_two_values_is_refused_naming_it() -> None:
    shared = {"runtime": {"a": {"marker": "same"}, "b": {"marker": "same"}}}

    with pytest.raises(ValidationError, match="same"):
        config(shared)


def test_a_marker_shared_by_two_dimensions_is_refused_naming_it() -> None:
    shared = {"runtime": {"a": {"marker": "same"}}, "telemetry": {"b": {"marker": "same"}}}

    with pytest.raises(ValidationError, match="same"):
        config(shared)


def test_a_marker_shared_by_a_value_and_a_split_is_refused_naming_it() -> None:
    with pytest.raises(ValidationError, match="runtime_acp"):
        config(DIMENSIONS, splits={"acp": {"marker": "runtime_acp"}})


def test_a_repos_marker_shared_with_a_split_is_refused_naming_it() -> None:
    with pytest.raises(ValidationError, match="app_acp"):
        config(
            own={"runtime": {"acp": {"marker": "app_acp"}}},
            splits={"acp": {"marker": "app_acp"}},
        )


def test_an_availability_of_an_undeclared_dimension_is_refused_naming_it() -> None:
    with pytest.raises(ValidationError, match="nonesuch"):
        config(DIMENSIONS, available={"nonesuch": ["x"]})


def test_an_availability_of_an_undeclared_value_is_refused_naming_it() -> None:
    with pytest.raises(ValidationError, match="nonesuch"):
        config(DIMENSIONS, available={"telemetry": ["nonesuch"]})


def test_with_nothing_available_set_every_value_is_available() -> None:
    loaded = config(DIMENSIONS)

    assert unavailable_markers(loaded.repos["app"], loaded) == ()


def test_the_values_a_machine_lacks_are_the_unavailable_markers() -> None:
    loaded = config(DIMENSIONS, available={"telemetry": ["local"]})

    assert unavailable_markers(loaded.repos["app"], loaded) == ("telemetry_otel",)


def test_a_dimension_with_no_entry_keeps_every_value() -> None:
    loaded = config(DIMENSIONS, available={"runtime": ["claude_code"]})

    assert unavailable_markers(loaded.repos["app"], loaded) == ("runtime_acp",)


def test_a_repos_own_dimensions_decide_its_unavailable_markers() -> None:
    loaded = config(
        DIMENSIONS,
        own={"runtime": {"acp": {"marker": "app_acp"}, "x": {"marker": "app_x"}}},
        available={"runtime": ["x"]},
    )

    assert unavailable_markers(loaded.repos["app"], loaded) == ("app_acp",)


def write(root: Path, name: str, content: dict[str, Any]) -> Path:
    path = root / name
    path.write_text(yaml.safe_dump(content))
    return path


def test_availability_loads_from_the_committed_file(tmp_path: Path) -> None:
    path = write(tmp_path, "abk.yaml", document(DIMENSIONS, available={"telemetry": ["local"]}))

    loaded = load(path)

    assert loaded.tests.e2e_available == {"telemetry": ["local"]}
    assert unavailable_markers(loaded.repos["app"], loaded) == ("telemetry_otel",)


def test_availability_loads_from_the_local_overlay(tmp_path: Path) -> None:
    path = write(tmp_path, "abk.yaml", document(DIMENSIONS))
    write(tmp_path, "abk.local.yaml", {"tests": {"e2e_available": {"runtime": ["claude_code"]}}})

    loaded = load(path)

    assert loaded.tests.e2e_available == {"runtime": ["claude_code"]}
    assert len(loaded.tests.e2e_dimensions) == 2
    assert unavailable_markers(loaded.repos["app"], loaded) == ("runtime_acp",)


def test_an_overlay_availability_naming_an_undeclared_value_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, "abk.yaml", document(DIMENSIONS))
    write(tmp_path, "abk.local.yaml", {"tests": {"e2e_available": {"runtime": ["nonesuch"]}}})

    with pytest.raises(ConfigError, match="nonesuch"):
        load(path)
