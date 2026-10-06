"""Which command records the live stack beside a tier 2 result: the config's
when it says, the repo's profile's when it does not, nothing when told so."""

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import VerifyConfig, WorkspaceConfig, load, stack_versions_for
from agent_build_kit.profiles.python_uv import PythonUvProfile

CONTAINER_LISTING = ("docker", "ps", "--format", "{{.Names}}\t{{.Image}}")


class _Profile(PythonUvProfile):
    """A toolchain differing from python-uv only in its stack-versions command."""

    def __init__(self, command: tuple[str, ...] | None) -> None:
        self.stack_versions_command = command


def _verify(tmp_path: Path, lines: str) -> VerifyConfig:
    path = tmp_path / "abk.yaml"
    path.write_text(
        "repos:\n  app:\n    path: /tmp/app\n    slug: example/app\n" + lines,
    )
    config: WorkspaceConfig = load(path)
    return config.verify


def test_an_absent_key_uses_the_profiles_command() -> None:
    profile = _Profile(("podman", "ps"))

    assert stack_versions_for(VerifyConfig(), profile) == ["podman", "ps"]


def test_a_list_in_config_overrides_the_profile() -> None:
    verify = VerifyConfig(stack_versions_command=["kubectl", "get", "pods"])

    assert stack_versions_for(verify, _Profile(("podman", "ps"))) == ["kubectl", "get", "pods"]


def test_an_explicit_null_records_nothing() -> None:
    verify = VerifyConfig(stack_versions_command=None)

    assert stack_versions_for(verify, _Profile(("podman", "ps"))) is None


def test_a_profile_with_no_command_records_nothing_by_default() -> None:
    assert stack_versions_for(VerifyConfig(), _Profile(None)) is None


def test_the_built_in_profiles_keep_the_container_listing_command() -> None:
    for name in ("python-uv", "node-npm"):
        assert profiles.get(name).stack_versions_command == CONTAINER_LISTING


def test_a_config_with_the_key_absent_listed_or_null_loads_three_distinct_values(
    tmp_path: Path,
) -> None:
    absent = _verify(tmp_path, "")
    listed = _verify(tmp_path, "verify:\n  stack_versions_command: [docker, ps]\n")
    null = _verify(tmp_path, "verify:\n  stack_versions_command: null\n")

    assert listed.stack_versions_command == ["docker", "ps"]
    assert null.stack_versions_command is None
    assert absent.stack_versions_command not in (None, ["docker", "ps"])
    profile = _Profile(("podman", "ps"))
    assert stack_versions_for(absent, profile) == ["podman", "ps"]
    assert stack_versions_for(listed, profile) == ["docker", "ps"]
    assert stack_versions_for(null, profile) is None
