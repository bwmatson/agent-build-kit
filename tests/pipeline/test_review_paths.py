"""Which paths never land without a person (spec: review-policy, protected paths)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.review_paths import is_protected
from tests.review_config import workspace

MIGRATION = "db/migrations/0042_add_index.sql"


@pytest.mark.parametrize(
    "path",
    [
        MIGRATION,
        ".github/workflows/ci.yml",
        "Dockerfile",
        "services/api/Dockerfile",
        "docker-compose.yml",
        ".env",
        "config/.env.production",
        "secrets/prod.key",
        "deploy/server.pem",
        ".github/CODEOWNERS",
        "CODEOWNERS",
    ],
)
def test_the_framework_defaults_protect(path: str) -> None:
    assert is_protected(workspace(), "app", path)


@pytest.mark.parametrize("path", ["src/app.py", "README.md", "tests/test_app.py", "docs/guide.md"])
def test_the_framework_defaults_leave_an_ordinary_file_alone(path: str) -> None:
    assert not is_protected(workspace(), "app", path)


def test_the_workspace_list_and_the_repos_list_are_added() -> None:
    config = workspace(
        {"protected_paths": ["deploy/**"]}, app={"protected_paths": ["src/billing/**"]}
    )

    assert is_protected(config, "app", "deploy/up.sh")
    assert is_protected(config, "app", "src/billing/charge.py")
    assert is_protected(config, "app", MIGRATION), "the defaults are still there"


def test_a_repos_list_does_not_apply_to_another_repo() -> None:
    config = workspace(
        {"protected_paths": ["deploy/**"]}, app={"protected_paths": ["src/billing/**"]}
    )

    assert is_protected(config, "platform", "deploy/up.sh")
    assert not is_protected(config, "platform", "src/billing/charge.py")


def test_a_repos_list_never_narrows_the_workspaces() -> None:
    config = workspace({"protected_paths": ["deploy/**"]}, app={"protected_paths": []})

    assert is_protected(config, "app", "deploy/up.sh")


def test_without_the_defaults_only_the_lists_protect() -> None:
    config = workspace(
        {"protected_defaults": False, "protected_paths": ["deploy/**"]},
        platform={"protected_paths": ["infra/**"]},
    )

    assert is_protected(config, "app", "deploy/up.sh")
    assert is_protected(config, "platform", "infra/main.tf")
    assert not is_protected(config, "app", MIGRATION)
    assert not is_protected(config, "app", "Dockerfile")
    assert not is_protected(config, "app", "infra/main.tf")


def test_a_directory_pattern_protects_everything_under_it() -> None:
    config = workspace({"protected_defaults": False, "protected_paths": ["deploy"]})

    assert is_protected(config, "app", "deploy/nested/up.sh")
    assert not is_protected(config, "app", "deployment/up.sh")
