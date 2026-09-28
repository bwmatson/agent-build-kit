"""Deploy a merged change and check it against the live stack, before archive.

A pipeline that stops at merge leaves deploys to whoever remembers them, and
nothing looks at the live system afterwards: a change once merged and archived
while its consumer could not see a single one of the tools it added.
"""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import DeployConfig, DeployRule, RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.verify import deploy_commands, live_credentials, verify_change
from tests.conftest import make_installation
from tests.factories import stored_unit

PY = profiles.get("python-uv")


def repo_config(tmp_path: Path, rules: list[DeployRule], **deploy) -> RepoConfig:
    return RepoConfig(
        path=tmp_path,
        slug="example/platform",
        deploy=DeployConfig(rules=rules, **deploy),
    )


def _member(checkout: Path, directory: str, package: str, *deps: str) -> None:
    (checkout / directory).mkdir(parents=True, exist_ok=True)
    dependencies = ", ".join(f'"{dep}"' for dep in deps)
    (checkout / directory / "pyproject.toml").write_text(
        f'[project]\nname = "{package}"\ndependencies = [{dependencies}]\n'
    )


def _workspace(checkout: Path, members: list[str]) -> None:
    quoted = ", ".join(f'"{m}"' for m in members)
    (checkout / "pyproject.toml").write_text(f"[tool.uv.workspace]\nmembers = [{quoted}]\n")


# --- what to deploy -----------------------------------------------------------


def test_a_rule_s_commands_run_for_a_path_under_its_prefix(tmp_path: Path) -> None:
    repo = repo_config(
        tmp_path, [DeployRule(prefix="svc-a/", run=[["scripts/deploy.sh", "svc-a"]])]
    )

    assert deploy_commands(repo, ["svc-a/src/main.py"], checkout=tmp_path) == [
        ("scripts/deploy.sh", "svc-a")
    ]


def test_each_command_runs_once_in_the_order_first_needed(tmp_path: Path) -> None:
    repo = repo_config(
        tmp_path,
        [
            DeployRule(prefix="svc-a/", run=[["deploy", "a"]]),
            DeployRule(prefix="svc-b/", run=[["deploy", "b"]]),
        ],
    )
    commands = deploy_commands(repo, ["svc-a/a.py", "svc-b/b.py", "svc-a/c.py"], checkout=tmp_path)

    assert commands == [("deploy", "a"), ("deploy", "b")]


def test_first_matching_rule_wins(tmp_path: Path) -> None:
    repo = repo_config(
        tmp_path,
        [
            DeployRule(prefix="svc-a/config/", run=[["reload", "a"]]),
            DeployRule(prefix="svc-a/", run=[["deploy", "a"]]),
        ],
    )

    assert deploy_commands(repo, ["svc-a/config/x.yaml"], checkout=tmp_path) == [("reload", "a")]


def test_a_file_prefix_matches_that_file(tmp_path: Path) -> None:
    repo = repo_config(tmp_path, [DeployRule(prefix="compose.yml", run=[["up"]])])

    assert deploy_commands(repo, ["compose.yml"], checkout=tmp_path) == [("up",)]
    assert deploy_commands(repo, ["compose.yml.bak"], checkout=tmp_path) == [("up",)]  # startswith


def test_test_and_doc_paths_deploy_nothing_by_convention(tmp_path: Path) -> None:
    # No `<svc>/tests/ -> []` rule needed: the profile knows a test path, and
    # documentation never changes what runs.
    repo = repo_config(tmp_path, [DeployRule(prefix="svc-a/", run=[["deploy", "a"]])])

    paths = [
        "svc-a/tests/test_x.py",
        "svc-a/README.md",
        "docs/guide.md",
        "LICENSE",
        "svc-a/conftest.py",
    ]
    assert deploy_commands(repo, paths, checkout=tmp_path) == []


