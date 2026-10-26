# Tasks

Priority: 3

Acceptance: none — a test-suite change with no behaviour a user sees; the groups' own tests are the check.

## 1. [agent-build-kit] [unit-test] Chat tests share no session id and run in parallel

Done when no two test modules define the same constant session id, the ten chat modules pass 10 repeats
under `-n auto --maxprocesses=8`, and a marker remains only on a module with a stated reason.

- [x] 1.1 Test: the guard walks every test module and test support module, collects each string constant
      shaped like a session id, and fails naming the id and both files when two files define the same one;
      a constant repeated inside one file is allowed. It fails on today's tree.
- [x] 1.2 Test: the id fixture gives a different id to each test, and a different id on each call within
      a test when asked for two.
- [x] 1.3 Test: the chat object's holder lookups, given a process-table directory, answer from it and not
      from the machine's; with none given they read the machine's, as before.
- [x] 1.4 Test: one live case per lookup starts a real detached process whose command line carries a
      fixture-made id and finds it; a second test's id is not found by it.
- [x] 1.5 Add the fixture and the optional process-table argument to the two lookups on the chat object.
- [x] 1.6 Replace each module's constant ids with the fixture, and the tests that start real processes only
      to be found with a private process-table tree, in `tests/serve/` and the four other files the guard names.
- [x] 1.7 Remove the serial marker from each of the ten modules once it passes 10 repeats under
      `-n auto --maxprocesses=8`; keep it, with a one-line reason, on any that does not.
- [x] 1.8 Correct the comment beside the serial pass in `pyproject.toml`; if no module is marked, remove the
      serial pass, the marker definition and the exemption for an empty collection; add a changelog line if
      the repo keeps one for test-suite changes.
