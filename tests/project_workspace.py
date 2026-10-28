"""A workspace whose repos declare projects, for the tests of how a group heading names one."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from tests.conftest import make_installation

OPT_OUT = "Acceptance: none — a fixture about project tags\n"


def repos_declaring(root: Path, repo: str = "app", paths: tuple[str, ...] = ()) -> dict:
    """The `repos` of a workspace config: `repo` declares `paths` beside its implicit root;
    `platform` declares none."""
    return {
        "platform": {"path": str(root / "checkouts" / "platform"), "slug": "example/platform"},
        repo: {
            "path": str(root / "checkouts" / repo),
            "slug": f"example/{repo.rsplit('/', 1)[-1]}",
            "projects": [{"path": path} for path in (".", *paths)],
        },
    }


def app_with_projects(root: Path, *paths: str, repo: str = "app") -> Installation:
    """The active workspace, with `repo` declaring `paths` beside its root."""
    return make_installation(root, repos=repos_declaring(root, repo, paths))


def tasks_with(*headings: str) -> str:
    """A `tasks.md` whose groups are `headings`, each the text after `## <n>. `."""
    text = f"# Tasks\n\n{OPT_OUT}\n"
    for number, heading in enumerate(headings, start=1):
        text += f"## {number}. {heading}\n\n- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
    return text


def tasks_editing(*groups: tuple[str, str]) -> str:
    """A `tasks.md` whose groups are each a heading (the text after `## <n>. `) and the file its
    second task edits: the path the group names."""
    text = f"# Tasks\n\n{OPT_OUT}\n"
    for number, (heading, path) in enumerate(groups, start=1):
        text += f"## {number}. {heading}\n\n- [ ] {number}.1 Test: it.\n"
        text += f"- [ ] {number}.2 Edit `{path}`.\n\n"
    return text
