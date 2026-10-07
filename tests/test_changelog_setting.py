"""The per-repo `changelog` setting: a path, the default, or off."""

from pathlib import Path

from agent_build_kit.config import RepoConfig, load


def load_repo(tmp_path: Path, setting: str) -> RepoConfig:
    path = tmp_path / "abk.yaml"
    path.write_text(
        f"repos:\n  app:\n    path: {tmp_path / 'app'}\n    slug: example/app\n{setting}"
    )
    return load(path).repos["app"]


def test_the_changelog_defaults_to_changelog_md(tmp_path: Path) -> None:
    assert load_repo(tmp_path, "").changelog == "CHANGELOG.md"


def test_a_path_loads_as_the_repos_changelog(tmp_path: Path) -> None:
    assert load_repo(tmp_path, "    changelog: docs/HISTORY.md\n").changelog == "docs/HISTORY.md"


def test_null_loads_as_off(tmp_path: Path) -> None:
    assert load_repo(tmp_path, "    changelog: null\n").changelog is None
