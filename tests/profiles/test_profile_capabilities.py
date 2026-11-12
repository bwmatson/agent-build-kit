"""Every registered toolchain profile provides every capability the framework branches on
(spec: profile-capability-parity).

The registry cases are conformance tests (integration kind); the rest run the same check over
temporary profiles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from agent_build_kit import profiles
from agent_build_kit.profiles.base import (
    RepeatsTests,
    RerunsFailedTests,
    SelectsAffectedTests,
    SelectsByKind,
    ToolchainProfile,
)
from agent_build_kit.profiles.capabilities import (
    CAPABILITIES,
    GAP_BASELINE,
    capability_problems,
    selector_problems,
)

PYTHON_PROJECT = {
    "pyproject.toml": (
        "[tool.pytest.ini_options]\n"
        "markers = [\n"
        '    "integration: runs in CI",\n'
        '    "e2e: needs the live stack",\n'
        '    "time_limit(seconds): a limit of its own",\n'
        "]\n"
        "addopts = \"--strict-markers -m 'not integration and not e2e'\"\n"
    ),
    "tests/test_a.py": "def test_a():\n    pass\n",
    "tests/test_b.py": "import pytest\n\n\n@pytest.mark.integration\ndef test_b():\n    pass\n",
}
NODE_PROJECT = {
    "package.json": '{"name": "app", "version": "0.1.0"}\n',
    "vitest.config.ts": (
        'import { defineConfig } from "vitest/config";\n\n'
        "export default defineConfig({\n"
        "  test: {\n"
        '    include: ["src/**/*.test.ts"],\n'
        '    exclude: ["**/*.integration.test.ts", "**/*.e2e.test.ts"],\n'
        "    testTimeout: 5000,\n"
        "  },\n"
        "});\n"
    ),
    "src/a.test.ts": "",
    "src/b.integration.test.ts": "",
    "src/c.e2e.test.ts": "",
}
PROJECTS = {"python-uv": PYTHON_PROJECT, "node-npm": NODE_PROJECT}


def project(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return root


def selecting(name: str) -> SelectsByKind:
    profile = profiles.get(name)
    assert isinstance(profile, SelectsByKind)
    return profile


def registry() -> dict[str, ToolchainProfile]:
    return {name: profiles.get(name) for name in profiles.names()}


class Bare:
    """A profile that provides none of the optional capabilities."""

    name = "bare"


@runtime_checkable
class NewHook(Protocol):
    def new_hook(self) -> None: ...


@pytest.mark.integration
def test_every_registered_profile_provides_every_capability_or_is_in_the_baseline() -> None:
    assert capability_problems(registry()) == []


@pytest.mark.integration
def test_every_registered_profile_has_a_fixture_for_the_selector_cases() -> None:
    assert set(profiles.names()) <= set(PROJECTS)


@pytest.mark.integration
def test_the_baseline_names_only_registered_profiles_and_known_capabilities() -> None:
    capabilities = {c.__name__ for c in CAPABILITIES}
    unknown = {
        (p, c) for p, c in GAP_BASELINE if p not in profiles.names() or c not in capabilities
    }
    assert unknown == set()


@pytest.mark.integration
@pytest.mark.parametrize("name", sorted(PROJECTS))
def test_every_profile_provides_the_six_selector_capabilities(name: str, tmp_path: Path) -> None:
    root = project(tmp_path, PROJECTS[name])
    files = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]
    assert selector_problems(profiles.get(name), root, files) == []


@pytest.mark.integration
@pytest.mark.parametrize("name", sorted(PROJECTS))
def test_a_profile_declares_both_kinds_leaves_them_out_and_overrides_by_id(
    name: str, tmp_path: Path
) -> None:
    root = project(tmp_path, PROJECTS[name])
    profile = selecting(name)
    assert {"integration", "e2e"} <= set(profile.declared_kinds(root))
    assert set(profile.default_run_leaves_out(root)) == {"integration", "e2e"}
    assert profile.by_id_overrides_default(root) is True
    assert profile.per_test_limit_option(root)


@pytest.mark.integration
@pytest.mark.parametrize("name", sorted(PROJECTS))
def test_a_profile_refuses_an_unknown_kind_and_accepts_the_declared_ones(
    name: str, tmp_path: Path
) -> None:
    root = project(tmp_path, PROJECTS[name])
    refused = selecting(name).refused_kinds(root, ["integration", "e2e", "serial", "bogus"])
    assert refused == ["serial", "bogus"]


@pytest.mark.integration
def test_a_profile_missing_a_capability_fails_naming_both() -> None:
    problems = capability_problems({"bare": Bare()}, baseline=frozenset())  # type: ignore[dict-item]
    assert any("bare" in p and "RepeatsTests" in p for p in problems)
    assert any("bare" in p and "SelectsByKind" in p for p in problems)


@pytest.mark.integration
def test_the_serial_rerun_and_failed_test_methods_are_a_protocol() -> None:
    assert RerunsFailedTests in CAPABILITIES
    assert isinstance(profiles.get("python-uv"), RerunsFailedTests)
    assert not isinstance(Bare(), RerunsFailedTests)


@pytest.mark.integration
def test_a_new_capability_protocol_fails_until_every_profile_implements_it() -> None:
    problems = capability_problems(
        registry(), capabilities=(*CAPABILITIES, NewHook), baseline=GAP_BASELINE
    )
    for name in profiles.names():
        assert any(name in p and "NewHook" in p for p in problems)


@pytest.mark.integration
def test_the_baseline_refuses_a_new_entry() -> None:
    # The profile lacks the capability and the entry lists it, so only the new-entry branch fires.
    problems = capability_problems(
        {"bare": Bare()},  # type: ignore[dict-item]
        capabilities=(RepeatsTests,),
        baseline=frozenset({("bare", "RepeatsTests")}),
    )
    assert any("is new" in p and "bare" in p and "RepeatsTests" in p for p in problems)
    assert not any("provide" in p for p in problems)


@pytest.mark.integration
def test_the_baseline_names_no_capability_a_profile_has_since_filled() -> None:
    problems = capability_problems(
        registry(), baseline=GAP_BASELINE | {("python-uv", "RerunsFailedTests")}
    )
    assert any(
        "python-uv" in p and "RerunsFailedTests" in p and "now provides" in p for p in problems
    )


def test_node_provides_the_serial_rerun_and_affected_selection_so_the_baseline_drops_them() -> None:
    node = profiles.get("node-npm")
    assert isinstance(node, RerunsFailedTests)
    assert isinstance(node, SelectsAffectedTests)
    assert ("node-npm", "RerunsFailedTests") not in GAP_BASELINE
    assert ("node-npm", "SelectsAffectedTests") not in GAP_BASELINE
