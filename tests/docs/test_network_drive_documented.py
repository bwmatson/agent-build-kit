"""The configuration document and the changelog describe running with the state on a network
drive (spec: state-locking-on-a-share)."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed, unreleased_bullets


def section() -> str:
    """The `Network drive` section of the configuration document, up to the next heading of its
    level or above."""
    text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    match = re.search(r"^(#{2,4}) Network drive\s*$", text, re.M)
    assert match, "docs/configuration.md has no `Network drive` section"
    rest = text[match.end() :]
    following = re.search(rf"^#{{1,{len(match.group(1))}}} ", rest, re.M)
    return squashed(rest[: following.start() if following else None])


def test_the_section_follows_where_an_installations_facts_live() -> None:
    text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")

    assert text.index("### Where an installation's facts live") < text.index("Network drive\n")


def test_the_section_says_one_pipeline_host_is_supported_and_two_are_not() -> None:
    text = section()

    assert re.search(r"one pipeline host", text, re.I)
    assert re.search(r"two (pipeline )?hosts[^.]{0,80}(not supported|unsupported)", text, re.I)


def test_the_section_names_the_settings_the_doctor_and_the_probe() -> None:
    text = section()

    for name in (
        "planning.state_dir",
        "planning.local_dir",
        "ABK_LOCAL_DIR",
        "ABK_LOCK_WAIT_SECONDS",
        "abk doctor",
        "probe",
    ):
        assert name in text, name


def test_the_section_lists_the_mounts_considered() -> None:
    text = section()

    assert re.search(r"NFS[^.]{0,80}(lockd|local_lock=all)", text)
    assert re.search(r"SMB[^.]{0,80}nobrl", text)
    assert "drvfs" in text


def test_the_section_says_the_local_directory_stays_on_local_disk() -> None:
    assert re.search(r"local directory[^.]{0,120}local disk", section(), re.I)


def test_the_changelog_names_the_local_directory_and_the_lock_probe() -> None:
    bullets = unreleased_bullets()

    assert any("planning.local_dir" in b and re.search(r"lock probe", b, re.I) for b in bullets)
