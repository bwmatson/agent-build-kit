"""A unit's size leaves out the lock files the environments name, and the
framework carries no list of lock file names of its own."""

from __future__ import annotations

from agent_build_kit import config as config_module
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.forges import FileChange
from agent_build_kit.pipeline.unit_size import actual_lines


def change(path: str, additions: int, deletions: int = 0) -> FileChange:
    return FileChange(path=path, additions=additions, deletions=deletions)


def environment(*lock: str) -> dict:
    return {"sync": ["env-sync"], "check": ["env-check"], "inputs": {"lock": list(lock)}}


def configure(**sections: object) -> None:
    config_module.activate(WorkspaceConfig.model_validate(sections))


def test_a_lock_file_named_only_in_the_environment_is_not_counted() -> None:
    configure(environment=environment("vendor.lockdata"))

    lines = actual_lines([change("src/app.py", 30, 10), change("vendor.lockdata", 500, 200)])

    assert lines == 40


def test_a_lock_file_named_in_a_repository_environment_is_not_counted() -> None:
    configure(
        repos={
            "app": {
                "path": "/tmp/app",
                "slug": "example/app",
                "environment": environment("web/pins.lockdata"),
            }
        }
    )

    lines = actual_lines([change("src/app.py", 20), change("web/pins.lockdata", 400)])

    assert lines == 20


def test_the_explicit_patterns_still_apply_beside_the_environment_list() -> None:
    configure(
        limits={"generated_files": ["*.snap"]},
        environment=environment("vendor.lockdata"),
    )

    lines = actual_lines(
        [change("src/app.py", 10), change("out.snap", 90), change("vendor.lockdata", 90)]
    )

    assert lines == 10


def test_with_no_patterns_and_no_environment_a_changed_lock_file_is_counted() -> None:
    configure()

    lines = actual_lines([change("src/app.py", 50), change("uv.lock", 300, 100)])

    assert lines == 450
