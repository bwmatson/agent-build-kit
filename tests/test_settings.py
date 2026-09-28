"""Machine-level settings: the environment, and the planning repo's .env."""

from pathlib import Path

from agent_build_kit.settings import Settings, reload, settings


def test_defaults_need_no_environment() -> None:
    fresh = Settings(_env_file=None)
    assert fresh.config is None
    assert fresh.gh_token == ""
    assert fresh.openspec_version
    assert fresh.implement_model is None


def test_the_github_token_is_read_under_its_conventional_name(monkeypatch) -> None:
    # `GH_TOKEN`, as gh itself reads it — not only the prefixed form.
    monkeypatch.setenv("GH_TOKEN", "ghp_x")
    assert Settings(_env_file=None).gh_token == "ghp_x"


def test_framework_settings_take_the_prefix(monkeypatch) -> None:
    monkeypatch.setenv("ABK_OPENSPEC_VERSION", "9.9.9")
    monkeypatch.setenv("ABK_REVIEW_MODEL", "sonnet")
    fresh = Settings(_env_file=None)
    assert fresh.openspec_version == "9.9.9"
    assert fresh.review_model == "sonnet"


def test_reload_reads_the_planning_repo_s_env_file_in_place(tmp_path: Path, monkeypatch) -> None:
    # Every importer holds the same object, so it is updated rather than
    # replaced.
    monkeypatch.delenv("GH_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("GH_TOKEN=from-file\n")
    before = settings

    reload(env)
    try:
        assert settings is before
        assert settings.gh_token == "from-file"
    finally:
        reload(None)
    assert settings.gh_token == ""
