"""A node-npm stub is only a stub (spec: node-npm-red-and-stubs).

Each test pairs what must be accepted with a near miss that must not be, so a check that
accepts or rejects everything fails.
"""

from __future__ import annotations

import pytest

from agent_build_kit import profiles

SENTINEL = 'throw new Error("not implemented");'

STUB = f"""\
import {{ helper }} from "./helper";
import type {{ Options }} from "./options";

export type Id = string;
export interface Shape {{ id: Id; area(): number }}
export const LIMIT = 10;
export enum Kind {{ A, B }}
declare function external(x: number): number;

export function area(shape: Shape): number {{
  {SENTINEL}
}}

export const double = (n: number): number => {{
  {SENTINEL}
}};

export class Box {{
  size: number = 3;
  grow(by: number): Box {{
    {SENTINEL}
  }}
}}
"""


@pytest.fixture
def profile():
    return profiles.get("node-npm")


def test_sentinel_bodies_and_declarations_are_accepted(profile) -> None:
    logic = STUB.replace(SENTINEL, "return 1;", 1)

    assert profile.stub_violations("src/shape.ts", STUB) == []
    assert profile.stub_violations("src/shape.ts", logic) != []


def test_a_body_with_logic_is_a_violation_naming_the_function(profile) -> None:
    source = f"""\
export function ok(): number {{
  {SENTINEL}
}}

export function total(a: number, b: number): number {{
  return a + b;
}}
"""

    problems = profile.stub_violations("src/total.ts", source)

    assert len(problems) == 1
    assert "total" in problems[0]
    assert "src/total.ts" in problems[0]


def test_a_nested_function_with_logic_is_a_violation(profile) -> None:
    nested = f"""\
export function outer(): number {{
  function inner(): number {{
    return 1;
  }}
  {SENTINEL}
}}
"""
    sentinel_only = f"""\
export function outer(): number {{
  function inner(): number {{
    {SENTINEL}
  }}
  {SENTINEL}
}}
"""

    assert profile.stub_violations("src/n.ts", nested) != []
    assert profile.stub_violations("src/n.ts", sentinel_only) == []


def test_a_sentinel_followed_by_logic_is_a_violation(profile) -> None:
    source = f"export function f(): number {{\n  {SENTINEL}\n  return 1;\n}}\n"

    assert profile.stub_violations("src/f.ts", source) != []


def test_an_unparseable_file_is_a_violation_saying_so(profile) -> None:
    problems = profile.stub_violations("src/bad.ts", "export function f( {\n")

    assert problems
    assert any("parse" in problem for problem in problems)


def test_a_test_file_is_not_checked(profile) -> None:
    logic = "export function f(): number {\n  return 1;\n}\n"

    assert profile.stub_violations("src/f.ts", logic) != []
    assert profile.stub_violations("src/f.test.ts", logic) == []
    assert profile.stub_violations("src/__tests__/f.ts", logic) == []
