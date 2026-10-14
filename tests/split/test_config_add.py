"""A repo's block is spliced into the destination's abk.yaml as text, and checked."""

import pytest
import yaml

from agent_build_kit.split.config_edit import ConfigEditError, add_repo_entry

APP_BLOCK = """\
  app:
    # where the app lives
    path: /x/app
    slug: example/app
"""

SOURCE = f"""\
# The workspace.
repos:
  lib:
    path: /x/lib
    slug: example/lib
{APP_BLOCK}  svc:
    path: /x/svc
    slug: example/svc
    consumes:
      - lib
      - other
limits:
  max_concurrent_stacks: 2
"""

DESTINATION = """\
repos:
    lib:
        path: /y/lib
        slug: example/lib

limits:
    max_concurrent_stacks: 1
"""


def files(tmp_path, source=SOURCE, destination=DESTINATION):
    (tmp_path / "source-abk.yaml").write_text(source)
    (tmp_path / "abk.yaml").write_text(destination)
    return tmp_path / "source-abk.yaml", tmp_path / "abk.yaml"


def test_the_block_is_spliced_after_the_last_repo_with_the_destinations_indentation(tmp_path):
    source, destination = files(tmp_path)

    result = add_repo_entry(source, destination, "app")

    assert result.written and not result.already_declared
    assert destination.read_text() == (
        "repos:\n"
        "    lib:\n"
        "        path: /y/lib\n"
        "        slug: example/lib\n"
        "    app:\n"
        "        # where the app lives\n"
        "        path: /x/app\n"
        "        slug: example/app\n"
        "\n"
        "limits:\n"
        "    max_concurrent_stacks: 1\n"
    )
    parsed = yaml.safe_load(destination.read_text())["repos"]["app"]
    assert parsed == yaml.safe_load(SOURCE)["repos"]["app"]


def test_a_repo_already_declared_is_left_and_reported(tmp_path):
    source, destination = files(tmp_path)

    result = add_repo_entry(source, destination, "lib")

    assert result.already_declared and not result.written
    assert destination.read_text() == DESTINATION
    assert not destination.with_name("abk.yaml.abk-backup").exists()


def test_a_consumed_repo_the_destination_lacks_is_listed(tmp_path):
    source, destination = files(tmp_path)

    planned = add_repo_entry(source, destination, "svc", write=False)

    assert planned.missing_consumes == ("other",)
    assert not planned.written
    assert destination.read_text() == DESTINATION


def test_the_original_is_backed_up_once(tmp_path):
    source, destination = files(tmp_path)

    add_repo_entry(source, destination, "app")
    add_repo_entry(source, destination, "svc")

    backup = destination.with_name("abk.yaml.abk-backup")
    assert backup.read_text() == DESTINATION
    assert set(yaml.safe_load(destination.read_text())["repos"]) == {"lib", "app", "svc"}


@pytest.mark.parametrize(
    ("source_text", "destination_text"),
    [
        (SOURCE.replace(APP_BLOCK, "  app: {path: /x/app, slug: example/app}\n"), DESTINATION),
        (SOURCE, "repos: {lib: {path: /y/lib, slug: example/lib}}\n"),
    ],
)
def test_a_layout_the_splice_cannot_follow_is_refused_and_nothing_is_written(
    tmp_path, source_text, destination_text
):
    source, destination = files(tmp_path, source_text, destination_text)

    with pytest.raises(ConfigEditError) as refused:
        add_repo_entry(source, destination, "app")

    assert "app" in str(refused.value)
    assert source.name in str(refused.value) or destination.name in str(refused.value)
    assert destination.read_text() == destination_text
    assert sorted(p.name for p in tmp_path.iterdir()) == ["abk.yaml", "source-abk.yaml"]
