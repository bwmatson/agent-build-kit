"""The socket clients of the chat-environment tests wait as long as a turn does (spec:
fix-test-tests-serve-test-chat-agent-environment-py-test-the-0b88e8ae, group 1).

A request whose handler starts a real agent process can take longer than httpx's unstated
5-second default under the parallel suite's load, so each client states `timeout=WAIT`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TypeGuard

from tests.chat_serving import WAIT

MODULE = Path(__file__).with_name("test_chat_agent_environment.py")
RESUME_CHECK = "test_the_resume_check_runs_in_the_given_environment"


def parsed() -> ast.Module:
    return ast.parse(MODULE.read_text())


def is_client_call(node: ast.AST) -> TypeGuard[ast.Call]:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Client"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "httpx"
    )


def test_every_client_in_the_module_is_opened_with_the_shared_wait() -> None:
    clients = [node for node in ast.walk(parsed()) if is_client_call(node)]
    assert clients, "the module opens no httpx client"

    unbounded = [
        node.lineno
        for node in clients
        if not any(
            keyword.arg == "timeout"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "WAIT"
            for keyword in node.keywords
        )
    ]

    assert not unbounded, f"httpx.Client opened without timeout=WAIT at lines {unbounded}"
    assert WAIT > 5


def test_the_resume_check_says_why_when_it_cannot_resume() -> None:
    (test,) = [
        node
        for node in ast.walk(parsed())
        if isinstance(node, ast.FunctionDef) and node.name == RESUME_CHECK
    ]
    (continues,) = [
        node
        for node in ast.walk(test)
        if isinstance(node, ast.Assert) and '"continue"' in ast.unparse(node.test)
    ]

    message = ast.unparse(continues.msg) if continues.msg else ""

    assert 'opened["reason"]' in message
    assert 'opened["actions"]' in message
