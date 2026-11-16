"""`repos.<repo>.generated` (spec: generated-files-restack): entries load with `paths`, `command`
and `cwd`, a bad entry is refused naming it, the paths count as generated for a unit's size, and
`abk doctor` lists each entry and warns for a pattern that matches nothing or a missing command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit import config as config_module
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import ConfigError, RepoConfig, WorkspaceConfig, dump, load
from agent_build_kit.forges import FileChange
from agent_build_kit.pipeline.unit_size import actual_lines
from tests.cli.test_doctor import Answers
from tests.factories import git, init_repo, which_all

ENTRY = {
    "paths": ["web/dist/**", "src/template.html"],
    "command": ["npm", "run", "build"],
    "cwd": "web",
}


def write(root: Path, entries: list[dict[str, Any]]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "abk.yaml"
    repo = {"path": "/work/app", "slug": "example/app", "generated": entries}
    path.write_text(yaml.safe_dump({"version": 1, "repos": {"app": repo}}))
    return path


def refusal(path: Path) -> str:
    try:
        load(path)
    except ConfigError as refused:
        return str(refused)
    return ""


def test_an_entry_loads_with_its_paths_command_and_cwd_and_its_paths_count_as_generated(
    tmp_path: Path,
) -> None:
    loaded = load(write(tmp_path, [ENTRY]))

    [entry] = loaded.repos["app"].generated
    assert entry.paths == ("web/dist/**", "src/template.html")
    assert entry.command == ("npm", "run", "build")
    assert entry.cwd == "web"
    assert {"web/dist/**", "src/template.html"} <= set(loaded.generated_file_patterns())


def test_the_cwd_defaults_to_the_repository_root_for_an_entry_that_is_accepted(
    tmp_path: Path,
) -> None:
    loaded = load(write(tmp_path, [{"paths": ["out/**"], "command": ["make"]}]))

    [entry] = loaded.repos["app"].generated
    assert entry.cwd == "."
    assert "out/**" in loaded.generated_file_patterns()


@pytest.mark.parametrize(
    "bad",
    [
        {**ENTRY, "paths": []},
        {**ENTRY, "command": []},
        {**ENTRY, "cwd": "/abs/place"},
        {**ENTRY, "cwd": "../x"},
        {**ENTRY, "cwd": "web/../../x"},
    ],
    ids=["empty-paths", "empty-command", "absolute-cwd", "leaves-repository", "nested-escape"],
)
def test_a_bad_entry_is_refused_naming_it(tmp_path: Path, bad: dict[str, Any]) -> None:
    message = refusal(write(tmp_path, [ENTRY, bad]))

    assert message != "", "the bad entry loaded without a refusal"
    assert "generated" in message
    assert "1" in message


def test_the_entry_paths_count_as_generated_beside_the_limits_and_lock_files() -> None:
    workspace = WorkspaceConfig.model_validate(
        {
            "global_limits": {"generated_files": ["*.snap"]},
            "repos": {
                "app": {
                    "path": "/work/app",
                    "slug": "example/app",
                    "generated": [ENTRY],
                    "environment": {
                        "sync": ["env-sync"],
                        "check": ["env-check"],
                        "inputs": {"lock": ["web/pins.lockdata"]},
                    },
                }
            },
        }
    )

    patterns = workspace.generated_file_patterns()

    assert {"*.snap", "pins.lockdata", "web/dist/**", "src/template.html"} <= set(patterns)


def test_the_patterns_of_every_repository_are_included() -> None:
    workspace = WorkspaceConfig.model_validate(
        {
            "repos": {
                "app": {
                    "path": "/work/app",
                    "slug": "example/app",
                    "generated": [{"paths": ["a/**"], "command": ["make"]}],
                },
                "platform": {
                    "path": "/work/platform",
                    "slug": "example/platform",
                    "generated": [{"paths": ["b/**"], "command": ["make"]}],
                },
            }
        }
    )

    assert {"a/**", "b/**"} <= set(workspace.generated_file_patterns())


def test_a_unit_size_leaves_out_the_entry_paths() -> None:
    config_module.activate(
        WorkspaceConfig.model_validate(
            {
                "repos": {
                    "app": {
                        "path": "/work/app",
                        "slug": "example/app",
                        "generated": [{"paths": ["web/dist/*"], "command": ["make"]}],
                    }
                }
            }
        )
    )

    lines = actual_lines(
        [
            FileChange(path="src/app.py", additions=12, deletions=3),
            FileChange(path="web/dist/app.js", additions=900, deletions=100),
        ]
    )

    assert lines == 15


def doctor(
    tmp_path: Path,
    entries: list[dict[str, Any]],
    *,
    tracked: tuple[str, ...] = (),
    which: Any = which_all,
) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    for name in tracked:
        (app / name).parent.mkdir(parents=True, exist_ok=True)
        (app / name).write_text("committed\n")
    if tracked:
        git(app, "add", "-A")
        git(app, "commit", "-qm", "tracked")
    repo = RepoConfig.model_validate(
        {"path": app, "slug": "example/app", "changelog": None, "generated": entries}
    )
    (planning / "abk.yaml").write_text(dump(WorkspaceConfig(repos={"app": repo})))
    checks = run_doctor(planning / "abk.yaml", run=Answers(), which=which)
    return [check for check in checks if "generated" in f"{check.name} {check.detail}".lower()]


def test_doctor_lists_each_entry(tmp_path: Path) -> None:
    other = {"paths": ["out/**"], "command": ["make", "all"]}

    found = doctor(tmp_path, [ENTRY, other], tracked=("web/dist/a.js", "out/b.txt"))

    text = " ".join(f"{check.detail}" for check in found)
    assert "npm run build" in text
    assert "make all" in text
    assert all(check.status != "warn" for check in found)


def test_doctor_warns_naming_the_entry_and_a_pattern_that_matches_no_tracked_file(
    tmp_path: Path,
) -> None:
    found = doctor(tmp_path, [ENTRY], tracked=("web/dist/a.js",))

    warnings = [check for check in found if check.status == "warn"]
    assert len(warnings) == 1, f"expected one warning, got {found}"
    [warning] = warnings
    assert "src/template.html" in warning.detail
    assert "web/dist/**" not in warning.detail
    assert "app" in f"{warning.name} {warning.detail}"


def test_doctor_warns_for_a_command_that_is_not_found(tmp_path: Path) -> None:
    def which(name: str) -> str | None:
        return None if name == "npm" else which_all(name)

    found = doctor(tmp_path, [ENTRY], tracked=("web/dist/a.js", "src/template.html"), which=which)

    warnings = [check for check in found if check.status == "warn"]
    assert len(warnings) == 1, f"expected one warning, got {found}"
    [warning] = warnings
    assert "npm" in warning.detail
    assert warning.fix
