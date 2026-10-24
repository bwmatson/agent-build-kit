"""`abk.local.yaml` is merged over `abk.yaml` at load: mappings by key, anything else
replaced whole, `null` replaces, and no overlay changes nothing."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_build_kit.config import (
    RepoConfig,
    WorkspaceConfig,
    deprecations,
    dump,
    load,
    merge_local,
    read_base,
)

PROVIDER_A = {"from": "literal", "value": "a-value"}
PROVIDER_B = {"from": "literal", "value": "b-value"}


def committed(root: Path, **extra) -> Path:
    document = {"repos": {"app": {"path": ".", "slug": "example/app"}}, **extra}
    path = root / "abk.yaml"
    path.write_text(yaml.safe_dump(document))
    return path


def overlay(root: Path, document: dict) -> None:
    (root / "abk.local.yaml").write_text(yaml.safe_dump(document))


def test_a_mapping_merges_key_by_key(tmp_path: Path) -> None:
    path = committed(tmp_path, verify={"env": {"A": PROVIDER_A}})
    overlay(tmp_path, {"verify": {"env": {"B": PROVIDER_B}}})

    env = load(path).verify.env

    assert set(env) == {"A", "B"}


def test_a_list_is_replaced_whole(tmp_path: Path) -> None:
    path = committed(tmp_path)
    document = yaml.safe_load(path.read_text())
    document["repos"]["app"]["deploy"] = {"live_written": ["one/", "two/"]}
    path.write_text(yaml.safe_dump(document))
    overlay(tmp_path, {"repos": {"app": {"deploy": {"live_written": ["three/"]}}}})

    assert load(path).repos["app"].deploy.live_written == ["three/"]


def test_a_prose_string_is_replaced_whole(tmp_path: Path) -> None:
    path = committed(tmp_path)
    document = yaml.safe_load(path.read_text())
    document["repos"]["app"]["relationships"] = "committed text"
    path.write_text(yaml.safe_dump(document))
    overlay(tmp_path, {"repos": {"app": {"relationships": "local text"}}})

    assert load(path).repos["app"].relationships == "local text"


def test_a_null_replaces_the_committed_value(tmp_path: Path) -> None:
    path = committed(tmp_path)
    document = yaml.safe_load(path.read_text())
    document["repos"]["app"]["deploy"] = {"ssh_key": "/keys/id"}
    path.write_text(yaml.safe_dump(document))
    overlay(tmp_path, {"repos": {"app": {"deploy": {"ssh_key": None}}}})

    assert load(path).repos["app"].deploy.ssh_key is None


def test_a_key_only_in_the_overlay_is_added(tmp_path: Path) -> None:
    path = committed(tmp_path)
    overlay(tmp_path, {"repos": {"platform": {"path": str(tmp_path / "platform"), "slug": "x/y"}}})

    assert set(load(path).repos) == {"app", "platform"}


def test_merge_local_replaces_anything_that_is_not_a_pair_of_mappings() -> None:
    base = {"a": {"x": 1, "y": [1, 2]}, "b": "text", "c": {"k": 1}}
    local = {"a": {"y": [3]}, "b": None, "c": "scalar", "d": 4}

    assert merge_local(base, local) == {"a": {"x": 1, "y": [3]}, "b": None, "c": "scalar", "d": 4}
    assert base["a"]["y"] == [1, 2]


def test_no_overlay_loads_as_the_committed_file_alone(tmp_path: Path) -> None:
    path = committed(tmp_path, verify={"env": {"A": PROVIDER_A}})

    assert load(path) == WorkspaceConfig.model_validate(read_base(path))


def test_a_committed_file_at_its_defaults_merges_to_what_the_old_loader_gave(
    tmp_path: Path,
) -> None:
    config = WorkspaceConfig(repos={"app": RepoConfig(path=tmp_path / "app", slug="example/app")})
    path = tmp_path / "abk.yaml"
    path.write_text(dump(config))

    merged = merge_local(read_base(path), {})

    assert WorkspaceConfig.model_validate(merged) == config
    assert load(path) == config


def test_a_deprecated_root_key_in_one_file_merges_with_the_new_spelling_in_the_other(
    tmp_path: Path,
) -> None:
    path = committed(tmp_path, limits={"min_unit_lines": 100})
    overlay(tmp_path, {"global_limits": {"manual_check_seconds": 60}})

    limits = load(path).global_limits

    assert (limits.min_unit_lines, limits.manual_check_seconds) == (100, 60)

    path = committed(tmp_path, global_limits={"min_unit_lines": 100})
    overlay(tmp_path, {"limits": {"manual_check_seconds": 60}})

    limits = load(path).global_limits

    assert (limits.min_unit_lines, limits.manual_check_seconds) == (100, 60)


def test_deprecations_reports_the_old_key_when_only_the_overlay_uses_it(tmp_path: Path) -> None:
    path = committed(tmp_path)
    overlay(tmp_path, {"limits": {"min_unit_lines": 100}})

    assert deprecations(path) == ["limits"]
