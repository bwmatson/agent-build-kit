"""Which project's toolchain reads a failure: the nested project, the root project, or the
repository's own profile. Pins what the failure check chooses by the directory it names."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.pipeline.check_failures import failed_check, failed_in
from tests.conftest import make_installation

# What each toolchain makes of this header: node-npm reads the type checker, python-uv sees no
# pytest and no failed hook, so it reads `lint`.
HEADER = "$ npx tsc --noEmit (exit 2)\n"


def install(tmp_path: Path, *projects: ProjectConfig) -> Path:
    app = RepoConfig(
        path=tmp_path / "app", slug="example/app", profile="python-uv", projects=list(projects)
    ).model_dump(mode="json")
    make_installation(tmp_path / "meta", repos={"app": app})
    return tmp_path / "app"


def read(checkout: Path, *parts: str) -> str:
    where = failed_in(checkout.joinpath(*parts))
    return failed_check(f"{HEADER}{where}\nerror TS2322\n", "app")


def test_a_failure_under_a_nested_project_is_read_by_that_project(tmp_path: Path) -> None:
    checkout = install(
        tmp_path,
        ProjectConfig(path="web", profile="python-uv"),
        ProjectConfig(path="web/admin", profile="node-npm"),
    )

    assert read(checkout, "web", "admin") == "types"
    assert read(checkout, "web") == "lint"


def test_a_failure_in_the_checkout_is_read_by_the_root_project(tmp_path: Path) -> None:
    checkout = install(tmp_path, ProjectConfig(path=".", profile="node-npm"))

    assert read(checkout) == "types"


def test_a_failure_under_no_project_is_read_by_the_repositorys_profile(tmp_path: Path) -> None:
    checkout = install(tmp_path, ProjectConfig(path="web", profile="node-npm"))

    assert read(checkout, "other") == "lint"
