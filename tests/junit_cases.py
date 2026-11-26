"""Test support: a JUnit report naming each case of a scripted pytest run, as pytest writes it."""

from __future__ import annotations

from collections.abc import Sequence
from xml.etree import ElementTree

from agent_build_kit.pipeline.red_check import REPORT_MARK

FAILED_ASSERTION = "assert 0 == 1"


def passing(classname: str, name: str) -> tuple[str, str, str | None]:
    """A case that passed."""
    return classname, name, None


def failing(classname: str, name: str) -> tuple[str, str, str | None]:
    """A case that failed with an assertion."""
    return classname, name, FAILED_ASSERTION


def junit_report(cases: Sequence[tuple[str, str, str | None]]) -> str:
    """The report of a run whose cases are (class name, name, failure message or None), on one
    line."""
    suite = ElementTree.Element("testsuite", tests=str(len(cases)))
    for classname, name, message in cases:
        case = ElementTree.SubElement(suite, "testcase", classname=classname, name=name)
        if message is not None:
            ElementTree.SubElement(case, "failure", message=message).text = message
    root = ElementTree.Element("testsuites")
    root.append(suite)
    return ElementTree.tostring(root, encoding="unicode")


def printed(cases: Sequence[tuple[str, str, str | None]]) -> str:
    """What a red command prints for a run of `cases`: the report after its mark."""
    return f"{REPORT_MARK}\n{junit_report(cases)}"
