"""The structural helper of the dry-guidance acceptance tests, on hand-written sources.

A wrong helper fails here, in the default suite, and not in a billed agent run: these are
the controls that fix the duplicate threshold before any agent runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.dry_checks import (
    calls_by_name,
    definitions_in_source,
    diff_definitions,
    is_copy,
    literal_count,
    session_prompts,
)
from tests.factories import commit_files, git, init_repo

ORIGINAL = '''\
def slugify(text):
    """Squeeze a title into a slug."""
    lowered = text.lower()
    squeezed = re.sub(r"[^a-z0-9]+", "-", lowered)
    return squeezed.strip("-")
'''

RENAMED_COPY = '''\
def make_stem(value):
    """The same thing, said otherwise."""
    folded = value.lower()
    joined = re.sub(r"[^A-Z0-9]+", "_", folded)
    return joined.strip("_")
'''

DELEGATE = """\
def title_slug(title):
    return slugify(title)
"""

UNRELATED = """\
def page_path(title, root):
    parts = [root, "pages", title]
    return "/".join(parts) + ".md"
"""


def test_a_copy_with_renamed_locals_and_constants_is_a_duplicate_of_the_original() -> None:
    assert is_copy(ORIGINAL, RENAMED_COPY)


def test_a_function_that_only_calls_the_original_is_not_a_duplicate() -> None:
    assert not is_copy(ORIGINAL, DELEGATE)


def test_a_function_that_does_something_else_is_not_a_duplicate() -> None:
    assert not is_copy(ORIGINAL, UNRELATED)


def test_a_call_is_found_by_name_whether_plain_or_through_a_module() -> None:
    source = (
        "def page_path(title):\n    return 'pages/' + slugify(title)\n\n"
        "def file_stem(title):\n    return text.slugify(title)\n"
    )

    assert calls_by_name(source, "page_path", "slugify")
    assert calls_by_name(source, "file_stem", "slugify")


def test_a_mention_in_a_string_or_a_comment_is_not_a_call() -> None:
    source = (
        "def page_path(title):\n"
        '    """Built with slugify(title), as the task says."""\n'
        "    # slugify(title) would do\n"
        "    note = 'slugify(title)'\n"
        "    return note\n"
    )

    assert not calls_by_name(source, "page_path", "slugify")


def test_a_call_made_by_another_definition_is_not_the_callers() -> None:
    source = "def one(x):\n    return slugify(x)\n\ndef two(x):\n    return x\n"

    assert calls_by_name(source, "one", "slugify")
    assert not calls_by_name(source, "two", "slugify")


def test_definitions_in_a_source_carry_their_name_path_and_source() -> None:
    found = definitions_in_source(ORIGINAL + "\n\n" + UNRELATED, "src/app/text.py")

    assert [(d.path, d.name) for d in found] == [
        ("src/app/text.py", "slugify"),
        ("src/app/text.py", "page_path"),
    ]
    assert "squeezed.strip" in found[0].source


def test_the_definitions_a_diff_adds_are_those_of_two_trees_that_differ(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    commit_files(repo, "base", {"src/app/text.py": ORIGINAL, "src/app/pages.py": UNRELATED})
    git(repo, "checkout", "-q", "-b", "feature")
    commit_files(
        repo,
        "work",
        {
            "src/app/text.py": ORIGINAL + "\n\n" + RENAMED_COPY,
            "src/app/files.py": DELEGATE,
            "tests/test_text.py": "def test_it():\n    assert True\n",
        },
    )

    diff = diff_definitions(repo, "main", "feature")

    assert {(d.path, d.name) for d in diff.added} == {
        ("src/app/text.py", "make_stem"),
        ("src/app/files.py", "title_slug"),
    }
    assert diff.changed == ()


def test_a_definition_whose_body_changed_is_reported_as_changed_not_added(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    commit_files(repo, "base", {"src/app/text.py": ORIGINAL})
    git(repo, "checkout", "-q", "-b", "feature")
    commit_files(
        repo,
        "generalize",
        {"src/app/text.py": ORIGINAL.replace('"-", lowered', '"-", lowered, flags=0')},
    )

    diff = diff_definitions(repo, "main", "feature")

    assert diff.added == ()
    assert [(d.path, d.name) for d in diff.changed] == [("src/app/text.py", "slugify")]


def test_the_occurrences_of_a_key_literal_across_a_tree_are_counted(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    commit_files(
        repo,
        "base",
        {
            "src/app/text.py": ORIGINAL,
            "src/app/files.py": RENAMED_COPY.replace("A-Z", "a-z"),
            "tests/test_text.py": 'PATTERN = "[^a-z0-9]+"\n',
        },
    )

    assert literal_count(repo, "main", "[^a-z0-9]+") == 2
    assert literal_count(repo, "main", "[^a-z0-9]+", under="tests/") == 1
    assert literal_count(repo, "main", "[^x]+") == 0


def test_the_prompts_of_a_session_are_the_text_of_its_prompt_requests(tmp_path: Path) -> None:
    record = tmp_path / "session.jsonl"
    lines = [
        {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": 1}},
        {"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": "/work"}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/prompt",
            "params": {
                "sessionId": "s1",
                "prompt": [
                    {"type": "text", "text": "first prompt, part one"},
                    {"type": "text", "text": "part two"},
                ],
            },
        },
        {"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": "s1"}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/prompt",
            "params": {"sessionId": "s1", "prompt": [{"type": "text", "text": "second prompt"}]},
        },
    ]
    record.write_text("".join(json.dumps(line) + "\n" for line in lines))

    prompts = session_prompts(record)

    assert len(prompts) == 2
    assert "first prompt, part one" in prompts[0]
    assert prompts[0].index("part one") < prompts[0].index("part two")
    assert prompts[1] == "second prompt"
