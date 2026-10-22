"""The reader of a builder's `product-defect` block: a defect, nothing, or a refusal with a
reason, decided without a model (spec: e2e-group-scope)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.product_defect import (
    DefectRefused,
    ProductDefect,
    read_product_defect,
)

TEST = "tests/e2e/test_route.py::test_stream"
FAILURE = f"FAILED {TEST} - assert 200 == 500\n1 failed in 3.10s"
REPORT: dict[str, Any] = {
    "test": TEST,
    "files": ["src/app/route.py"],
    "reproduction": "GET /stream with no token: expected 401, got 500",
}


def block(report: dict[str, Any] | str) -> str:
    body = report if isinstance(report, str) else json.dumps(report, indent=2)
    return f"```product-defect\n{body}\n```"


def account(*blocks: str) -> str:
    return "I read the failure.\n\n" + "\n\n".join(blocks) + "\n\nThat is my account."


def read(text: str, tmp_path: Path, **options: Any) -> ProductDefect | DefectRefused | None:
    repos = {"app": RepoConfig(path=tmp_path), "platform": RepoConfig(path=tmp_path)}
    return read_product_defect(text, failure=FAILURE, repo="app", repos=repos, **options)


def refusal(text: str, tmp_path: Path) -> str:
    refused = read(text, tmp_path)
    assert isinstance(refused, DefectRefused), refused
    return refused.reason


def test_a_valid_block_is_a_defect(tmp_path: Path) -> None:
    found = read(account(block({**REPORT, "sketch": "def test_route(): ..."})), tmp_path)

    assert found == ProductDefect(
        test=TEST,
        files=["src/app/route.py"],
        reproduction=REPORT["reproduction"],
        sketch="def test_route(): ...",
    )


def test_the_last_block_of_an_account_is_the_one_read(tmp_path: Path) -> None:
    first = {**REPORT, "files": ["src/app/old.py"]}
    last = {**REPORT, "files": ["src/app/new.py"], "repo": "platform"}

    found = read(account(block(first), block(last)), tmp_path)

    assert isinstance(found, ProductDefect)
    assert found.files == ["src/app/new.py"]
    assert found.repo == "platform"


def test_an_account_with_no_block_reports_nothing(tmp_path: Path) -> None:
    assert read("I fixed the selector in tests/e2e/conftest.py.", tmp_path) is None
    assert read("```json\n{}\n```", tmp_path) is None, "only a `product-defect` block counts"


def test_a_block_that_is_not_json_is_refused(tmp_path: Path) -> None:
    reason = refusal(account(block("{not json")), tmp_path)

    assert "json" in reason.lower()


@pytest.mark.parametrize("missing", ["test", "reproduction"])
def test_a_block_without_a_required_field_is_refused_naming_it(
    missing: str, tmp_path: Path
) -> None:
    report = {key: value for key, value in REPORT.items() if key != missing}

    assert missing in refusal(account(block(report)), tmp_path)


@pytest.mark.parametrize("field", ["test", "reproduction"])
@pytest.mark.parametrize("blank", ["", "  "])
def test_a_blank_required_field_is_refused_naming_it(
    field: str, blank: str, tmp_path: Path
) -> None:
    assert field in refusal(account(block({**REPORT, field: blank})), tmp_path)


def test_a_block_with_no_files_is_refused(tmp_path: Path) -> None:
    assert "files" in refusal(account(block({**REPORT, "files": []})), tmp_path)


def test_a_test_the_saved_failure_does_not_mention_is_refused(tmp_path: Path) -> None:
    other = "tests/e2e/test_route.py::test_other"

    reason = refusal(account(block({**REPORT, "test": other})), tmp_path)

    assert other in reason


def test_a_repo_that_is_not_declared_is_refused(tmp_path: Path) -> None:
    reason = refusal(account(block({**REPORT, "repo": "elsewhere"})), tmp_path)

    assert "elsewhere" in reason


def test_a_declared_repo_is_kept(tmp_path: Path) -> None:
    found = read(account(block({**REPORT, "repo": "platform"})), tmp_path)

    assert isinstance(found, ProductDefect)
    assert found.repo == "platform"


def test_files_that_are_only_tests_and_docs_are_the_tests_fault(tmp_path: Path) -> None:
    files = ["tests/e2e/conftest.py", "docs/e2e.md", "CHANGELOG.md"]

    reason = refusal(account(block({**REPORT, "files": files})), tmp_path)

    assert "fault in the test" in reason
    assert "in place" in reason


def test_one_product_file_among_test_paths_is_enough(tmp_path: Path) -> None:
    files = ["tests/e2e/conftest.py", "src/app/route.py"]

    found = read(account(block({**REPORT, "files": files})), tmp_path)

    assert isinstance(found, ProductDefect)
    assert found.files == files


def test_a_declared_support_file_is_not_a_product_file(tmp_path: Path) -> None:
    files = ["scripts/seed-stack.sh"]

    refused = read(account(block({**REPORT, "files": files})), tmp_path, support=files)

    assert isinstance(refused, DefectRefused)
