"""The node profile's code reader, over small fixture projects in a temporary folder."""

from pathlib import Path

import pytest

from agent_build_kit.codemap.graph import FileFacts, Reading
from agent_build_kit.profiles.node_npm import NodeNpmProfile


def read_project(root: Path, files: dict[str, str]) -> Reading:
    """Write `files` under `root` and read them as the build would: the reader's suffixes,
    split into sources and tests by the profile's own rule."""
    profile = NodeNpmProfile()
    reader = profile.code_reader()
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    kept = sorted(p for p in files if p.endswith(reader.suffixes))
    sources = [p for p in kept if not profile.is_test_path(p)]
    tests = [p for p in kept if profile.is_test_path(p)]
    return reader.read(root, sources, tests)


def facts_of(reading: Reading) -> dict[str, FileFacts]:
    return {facts.path: facts for facts in reading.files}


def edges_of(reading: Reading, *kinds: str) -> set[tuple[str, str, str]]:
    return {(e.kind, e.source, e.target) for e in reading.edges if e.kind in kinds}


SYMBOL_ROWS = [
    pytest.param(
        "a.ts",
        "export function add(a: number, b: number): number {\n  return a + b;\n}\n",
        [("add", "function", "function add(a: number, b: number): number", "")],
        id="function-declaration",
    ),
    pytest.param(
        "a.ts",
        "export const total = (rows: Row[]): number => {\n  return rows.length;\n};\n",
        [("total", "function", "const total = (rows: Row[]): number =>", "")],
        id="exported-arrow-function",
    ),
    pytest.param(
        "a.ts",
        "export default function (x: number) {\n  return x;\n}\n",
        [("default", "function", None, "")],
        id="anonymous-default-export",
    ),
    pytest.param(
        "a.ts",
        "class C {\n  m(x: number) {\n    return x;\n  }\n}\n"
        "abstract class D {\n  abstract n(): void;\n  o() {}\n}\n",
        [
            ("C", "class", None, ""),
            ("C.m", "function", None, ""),
            ("D", "class", None, ""),
            ("D.o", "function", None, ""),
        ],
        id="classes-and-methods",
    ),
    pytest.param(
        "a.ts",
        "/**\n * Adds two numbers.\n * More detail.\n */\n"
        "export function add(a: number) {\n  return a;\n}\n",
        [("add", "function", None, "Adds two numbers.")],
        id="jsdoc-before-export",
    ),
    pytest.param(
        "a.tsx",
        "export function Page() {\n  return <div>hi</div>;\n}\n",
        [("Page", "function", None, "")],
        id="tsx-component",
    ),
    pytest.param(
        "a.ts",
        "export interface I {\n  a: number;\n}\nexport type T = string;\n",
        [],
        id="interface-and-type-alias",
    ),
    pytest.param(
        "types.d.ts",
        "export declare function f(): void;\n",
        None,
        id="declaration-file-is-not-read",
    ),
]


@pytest.mark.parametrize(("name", "source", "expected"), SYMBOL_ROWS)
def test_the_reader_finds_a_files_symbols(
    tmp_path: Path, name: str, source: str, expected: list[tuple[str, str, str | None, str]] | None
) -> None:
    facts = facts_of(read_project(tmp_path, {name: source}))

    if expected is None:
        assert name not in facts
        return
    symbols = facts[name].symbols
    assert [s.name for s in symbols] == [e[0] for e in expected]
    assert [s.kind for s in symbols] == [e[1] for e in expected]
    for symbol, (_, _, signature, doc) in zip(symbols, expected, strict=True):
        assert symbol.doc == doc
        assert symbol.lines >= 1
        assert symbol.span[0] <= symbol.span[1]
        if signature is not None:
            assert symbol.signature == signature


def test_the_reader_resolves_imports_across_relative_paths_and_workspace_members(
    tmp_path: Path,
) -> None:
    main = (
        'import { u } from "./util";\n'
        'import { l } from "../lib";\n'
        'import { x } from "./x.js";\n'
        'import { s } from "@demo/shared";\n'
        'import { fmt } from "@demo/shared/format";\n'
        'import React from "react";\n'
        'import { thing } from "@/thing";\n'
        'export * from "./re";\n'
        'export const lazy = () => import("./lazy");\n'
        "export const keep = [u, l, x, s, fmt, React, thing];\n"
    )
    reading = read_project(
        tmp_path,
        {
            "package.json": '{"name": "demo", "workspaces": ["packages/*"]}',
            "packages/shared/package.json": '{"name": "@demo/shared"}',
            "packages/shared/src/index.ts": "export const s = 1;\n",
            "packages/shared/format.ts": "export const fmt = 1;\n",
            "packages/page/package.json": '{"name": "@demo/page"}',
            "packages/page/src/pages/main.ts": main,
            "packages/page/src/pages/util.ts": "export const u = 1;\n",
            "packages/page/src/lib/index.tsx": "export const l = 1;\n",
            "packages/page/src/pages/x.ts": "export const x = 1;\n",
            "packages/page/src/pages/lazy.ts": "export const z = 1;\n",
            "packages/page/src/pages/re.ts": "export const r = 1;\n",
        },
    )

    page = "packages/page/src"
    assert edges_of(reading, "imports") == {
        ("imports", f"{page}/pages/main.ts", target)
        for target in (
            f"{page}/pages/util.ts",
            f"{page}/lib/index.tsx",
            f"{page}/pages/x.ts",
            "packages/shared/src/index.ts",
            "packages/shared/format.ts",
            f"{page}/pages/lazy.ts",
            f"{page}/pages/re.ts",
        )
    }