def test_a_library_change_redeploys_the_members_that_depend_on_it(tmp_path: Path) -> None:
    # `shared` is a workspace member two services declare as a dependency and
    # one does not: the change reaches the two, and only the two.
    _workspace(tmp_path, ["shared", "svc-a", "svc-b", "svc-c"])
    _member(tmp_path, "shared", "shared")
    _member(tmp_path, "svc-a", "svc-a", "shared[http]>=1")
    _member(tmp_path, "svc-b", "svc-b", "shared")
    _member(tmp_path, "svc-c", "svc-c", "requests")
    repo = repo_config(
        tmp_path,
        [
            DeployRule(prefix="svc-a/", run=[["deploy", "a"]]),
            DeployRule(prefix="svc-b/", run=[["blue-green", "b"]]),
            DeployRule(prefix="svc-c/", run=[["deploy", "c"]]),
        ],
    )

    assert deploy_commands(repo, ["shared/shared/models.py"], checkout=tmp_path) == [
        ("deploy", "a"),
        ("blue-green", "b"),
    ]


def test_an_explicit_rule_for_the_library_still_applies(tmp_path: Path) -> None:
    _workspace(tmp_path, ["shared", "svc-a"])
    _member(tmp_path, "shared", "shared")
    _member(tmp_path, "svc-a", "svc-a", "shared")
    repo = repo_config(
        tmp_path,
        [
            DeployRule(prefix="shared/", run=[["rebuild", "all"]]),
            DeployRule(prefix="svc-a/", run=[["deploy", "a"]]),
        ],
    )

    assert deploy_commands(repo, ["shared/x.py"], checkout=tmp_path) == [
        ("rebuild", "all"),
        ("deploy", "a"),
    ]


def test_an_unmatched_path_deploys_nothing(tmp_path: Path) -> None:
    repo = repo_config(tmp_path, [DeployRule(prefix="svc-a/", run=[["deploy", "a"]])])

    assert deploy_commands(repo, ["scripts/x.sh", "svc-z/y.py"], checkout=tmp_path) == []


# --- credentials ---------------------------------------------------------------------


def test_credentials_are_the_ones_the_repo_s_live_stack_tests_read(tmp_path: Path) -> None:
    # One list, kept by the repo's own dev stack script for its own `test`.
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "dev-stack.sh").write_text(
        "OTHER=(x)\nTEST_CREDENTIALS=(GATEWAY_MASTER_KEY BROWSER_API_KEY)\n"
    )
    (tmp_path / ".env").write_text(
        'GATEWAY_MASTER_KEY="sk-master"\nBROWSER_API_KEY=sb\nOTHER_SECRET=nope\n'
    )
    repo = RepoConfig.model_validate(
        {
            "path": str(tmp_path),
            "slug": "example/platform",
            "deploy": {
                "credentials": {
                    "names_from": {
                        "file": "scripts/dev-stack.sh",
                        "shell_array": "TEST_CREDENTIALS",
                    },
                    "values_from": ".env",
                }
            },
        }
    )

    assert live_credentials(repo, tmp_path) == {
        "GATEWAY_MASTER_KEY": "sk-master",
        "BROWSER_API_KEY": "sb",
    }


def test_no_credentials_configured_means_none(tmp_path: Path) -> None:
    assert live_credentials(repo_config(tmp_path, []), tmp_path) == {}


# --- the whole step ---------------------------------------------------------------------


