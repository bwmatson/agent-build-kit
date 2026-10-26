# a-group-with-no-new-tests-gets-an-empty-tests-commit

Unit `reviewers-are-told-where-to-look/4` (repo agent-build-kit, groups 3 and 4 joined into one unit) failed again after the merged change
`a-group-built-by-an-earlier-group-is-recorded`, with `the branch holds no tests and implementation pair for group 4`. Its branch read
`test g3, feat g3, feat g4, test g4 (empty, marked), feat g4 (empty, marked)`: group 4's tests already existed from group 3, so its tests step committed
nothing, while its implementation step made real changes in an earlier attempt (a changelog blank line and a stale assertion) and committed a lone `feat:` with
no `test:` before it. The pair check matches commits by position and title, so after `feat g3` it expects `test g4` and finds a `feat`. The gap is general:
it arises whenever a group's tests step commits nothing and its implementation step changes something. This change makes the stubbed build record an EMPTY,
marked `test:` commit for such a group at the end of its tests step (in `stub_checks`, after the static check passes), so that whatever the implementation
step then does (a real `feat:`, or nothing and the existing empty `feat:`) completes a pair. It also gives the stop for a lone `feat:` where a `test:` was
expected a clearer message. Emergency lane (priority 0). Both flows stay behind `builders.per_group_commits`.

A second case of the same gap is covered: unit `a-unit-over-its-tier-is-held-and-split/13` (groups 11, 12, 13) stopped with the pair message for group 12 after its tests
agent committed real tests that already passed (group 11's implementation covered them) and its implement step changed nothing. The build now records an empty
marked `feat:` for such a group when the whole-repository unit tests pass, and still stops when they fail.
