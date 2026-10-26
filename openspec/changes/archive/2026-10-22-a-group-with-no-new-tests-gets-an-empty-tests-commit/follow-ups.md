## From `a-group-with-no-new-tests-gets-an-empty-tests-commit/1`

- docs/architecture.md:1288 — The push-gate paragraph says the gate accepts 'a real `test:` before an empty `feat:`', but `abk gate`'s red check will report a green real tests commit, and a green tests commit is exactly what the new rule records.
- CHANGELOG.md:20 — This change adds two Unreleased bullets, one for the empty commits and one for the lone-`feat:` stop message, where the convention and task 3.2 ask for one bullet per change.
- src/agent_build_kit/graph/nodes.py:1435 — `stub_checks` builds the same `done` dict on two branches (lines 1435 and 1437), and `record_no_new_tests` returns a bool that no caller reads.