class Host:
    """Records every command with where it ran and what it was given; the
    checkouts are clean and on main unless told otherwise."""

    def __init__(self, *, dirty: str = "", branch: str = "main", failing: str = "") -> None:
        self.calls: list[tuple[str, tuple[str, ...], dict]] = []
        self.dirty, self.branch, self.failing = dirty, branch, failing

    def __call__(self, command, *, cwd, env=None, **kwargs):
        self.calls.append((Path(cwd).name, tuple(command), env or {}))
        out, code = "", 0
        if command[:2] == ["git", "status"]:
            excluded = [a.removeprefix(":(exclude)") for a in command if a.startswith(":(exclude)")]
            out = "\n".join(
                line
                for line in self.dirty.splitlines()
                if not any(line[3:].startswith(e) for e in excluded)
            )
        elif command[:2] == ["git", "rev-parse"]:
            out = self.branch
        elif self.failing and self.failing in " ".join(command):
            out, code = "1 failed in 2.00s\nAssertionError: no tools", 1
        return subprocess.CompletedProcess(command, code, out, "")

    def ran(self) -> list[tuple[str, tuple[str, ...]]]:
        return [(where, command) for where, command, _ in self.calls]


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    """`app` consumes `platform`; platform has a service with a rule and a
    live-stack test; app builds inside an ssh-agent."""
    installation = make_installation(
        tmp_path,
        repos={
            "platform": {
                "path": str(tmp_path / "checkouts" / "platform"),
                "slug": "example/platform",
                "deploy": {
                    "rules": [
                        {"prefix": "svc-a/", "run": [["scripts/deploy.sh", "svc-a"]]},
                        {
                            "prefix": "gateway/",
                            "run": [["docker", "compose", "restart", "gateway"]],
                        },
                    ],
                    "credentials": {
                        "names_from": {
                            "file": "scripts/dev-stack.sh",
                            "shell_array": "TEST_CREDENTIALS",
                        }
                    },
                },
            },
            "app": {
                "path": str(tmp_path / "checkouts" / "app"),
                "slug": "example/app",
                "consumes": ["platform"],
                "deploy": {
                    "needs_ssh_agent": True,
                    "ssh_key": str(tmp_path / "keys" / "deploy"),
                    "live_written": ["notes"],
                    "rules": [
                        {"prefix": "worker/", "run": [["scripts/deploy-blue-green.sh", "worker"]]}
                    ],
                },
            },
        },
    )
    for name in ("platform", "app"):
        checkout = tmp_path / "checkouts" / name
        (checkout / "scripts").mkdir(parents=True)
        (checkout / "scripts" / "dev-stack.sh").write_text(
            "TEST_CREDENTIALS=(GATEWAY_MASTER_KEY)\n"
        )
        (checkout / ".env").write_text("GATEWAY_MASTER_KEY=sk-master\n")
    platform = tmp_path / "checkouts" / "platform"
    _member(platform, "svc-a", "svc-a")
    (platform / "svc-a" / "tests" / "integration").mkdir(parents=True)
    (platform / "svc-a" / "tests" / "integration" / "test_drive_live_stack.py").touch()
    return installation


FILES = {
    ("platform", 30): ["svc-a/src/mcp.py", "gateway/config.yaml"],
    ("platform", 31): ["svc-a/tests/integration/test_drive_live_stack.py"],
}


def _units():
    return [
        stored_unit("c/1", change="c", repo="platform", state="merged", pr=30),
        stored_unit("c/2", change="c", repo="platform", state="merged", pr=31),
    ]


def verify(host: Host, inst: Installation, files=FILES, env=None):
    return verify_change(
        "c",
        _units(),
        installation=inst,
        pr_files=lambda repo, pr: files[(repo, pr)],
        run=host,
        env=env if env is not None else {"CONSUMER_KEY": "sk-consumer"},
    )


def test_a_merged_change_is_deployed_from_main_then_tested_live(inst) -> None:
    host = Host()

    result = verify(host, inst)

    assert result.passed, result.detail
    ran = host.ran()
    pull = ran.index(("platform", ("git", "pull", "--ff-only", "-q")))
    deploy = ran.index(("platform", ("scripts/deploy.sh", "svc-a")))
    test = next(i for i, (_, c) in enumerate(ran) if "pytest" in c)
    assert pull < deploy < test
    assert ("platform", ("docker", "compose", "restart", "gateway")) in ran
    assert result.deployed == [
        "platform: scripts/deploy.sh svc-a",
        "platform: docker compose restart gateway",
    ]


