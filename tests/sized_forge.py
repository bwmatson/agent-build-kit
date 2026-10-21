"""A host that answers one pull request's size, for the tests of what is said when it is opened."""

from __future__ import annotations

from agent_build_kit.forges import FileChange, RepoId

REPO = RepoId(forge="fake", account="example", name="app")


class SizedForge:
    name = "fake"
    implemented = True
    supports_stacks = False

    def __init__(self, lines: int) -> None:
        self.lines = lines

    def find_pr(self, repo, *, head):
        return None

    def create_pr(self, repo, *, head, base, title, body):
        return 1

    def update_pr(self, repo, pr, *, base="", body=""):
        pass

    def pr_changes(self, repo, pr):
        return [FileChange(path="src/app.py", additions=self.lines, deletions=0)]

    def stack_of(self, repo, pr):
        raise AssertionError("a host without stacks was asked about one")

    def create_stack(self, repo, pulls):
        raise AssertionError("a host without stacks was asked about one")

    def add_to_stack(self, repo, stack, pulls):
        raise AssertionError("a host without stacks was asked about one")