CALL_ROWS = [
    pytest.param(
        {"a.ts": "function g() {}\nexport function f() {\n  g();\n}\n"},
        {("invokes", "a.ts::f", "a.ts::g")},
        id="same-file-function",
    ),
    pytest.param(
        {
            "b.ts": "export function g() {}\n",
            "a.ts": 'import { g } from "./b";\nexport function f() {\n  g();\n}\n',
        },
        {("invokes", "a.ts::f", "b.ts::g")},
        id="named-import",
    ),
    pytest.param(
        {
            "b.ts": "export default function () {}\n",
            "a.ts": 'import g from "./b";\nexport function f() {\n  g();\n}\n',
        },
        {("invokes", "a.ts::f", "b.ts::default")},
        id="default-import",
    ),
    pytest.param(
        {
            "b.ts": "export function g() {}\n",
            "a.ts": 'import * as ns from "./b";\nexport function f() {\n  ns.g();\n}\n',
        },
        {("invokes", "a.ts::f", "b.ts::g")},
        id="namespace-import",
    ),
    pytest.param(
        {
            "b.ts": "export class C {}\n",
            "a.ts": 'import { C } from "./b";\nexport function f() {\n  return new C();\n}\n',
        },
        {("invokes", "a.ts::f", "b.ts::C")},
        id="new-expression",
    ),
    pytest.param(
        {
            "table.tsx": "export function Table() {\n  return null;\n}\n",
            "a.tsx": 'import { Table } from "./table";\n'
            "export function Page() {\n  return <Table />;\n}\n",
        },
        {("invokes", "a.tsx::Page", "table.tsx::Table")},
        id="jsx-element",
    ),
    pytest.param(
        {"a.ts": "export class A {\n  m() {}\n  n() {\n    this.m();\n  }\n}\n"},
        {("invokes", "a.ts::A.n", "a.ts::A.m")},
        id="this-method",
    ),
    pytest.param(
        {
            "b.ts": "export class B {}\n",
            "a.ts": 'import { B } from "./b";\nexport class A extends B {}\n',
        },
        {("inherits", "a.ts::A", "b.ts::B")},
        id="extends-imported-class",
    ),
    pytest.param(
        {"a.ts": "export function f(cb: () => void) {\n  cb();\n}\n"},
        set(),
        id="call-on-a-parameter",
    ),
    pytest.param(
        {"a.ts": 'export function f() {\n  console.log(1);\n  fetch("x");\n}\n'},
        set(),
        id="call-to-a-global",
    ),
]


@pytest.mark.parametrize(("files", "expected"), CALL_ROWS)
def test_the_reader_resolves_calls_and_bases_statically(
    tmp_path: Path, files: dict[str, str], expected: set[tuple[str, str, str]]
) -> None:
    reading = read_project(tmp_path, files)

    assert edges_of(reading, "invokes", "inherits") == expected


TEST_FILE_ROWS = [
    pytest.param(["src/sum.test.ts"], ["src/sum.test.ts"], id="beside-the-module"),
    pytest.param(
        ["src/__tests__/sum.test.ts"], ["src/__tests__/sum.test.ts"], id="in-a-tests-folder"
    ),
    pytest.param(["tests/sum.spec.ts"], ["tests/sum.spec.ts"], id="in-the-projects-tests-folder"),
    pytest.param([], [], id="no-test-file"),
]


@pytest.mark.parametrize(("test_files", "expected"), TEST_FILE_ROWS)
def test_the_reader_names_each_modules_test_files(
    tmp_path: Path, test_files: list[str], expected: list[str]
) -> None:
    files = {"src/sum.ts": "export const sum = () => 0;\n"}
    files.update({path: "export {};\n" for path in test_files})

    facts = facts_of(read_project(tmp_path, files))

    assert list(facts["src/sum.ts"].tests) == expected
    assert not any(path in facts for path in test_files)


def test_the_reader_does_not_match_a_test_file_of_another_folder(tmp_path: Path) -> None:
    facts = facts_of(
        read_project(
            tmp_path,
            {
                "src/a/sum.ts": "export const sum = () => 0;\n",
                "tests/b/sum.test.ts": "export {};\n",
            },
        )
    )

    assert list(facts["src/a/sum.ts"].tests) == []


def test_a_file_that_does_not_parse_is_a_file_node_and_a_problem(tmp_path: Path) -> None:
    reading = read_project(
        tmp_path,
        {"broken.ts": "export function f( {{{\n", "ok.ts": "export const x = 1;\n"},
    )

    facts = facts_of(reading)
    assert facts["broken.ts"].symbols == ()
    assert [name for name in facts["ok.ts"].symbols] != []
    assert len(reading.problems) == 1
    assert "broken.ts" in reading.problems[0]
