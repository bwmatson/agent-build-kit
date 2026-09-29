"""Every Azure DevOps call the pipeline makes, in one place.

What these check is the discipline, not the API: that a call names its
organisation rather than relying on a configured default, that the token is
passed through the environment rather than argv, and above all that an answer
which is not JSON is an error. An unauthenticated Azure DevOps request is
answered with a sign-in page and a 2xx, and read as `{}` that says "no pull
requests" — the failure counter never trips and the pipeline goes quiet with a
clean log.
"""

from __future__ import annotations

import subprocess

import pytest

from agent_build_kit.pipeline import az
from agent_build_kit.settings import settings


def recorded(stdout: str = "", returncode: int = 0):
    calls: list[dict] = []

    def run(args, **kwargs):
        calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(args, returncode, stdout, "")

    return run, calls


def test_a_call_names_its_organisation_rather_than_a_configured_default() -> None:
    """`az devops configure --defaults` is global CLI state, and units run
    concurrently: one repo's default would answer another repo's call."""
    run, calls = recorded("[]")

    az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    args = calls[0]["args"]
    assert args[:4] == ["az", "repos", "pr", "list"]
    assert args[args.index("--org") + 1] == "https://dev.azure.com/acme"
    assert "--output" in args and "json" in args


def test_the_token_travels_in_the_environment_not_in_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ps` shows every argument of every running process, and a build runs
    unattended for hours."""
    monkeypatch.setattr(settings, "ado_pat", "a-secret")
    run, calls = recorded("[]")

    az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    assert "a-secret" not in " ".join(calls[0]["args"])
    assert calls[0]["env"]["AZURE_DEVOPS_EXT_PAT"] == "a-secret"


def test_without_a_token_the_call_falls_back_to_the_az_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both ways of being authenticated have to work: a PAT on a headless box,
    an `az login` session on a workstation."""
    monkeypatch.setattr(settings, "ado_pat", "")
    run, calls = recorded("[]")

    az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    assert "AZURE_DEVOPS_EXT_PAT" not in calls[0]["env"]


def test_a_sign_in_page_is_an_error_not_an_empty_answer() -> None:
    """The trap this module exists for: HTML with a 2xx, parsed as nothing,
    reads as "no pull requests" and the poller never backs off."""
    run, _ = recorded("<!DOCTYPE html><html>Sign in to your account")

    with pytest.raises(az.AzError) as refused:
        az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    assert "not JSON" in str(refused.value)


def test_a_failed_call_reports_what_az_said() -> None:
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "TF401019: repository does not exist")

    with pytest.raises(az.AzError) as refused:
        az.json_out(["repos", "pr", "show"], org="https://dev.azure.com/acme", run=run)

    assert "TF401019" in str(refused.value)


def test_an_empty_answer_is_an_empty_answer() -> None:
    """A command that prints nothing on success — an update, a delete — is not
    a failure, and must not be read as one."""
    run, _ = recorded("")

    assert az.json_out(["repos", "pr", "update"], org="https://dev.azure.com/acme", run=run) is None


def test_the_organisation_url_is_built_from_the_account_name() -> None:
    assert az.org_url("3CInternalAI") == "https://dev.azure.com/3CInternalAI"
