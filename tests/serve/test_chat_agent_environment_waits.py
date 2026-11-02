"""The resume check of the chat-environment tests says why it could not resume (spec:
fix-test-tests-serve-test-chat-agent-environment-py-test-the-0b88e8ae, group 1).
"""

from __future__ import annotations

import ast
from pathlib import Path

MODULE = Path(__file__).with_name("test_chat_agent_environment.py")
RESUME_CHECK = "test_the_resume_check_runs_in_the_given_environment"


def parsed() -> ast.Module:
    return ast.parse(MODULE.read_text())


def test_the_resume_check_says_why_when_it_cannot_resume() -> None:
    (test,) = [
        node
        for node in ast.walk(parsed())
        if isinstance(node, ast.FunctionDef) and node.name == RESUME_CHECK
    ]
    (continues,) = [
        node
        for node in ast.walk(test)
        if isinstance(node, ast.Assert) and "'continue'" in ast.unparse(node.test)
    ]

    message = ast.unparse(continues.msg) if continues.msg else ""

    assert "opened['reason']" in message
    assert "opened['actions']" in message
