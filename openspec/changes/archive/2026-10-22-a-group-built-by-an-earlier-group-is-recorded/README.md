# a-group-built-by-an-earlier-group-is-recorded

Unit `reviewers-are-told-where-to-look/4` (repo agent-build-kit, groups 3 and 4 joined into one unit) failed on 2026-10-21 with `the branch holds no tests and
implementation pair for group 4 (The Start here section is never shrunk, and a held unit carries it)`, after the merged change
`a-group-already-built-is-satisfied-in-a-stubbed-build`. Group 3's builder had also built group 4's work, so the unit made a real `test:` and `feat:` pair for
group 3 and group 4's agents rightly found nothing to change. The merged change only helps a branch with no commit at all; this one has commits, and the
stubbed build requires a `test:` then `feat:` pair for every group, matched by position and title. This change makes the stubbed build record such a group
with an EMPTY, marked pair (`git commit --allow-empty` of `test: <title>` and `feat: <title>`, each with the trailers `Unit:` and `Already-built: yes`),
only when the whole repository's unit tests pass on the tree, with the agent's account in the body of the `feat:` commit as the reason. Position and title
matching, resume, restack and the push gate keep working unchanged; a forgotten implementation still stops the unit with the pair message. A unit whose every
group is already built still ends `satisfied` by the existing zero-commit route. Both flows stay behind `builders.per_group_commits`. Emergency lane
(priority 0).
