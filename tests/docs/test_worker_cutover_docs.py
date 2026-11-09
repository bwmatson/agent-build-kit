"""The documents describe the dispatcher and workers as the way a tick runs: the thread pool is
gone from the architecture and unit-graph documents, the worker design is headed as a description
of what exists with a short history in place of its migration plan, and the pipeline skill
explains workers."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed

DOCS = ROOT / "docs"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md"
THREAD_POOL = re.compile(
    r"thread[ -]pool|ThreadPoolExecutor|build pool|pool runs it|in parallel threads|threads mode",
    re.I,
)


def test_the_architecture_document_describes_the_dispatcher_and_workers_and_no_thread_pool() -> (
    None
):
    text = squashed((DOCS / "architecture.md").read_text(encoding="utf-8"))

    assert re.search(r"dispatcher of worker processes", text, re.I)
    assert "abk worker build" in text
    assert THREAD_POOL.search(text) is None


def test_the_unit_graph_document_describes_the_dispatcher_and_workers_and_no_thread_pool() -> None:
    text = squashed((DOCS / "designs" / "unit-graph.md").read_text(encoding="utf-8"))

    assert re.search(r"dispatcher", text, re.I)
    assert re.search(r"worker process", text, re.I)
    assert THREAD_POOL.search(text) is None


def test_the_worker_design_is_headed_as_a_description_of_what_exists() -> None:
    text = (DOCS / "designs" / "worker-design.md").read_text(encoding="utf-8")
    opening = squashed(text.split("\n## ", 1)[0])

    assert re.search(r"describes what (exists|is built)", opening, re.I)
    assert "It is a design, not a specification" not in opening
    assert "Today one abk tick process owns every build" not in opening


def test_the_worker_design_replaces_its_migration_section_with_a_short_history() -> None:
    text = (DOCS / "designs" / "worker-design.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, re.M)

    assert "Migration" not in headings
    assert "History" in headings
    history = text.split("\n## History", 1)[1]
    history = re.split(r"^## ", history, maxsplit=1, flags=re.M)[0]
    assert 0 < len(history.splitlines()) <= 25
    assert "workers.mode: threads | processes" not in text


def test_the_pipeline_skill_says_what_a_worker_is_and_how_to_read_the_status_worker_list() -> None:
    text = squashed(SKILL.read_text(encoding="utf-8"))

    assert re.search(r"a worker is", text, re.I)
    assert "abk worker build" in text
    assert re.search(r"abk status.{0,200}workers?\b.{0,400}(pid)", text, re.I)
    assert "link to the unit's log" not in text


def test_the_orchestration_document_describes_no_thread_pool_and_no_processes_mode() -> None:
    text = squashed((DOCS / "designs" / "orchestration.md").read_text(encoding="utf-8"))
    # The roadmap line for the change in flight names what it deletes; the archive updates it.
    text = text.replace("the tick's thread pool is deleted", "")

    assert THREAD_POOL.search(text) is None
    assert "`processes` mode" not in text
    assert "abk worker build|resolve|verify" in text


def test_the_worker_design_is_written_as_what_is_built() -> None:
    text = (DOCS / "designs" / "worker-design.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, re.M)
    before_history, history_and_after = text.split("\n## History", 1)
    after_history = re.split(r"^## ", history_and_after, maxsplit=1, flags=re.M)[-1]

    assert "Where we are" not in headings
    assert "ThreadPoolExecutor" not in before_history + after_history
