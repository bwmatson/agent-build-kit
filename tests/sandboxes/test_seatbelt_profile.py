"""The Seatbelt backend's generated profile, its command and its probe, checked as text and as
arguments; nothing here needs a Mac (the behavioural cases are in `test_backend_contract.py`)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.sandboxes import Coverage, SandboxPolicy
from agent_build_kit.sandboxes.seatbelt import BACKEND, profile_text
from tests.sandboxes.seatbelt_support import (
    as_macos,
    fake_sandbox_exec,
    no_sandbox_exec,
)

PARAM = re.compile(r'\(param "([^"]+)"\)')
PATH_RULE = re.compile(r'\((subpath|literal) \(param "([^"]+)"\)\)')


def policy(tmp_path: Path, *, proxy_port: int | None = 8123) -> SandboxPolicy:
    write = tmp_path / "work"
    write.mkdir()
    read = tmp_path / "tools"
    read.mkdir()
    return SandboxPolicy(
        write=(write,),
        read=(read,),
        hosts=("example.com",),
        required=Coverage.PROCESS,
        proxy_port=proxy_port,
    )


def forms(text: str) -> list[str]:
    """The top-level `(...)` forms of a profile, comments dropped, each on one line."""
    body = "\n".join(line.split(";")[0] for line in text.splitlines())
    found, depth, start = [], 0, 0
    for index, char in enumerate(body):
        if char == "(":
            if depth == 0:
                start = index
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                found.append(" ".join(body[start : index + 1].split()))
    return found


def split_command(command: list[str]) -> tuple[Path, dict[str, str], list[str]]:
    """The profile file, the `-D` parameters and the confined argv of a `sandbox-exec` command."""
    assert command[:2] == ["sandbox-exec", "-f"]
    cut = command.index("--")
    head = command[:cut]
    params = dict(head[at + 1].split("=", 1) for at, word in enumerate(head) if word == "-D")
    return Path(head[2]), params, command[cut + 1 :]


def granted(text: str, params: dict[str, str], operation: str) -> list[tuple[str, str]]:
    """The (kind, path) pairs the profile allows for `operation`, named paths filled in."""
    found = []
    for form in forms(text):
        if form.startswith(f"(allow {operation} ") or form.startswith(f"(allow {operation})"):
            found += [(kind, params[name]) for kind, name in PATH_RULE.findall(form)]
    return found


def test_the_backend_is_registered_for_macos() -> None:
    assert sandboxes.get("seatbelt").platform == "darwin"
    assert "seatbelt" in sandboxes.names()


def test_the_profile_allows_the_proxy_port_and_each_e2e_port_once() -> None:
    text = profile_text(
        SandboxPolicy(
            write=(),
            read=(),
            hosts=(),
            required=Coverage.PROCESS,
            proxy_port=3128,
            ports=(5432, 6379),
        )
    )

    rules = [f for f in forms(text) if f.startswith("(allow network-outbound")]
    assert sorted(rules) == [
        f'(allow network-outbound (remote ip "localhost:{port}"))' for port in (3128, 5432, 6379)
    ]


def test_a_policy_with_no_proxy_and_no_ports_allows_no_network() -> None:
    text = profile_text(SandboxPolicy(write=(), read=(), hosts=(), required=Coverage.FILES))

    assert not [f for f in forms(text) if f.startswith("(allow network-outbound")]


def test_the_profile_denies_by_default() -> None:
    text = profile_text(SandboxPolicy(write=(), read=(), hosts=(), required=Coverage.PROCESS))

    assert forms(text)[:2] == ["(version 1)", "(deny default)"]


def test_the_profile_allows_writes_and_reads_only_by_the_policys_paths(tmp_path: Path) -> None:
    given = policy(tmp_path)
    profile, params, _ = split_command(BACKEND.command(given, ["true"]))
    text = profile.read_text()

    writes = {path for _, path in granted(text, params, "file-write*")}
    reads = {path for _, path in granted(text, params, "file-read*")}

    assert writes == {str(given.write[0])}
    assert {str(given.read[0]), str(given.write[0])} <= reads
    assert reads <= {str(path) for path in (*given.write, *given.read)}


def test_a_file_is_granted_by_literal_and_a_folder_by_subpath(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    file = tmp_path / "state.json"
    file.write_text("{}")
    given = SandboxPolicy(write=(folder, file), read=(), hosts=(), required=Coverage.PROCESS)
    _, params, _ = split_command(BACKEND.command(given, ["true"]))
    text = profile_text(given)

    assert set(granted(text, params, "file-write*")) == {
        ("subpath", str(folder)),
        ("literal", str(file)),
    }


def test_the_profile_allows_outbound_only_to_the_proxys_loopback_port(tmp_path: Path) -> None:
    text = profile_text(policy(tmp_path, proxy_port=8123))

    network = [form for form in forms(text) if "network" in form]

    assert network == ['(allow network-outbound (remote ip "localhost:8123"))']


def test_the_profile_allows_no_network_without_a_proxy_port(tmp_path: Path) -> None:
    text = profile_text(policy(tmp_path, proxy_port=None))

    assert not [form for form in forms(text) if form.startswith("(allow network")]


def test_no_rule_after_a_deny_allows_what_it_denied(tmp_path: Path) -> None:
    rules = forms(profile_text(policy(tmp_path)))[2:]
    last_allow = max((at for at, rule in enumerate(rules) if rule.startswith("(allow")), default=-1)

    assert [rule for rule in rules[:last_allow] if rule.startswith("(deny")] == []


def test_paths_travel_by_dash_d_and_never_sit_in_the_profile(tmp_path: Path) -> None:
    odd = tmp_path / 'a "quoted" folder'
    odd.mkdir()
    given = SandboxPolicy(write=(odd,), read=(), hosts=(), required=Coverage.PROCESS)

    profile, params, _ = split_command(BACKEND.command(given, ["true"]))
    text = profile.read_text()

    assert str(odd) in params.values()
    assert str(odd) not in text
    assert {name for name in PARAM.findall(text)} <= set(params)


def test_a_no_execute_path_travels_by_dash_d_and_its_deny_comes_last(tmp_path: Path) -> None:
    odd = tmp_path / 'a "quoted" git'
    odd.mkdir()
    given = SandboxPolicy(
        write=(),
        read=(odd,),
        hosts=(),
        required=Coverage.PROCESS,
        proxy_port=8123,
        ports=(9000,),
        no_execute=(odd,),
    )

    profile, params, _ = split_command(BACKEND.command(given, ["true"]))
    text = profile.read_text()
    rules = forms(text)[2:]

    assert str(odd) in params.values()
    assert str(odd) not in text
    assert {name for name in PARAM.findall(text)} <= set(params)
    denies = [at for at, rule in enumerate(rules) if rule.startswith("(deny process-exec")]
    assert len(denies) == 1
    assert not [rule for rule in rules[denies[0] :] if rule.startswith("(allow")]


def test_the_command_runs_the_argv_after_the_double_dash(tmp_path: Path) -> None:
    command = BACKEND.command(policy(tmp_path), ["git", "status", "--short"])

    profile, _, argv = split_command(command)

    assert profile.is_file()
    assert argv == ["git", "status", "--short"]


def test_the_same_policy_gives_the_same_profile_and_parameters(tmp_path: Path) -> None:
    given = policy(tmp_path)

    first = split_command(BACKEND.command(given, ["true"]))
    second = split_command(BACKEND.command(given, ["true"]))

    assert profile_text(given) == profile_text(given)
    assert first[0].read_text() == second[0].read_text() == profile_text(given)
    assert first[1] == second[1]


def test_availability_off_macos_names_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")

    found = BACKEND.availability()

    assert found.ok is False
    assert found.coverage is Coverage.NONE
    assert "linux" in found.cause
    assert found.fix


def test_availability_without_sandbox_exec_names_it_and_the_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_macos(monkeypatch)
    no_sandbox_exec(monkeypatch)

    found = BACKEND.availability()

    assert found.ok is False
    assert found.coverage is Coverage.NONE
    assert "sandbox-exec" in found.cause
    assert "sandbox-exec" in found.fix


def test_availability_fails_when_a_denied_write_goes_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_macos(monkeypatch)
    fake_sandbox_exec(tmp_path, monkeypatch, mode="unconfined")

    found = BACKEND.availability()

    assert found.ok is False
    assert "write" in found.cause
    assert found.fix


def test_availability_fails_when_the_write_is_denied_but_a_connection_goes_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_macos(monkeypatch)
    fake_sandbox_exec(tmp_path, monkeypatch, mode="leaks_network")

    found = BACKEND.availability()

    assert found.ok is False
    assert "connection" in found.cause
    assert found.fix


def test_the_profile_lets_a_process_signal_its_descendants(tmp_path: Path) -> None:
    rules = forms(profile_text(policy(tmp_path)))

    assert "(allow signal (target same-sandbox))" in rules


def test_availability_runs_a_write_probe_and_a_network_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_macos(monkeypatch)
    log = fake_sandbox_exec(tmp_path, monkeypatch, mode="refuses")

    BACKEND.availability()

    profiles = [path.read_text() for path in sorted(log.glob("profile.*"))]
    scripts = [path.read_text() for path in sorted(log.glob("script.*"))]
    assert len(profiles) == 2
    assert all(forms(text)[:2] == ["(version 1)", "(deny default)"] for text in profiles)
    assert not any(form.startswith("(allow network") for text in profiles for form in forms(text))
    assert len([s for s in scripts if re.search(r": > \S*outside", s)]) == 1
    assert len([s for s in scripts if re.search(r"/usr/bin/nc -z 127\.0\.0\.1 \d+", s)]) == 1


def test_availability_is_ok_when_a_denied_write_and_a_direct_connection_both_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_macos(monkeypatch)
    fake_sandbox_exec(tmp_path, monkeypatch, mode="confines")

    found = BACKEND.availability()

    assert found.ok is True, found.cause
    assert found.coverage is Coverage.PROCESS
