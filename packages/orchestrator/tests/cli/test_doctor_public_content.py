"""`abk doctor`'s `public content` check: a committed abk.yaml that carries
facts a public repository must not, found offline from the committed text."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig
from tests.cli.public_content_repo import planning, public_content, said
from tests.forges.mock_host import MockHost, ok

# Assembled, so that this file does not itself look like a leaked path.
HOME = "/" + "home" + "/someone"
HOME_FILE = {"from": "env-file", "file": f"{HOME}/.config/svc/token.env", "key": "TOKEN"}


def env_file(path: str) -> dict[str, str]:
    return dict(HOME_FILE, file=path)


def inside(name: str = "app", slug: str = "example/app") -> dict[str, RepoConfig]:
    return {name: RepoConfig(path=Path(name), slug=slug, changelog=None)}


def test_a_repo_path_outside_the_checkout_warns_naming_the_key_not_the_value(
    tmp_path: Path,
) -> None:
    (tmp_path / "sibling-checkout").mkdir()
    # Relative to the planning root: an absolute `tmp_path` under the home directory would also
    # read as a home-directory path, and the check would warn of that as well.
    config = planning(
        tmp_path / "plan",
        repos={
            "app": RepoConfig(path=Path("../sibling-checkout"), slug="example/app", changelog=None)
        },
    )

    found = public_content(config)

    assert [c.status for c in found] == ["warn"]
    assert "repos.app.path" in said(found[0])
    assert "sibling-checkout" not in said(found[0])
    assert ".env" in said(found[0])


def test_a_home_path_in_a_value_warns_naming_the_key_not_the_value(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", verify_env={"TOKEN": HOME_FILE})

    found = public_content(config)

    assert [c.status for c in found] == ["warn"]
    assert "verify.env.TOKEN.file" in said(found[0])
    assert HOME not in said(found[0])


def test_a_repo_owned_by_another_account_than_the_origin_warns_naming_the_entry(
    tmp_path: Path,
) -> None:
    (tmp_path / "plan" / "app").mkdir(parents=True)
    config = planning(tmp_path / "plan", repos=inside(slug="elsewhere/app"))

    found = public_content(config)

    assert [c.status for c in found] == ["warn"]
    assert "app" in said(found[0])
    assert "elsewhere" not in said(found[0])


def test_the_owner_is_compared_without_regard_to_case(tmp_path: Path) -> None:
    (tmp_path / "plan" / "app").mkdir(parents=True)
    config = planning(tmp_path / "plan", repos=inside(slug="EXAMPLE/app"))

    assert [c.status for c in public_content(config)] == ["ok"]


def test_the_checkouts_own_entry_with_the_origins_owner_is_ok(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan")

    assert [c.status for c in public_content(config)] == ["ok"]


def test_a_checkout_entry_is_exempt_from_the_owner_comparison(tmp_path: Path) -> None:
    config = planning(
        tmp_path / "plan",
        repos={"app": RepoConfig(path=Path("."), slug="elsewhere/app", changelog=None)},
    )

    assert [c.status for c in public_content(config)] == ["ok"]


def test_an_untracked_abk_yaml_is_ok_and_says_so(tmp_path: Path) -> None:
    config = planning(
        tmp_path / "plan",
        verify_env={"TOKEN": HOME_FILE},
        tracked=False,
        ignore="abk.yaml\n",
    )

    found = public_content(config)

    assert [c.status for c in found] == ["ok"]
    assert "not tracked" in found[0].detail


def test_a_root_that_is_not_a_repository_is_ok(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", verify_env={"TOKEN": HOME_FILE}, repository=False)

    assert [c.status for c in public_content(config)] == ["ok"]


def test_no_origin_skips_only_the_owner_finding(tmp_path: Path) -> None:
    (tmp_path / "plan" / "app").mkdir(parents=True)
    owner_only = planning(tmp_path / "plan", repos=inside(slug="elsewhere/app"), origin=None)
    assert [c.status for c in public_content(owner_only)] == ["ok"]

    config = planning(tmp_path / "other", verify_env={"TOKEN": HOME_FILE}, origin=None)
    found = public_content(config)
    assert [c.status for c in found] == ["warn"]
    assert "verify.env.TOKEN.file" in said(found[0])


def test_the_check_reaches_the_host_no_more_than_the_rest_of_doctor_does(
    tmp_path: Path,
) -> None:
    """The same installation, tracked and not: the extra findings come with
    no extra request."""
    (tmp_path / "a" / "app").mkdir(parents=True)
    (tmp_path / "b" / "app").mkdir(parents=True)
    tracked_host = MockHost(ok({"login": "example"}))
    untracked_host = MockHost(ok({"login": "example"}))
    findings = planning(
        tmp_path / "a", repos=inside(slug="elsewhere/app"), verify_env={"TOKEN": HOME_FILE}
    )
    silent = planning(
        tmp_path / "b",
        repos=inside(slug="elsewhere/app"),
        verify_env={"TOKEN": HOME_FILE},
        tracked=False,
        ignore="abk.yaml\n",
    )

    flagged = public_content(findings, transport=tracked_host)
    quiet = public_content(silent, transport=untracked_host)

    assert [c.status for c in flagged] == ["warn", "warn"]
    assert [c.status for c in quiet] == ["ok"]
    assert [r.url for r in tracked_host.requests] == [r.url for r in untracked_host.requests]


def test_a_repo_only_the_local_overlay_adds_is_not_judged(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore="abk.local.yaml\n")
    (config.parent / "abk.local.yaml").write_text(
        "repos:\n  platform:\n    path: platform\n    slug: elsewhere/app\n"
    )
    (config.parent / "platform").mkdir()

    assert [c.status for c in public_content(config)] == ["ok"]


def test_a_home_directory_of_slash_matches_no_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/")))
    config = planning(tmp_path / "plan", verify_env={"TOKEN": env_file("/srv/token.env")})

    assert [c.status for c in public_content(config)] == ["ok"]


def test_a_home_directory_is_matched_as_a_path_prefix_not_a_substring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/srv/runner")))
    config = planning(
        tmp_path / "plan",
        verify_env={
            "A": env_file("/srv/runner-cache/a.env"),
            "B": env_file("/srv/runner/b.env"),
        },
    )

    found = public_content(config)

    assert [c.status for c in found] == ["warn"]
    assert "verify.env.B.file" in said(found[0])