def test_the_live_tests_get_the_consumer_env_and_the_repo_s_credentials(inst) -> None:
    host = Host()
    verify(host, inst)

    [(_, command, env)] = [c for c in host.calls if "pytest" in c[1]]
    assert env["CONSUMER_KEY"] == "sk-consumer"
    assert env["GATEWAY_MASTER_KEY"] == "sk-master"
    # only the live-stack tests, and never the ones only a dev stack can run
    assert command[command.index("-m") + 1] == "local_stack and not dev_stack"


def test_a_failing_live_test_fails_the_change_with_what_failed(inst) -> None:
    result = verify(Host(failing="pytest"), inst)

    assert not result.passed
    assert "no tools" in result.detail


def test_a_failed_deploy_stops_before_testing(inst) -> None:
    host = Host(failing="deploy.sh")

    result = verify(host, inst)

    assert not result.passed
    assert "deploy.sh svc-a" in result.detail
    assert not [c for _, c in host.ran() if "pytest" in c]


@pytest.mark.parametrize(
    ("host", "why"),
    [(Host(dirty=" M README.md"), "uncommitted"), (Host(branch="feature"), "not on main")],
)
def test_a_checkout_that_is_not_a_clean_default_branch_is_left_alone(inst, host, why) -> None:
    # The deploy builds from the user's own checkout; pulling into one with
    # their work in it, or deploying some other branch, is not this step's
    # call.
    result = verify(host, inst)

    assert not result.passed
    assert why in result.detail
    assert not [c for _, c in host.ran() if c[:2] == ("git", "pull") or "deploy" in " ".join(c)]


def test_a_repo_that_needs_an_ssh_agent_deploys_inside_one(inst, tmp_path: Path) -> None:
    host = Host()
    units = [stored_unit("a/1", change="c", repo="app", state="merged", pr=7)]

    verify_change(
        "c",
        units,
        installation=inst,
        pr_files=lambda repo, pr: ["worker/src/main.py"],
        run=host,
        env={},
    )

    [deploy] = [c for _, c in host.ran() if "scripts/deploy-blue-green.sh" in c]
    assert deploy[0] == "ssh-agent"
    assert str(tmp_path / "keys" / "deploy") in deploy
    assert deploy[-2:] == ("scripts/deploy-blue-green.sh", "worker")


def test_paths_the_running_system_writes_do_not_hold_up_a_deploy(inst) -> None:
    # `live_written` names what the system itself changes in the checkout;
    # anything else uncommitted still holds the deploy.
    units = [stored_unit("a/1", change="c", repo="app", state="merged", pr=7)]

    def run_with(dirty: str):
        return verify_change(
            "c",
            units,
            installation=inst,
            pr_files=lambda repo, pr: ["worker/src/main.py"],
            run=Host(dirty=dirty),
            env={},
        )

    assert run_with(" M notes/learned.md").passed
    held = run_with(" M notes/learned.md\n M worker/src/main.py")
    assert not held.passed
    assert "worker/src/main.py" in held.detail


def test_consumed_repos_deploy_first(inst) -> None:
    host = Host()
    units = [
        stored_unit("a/1", change="c", repo="app", state="merged", pr=7),
        stored_unit("p/1", change="c", repo="platform", state="merged", pr=8),
    ]
    files = {("app", 7): ["worker/x.py"], ("platform", 8): ["svc-a/y.py"]}

    verify_change(
        "c", units, installation=inst, pr_files=lambda r, p: files[(r, p)], run=host, env={}
    )

    deploys = [where for where, c in host.ran() if "deploy" in " ".join(c)]
    assert deploys.index("platform") < deploys.index("app")


def test_a_change_with_nothing_to_deploy_or_test_passes(inst) -> None:
    result = verify(Host(), inst, files={("platform", 30): ["README.md"], ("platform", 31): []})

    assert result.passed
    assert result.deployed == []
