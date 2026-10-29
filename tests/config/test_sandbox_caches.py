"""The `caches` list on a repo's and a project's `sandbox`: accepted, `~` paths allowed, a
non-list refused with the key named, and unset told apart from empty (spec: sandbox-caches)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import ConfigError, RepoConfig, load

REPO = "repos:\n  app:\n    path: /srv/app\n    slug: example/app\n"


def loaded(tmp_path: Path, repo_body: str) -> RepoConfig:
    path = tmp_path / "abk.yaml"
    path.write_text(REPO + repo_body)
    return load(path).repos["app"]


def test_a_repo_accepts_a_caches_list_with_a_tilde_path(tmp_path: Path) -> None:
    repo = loaded(tmp_path, "    sandbox:\n      caches: [~/.cache/uv, /var/cache/tool]\n")

    assert repo.sandbox.model_dump()["caches"] == ["~/.cache/uv", "/var/cache/tool"]


def test_a_project_accepts_a_caches_list(tmp_path: Path) -> None:
    body = (
        "    projects:\n      - path: web\n        sandbox:\n"
        "          caches: [~/.cache/web-tool]\n"
    )

    repo = loaded(tmp_path, body)

    assert repo.projects[0].sandbox.model_dump()["caches"] == ["~/.cache/web-tool"]


def test_unset_differs_from_an_empty_list(tmp_path: Path) -> None:
    empty = loaded(tmp_path, "    sandbox:\n      caches: []\n")
    unset = loaded(tmp_path, "    sandbox:\n      write: []\n")

    assert empty.sandbox.model_dump()["caches"] == []
    assert unset.sandbox.model_dump()["caches"] is None


def test_a_caches_value_that_is_not_a_list_is_refused_naming_the_key(tmp_path: Path) -> None:
    loaded(tmp_path, "    sandbox:\n      caches: [~/.cache/uv]\n")

    with pytest.raises(ConfigError, match="caches"):
        loaded(tmp_path, "    sandbox:\n      caches: ~/.cache/uv\n")
    with pytest.raises(ConfigError, match="caches"):
        loaded(
            tmp_path,
            "    projects:\n      - path: web\n        sandbox:\n"
            "          caches: ~/.cache/web-tool\n",
        )
