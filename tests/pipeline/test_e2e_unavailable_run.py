"""An e2e run and the post-merge verification leave out the tests of an unavailable value's
marker, with nothing held and no split run alone (spec: e2e-dimensions)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.verify import verify_change
from tests.conftest import make_installation
from tests.e2e_scope_fakes import PASSED, Ran, branch
from tests.e2e_scope_fakes import session as shared_session
from tests.factories import stored_unit
from tests.pipeline.test_verify import Host

LIVE = "svc-a/tests/integration/test_drive_live_stack.py"
DIMENSIONS = {
    "telemetry": {"otel": {"marker": "telemetry_otel"}, "local": {"marker": "telemetry_local"}}
}


def expression_of(command: list[str] | tuple[str, ...]) -> str:
    return command[list(command).index("-m") + 1]


def test_a_run_with_nothing_held_leaves_out_the_unavailable_marker(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {"tests/live/test_a.py": "def test_a():\n    pass\n"})
    ran = Ran(PASSED)

    shared_session(tmp_path, ran, unavailable=["telemetry_otel"]).run(cwd=repo, base=base)

    [command] = [c for c in ran.commands if "-m" in c]
    assert "not telemetry_otel" in expression_of(command)


def test_a_run_with_everything_available_keeps_the_bare_marker(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {"tests/live/test_a.py": "def test_a():\n    pass\n"})
    ran = Ran(PASSED)

    shared_session(tmp_path, ran).run(cwd=repo, base=base)

    assert all("telemetry_otel" not in " ".join(c) for c in ran.commands)


def test_the_verification_leaves_out_the_unavailable_marker(tmp_path: Path) -> None:
    checkout = tmp_path / "checkouts" / "platform"
    inst: Installation = make_installation(
        tmp_path,
        tests={"e2e_dimensions": DIMENSIONS, "e2e_available": {"telemetry": ["local"]}},
        repos={"platform": {"path": str(checkout), "slug": "example/platform"}},
    )
    (checkout / "svc-a").mkdir(parents=True)
    (checkout / "svc-a" / "pyproject.toml").write_text('[project]\nname = "svc-a"\n')
    (checkout / LIVE).parent.mkdir(parents=True)
    (checkout / LIVE).touch()
    (checkout / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["svc-a"]\n')
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host = Host()

    verify_change(
        "c",
        [stored_unit("c/1", change="c", repo="platform", state="merged", pr=30)],
        installation=inst,
        pr_files=lambda repo, pr: [LIVE],
        run=host,
        env={},
    )

    runs = [c for _, c, _ in host.calls if "pytest" in c and "-m" in c]
    assert runs
    assert all("not telemetry_otel" in expression_of(c) for c in runs)
