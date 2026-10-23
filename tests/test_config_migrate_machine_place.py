"""Where the moved lines go in the local text, and that the existing steps run first."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config_migrate import migrate
from agent_build_kit.config_migrate_machine import move_machine_settings
from tests.config_migrate_machine_support import merged, request

APP = "repos:\n  app:\n    slug: example/app\n    path: ../app\n"


def test_a_setting_is_added_to_its_entry_in_the_local_block(tmp_path: Path) -> None:
    local = "repos:\n  app:\n    account: personal\n"

    result = move_machine_settings(APP, request(tmp_path, local))

    assert result.local_text == "repos:\n  app:\n    account: personal\n    path: ../app\n"
    assert result.text == "repos:\n  app:\n    slug: example/app\n"
    assert merged(result.text, result.local_text) == merged(APP, local)


def test_a_missing_parent_is_written_once_for_settings_that_share_it(tmp_path: Path) -> None:
    base = (
        "repos:\n  app:\n    slug: example/app\n    path: ../app\n"
        "    deploy:\n      ssh_key: /opt/key\n"
        "  platform:\n    slug: example/platform\n    path: ../platform\n"
    )
    local = "other: 1\n"

    result = move_machine_settings(base, request(tmp_path, local))

    assert result.local_text == (
        "other: 1\nrepos:\n  app:\n    path: ../app\n    deploy:\n      ssh_key: /opt/key\n"
        "  platform:\n    path: ../platform\n"
    )
    assert merged(result.text, result.local_text) == merged(base, local)


def test_a_local_text_of_only_comments_gets_the_lines_appended(tmp_path: Path) -> None:
    local = "# my machine\n"

    result = move_machine_settings(APP, request(tmp_path, local))

    assert result.local_text == "# my machine\nrepos:\n  app:\n    path: ../app\n"


def test_a_crlf_text_without_a_final_newline_gives_a_crlf_local_text(tmp_path: Path) -> None:
    base = "repos:\r\n  app:\r\n    slug: example/app\r\n    path: ../app"

    result = move_machine_settings(base, request(tmp_path))

    assert result.text == "repos:\r\n  app:\r\n    slug: example/app"
    assert result.local_text is not None
    assert result.local_text.startswith("repos:\r\n  app:\r\n    path: ../app")
    assert "\n" not in result.local_text.replace("\r\n", "")


def test_the_existing_steps_run_first_and_their_project_limits_are_moved(tmp_path: Path) -> None:
    base = (
        "limits:\n  max_concurrent_stacks: 2\n  max_units_in_progress: 3\n"
        "  max_concurrent_restacks: 1\n  max_failures: 2\n"
    )

    result = migrate(base, machine=request(tmp_path))

    assert result.text == "global_limits:\n  max_failures: 2\n"
    assert result.moved == (
        "max_concurrent_stacks",
        "max_units_in_progress",
        "max_concurrent_restacks",
    )
    assert result.machine_moved == (("project_limits",),)
    assert result.local_text == (
        "project_limits:\n  max_concurrent_stacks: 2\n  max_units_in_progress: 3\n"
        "  max_concurrent_restacks: 1\n"
    )
