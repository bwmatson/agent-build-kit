# Tasks

Acceptance: none — a workflow file, a parsing test and a pytest option are checked by unit tests over the parsed workflow files and a child pytest; the first main run after the change is the live confirmation, described in design.md.

Priority: 2

## 1. [agent-build-kit] [tier1] Every action runs on Node 24 at an exact release, the runner is pinned, and a test fails on anything else

Done when `.github/workflows/ci.yml` uses `actions/checkout@v7.0.1`, `actions/setup-node@v7.1.0`, `actions/setup-python@v7.0.0` and `astral-sh/setup-uv@v10.3.0` and `runs-on: ubuntu-24.04` in all three jobs, and a test over every `.github/workflows/*.yml` fails on an action below its first Node 24 major, on an action missing from its table, on a floating or expression reference and on a `*-latest` or unlisted runner. Estimate: about 300 changed lines.

- [x] 1.1 Test: `tests/test_ci_workflows.py` parses the real workflow files and asserts every `uses:` is `owner/name@vX.Y.Z` or `owner/name@<40 hex>` with a major at or above the table's (`actions/checkout` 5, `actions/setup-node` 5, `actions/setup-python` 6, `astral-sh/setup-uv` 7), and every `runs-on` is `ubuntu-24.04`.
- [x] 1.2 Test: the same file runs its checker over generated workflow text and asserts it fails, naming the file, job and step, for `actions/checkout@v4`, `actions/setup-uv@v3` written with the wrong owner (an action missing from the table, with the message "add ... to the table"), a floating major (`@v7`), a branch (`@main`), `@latest`, an expression (`${{ matrix.action }}`), `runs-on: ubuntu-latest`, `runs-on: [self-hosted, macos-latest]`, and a matrix runner value ending in `-latest`; and passes a SHA reference, a local `./` action and a `docker://` reference.
- [x] 1.3 Test: the same file asserts the failure message ends with `see AGENTS.md, CI workflows`, and that a workflow file with no jobs, or with a reusable-workflow job (`uses:` at the job level), is read without error.
- [x] 1.4 Move the four actions to the exact tags above and the three jobs to `runs-on: ubuntu-24.04` in `.github/workflows/ci.yml`; keep `python-version: "3.12"`, `node-version: "22"` and `enable-cache: true` as they are. Confirm the places design.md marks UNVERIFIED for these (a real remote used after checkout, the cache post step) and correct the design where the first run says otherwise.

## 2. [agent-build-kit] [tier1] The state a checkpoint test builds holds tuples, and a pydantic serializer warning fails the suite

Done when `test_a_populated_state_carrying_the_nodes_values_encodes_no_blocked_type` builds its state through validation so tuple fields hold tuples and prints no `Pydantic serializer warnings`, a test fails on any `PydanticSerializationUnexpectedValue` the states the held-state tests build raise, and `[tool.pytest.ini_options]` makes that warning a failure. Estimate: about 180 changed lines.

- [x] 2.1 Test: `tests/graph/test_checkpoint_state_quiet.py` builds, for each hold path of `tests/graph/test_hold_causes.py`, the state `test_held_state_plain_text.py` builds, runs it through `blocked_on_load` under `warnings.catch_warnings(record=True)` and asserts no recorded warning mentions `PydanticSerializationUnexpectedValue`; it fails today for the six paths that print it.
- [x] 2.2 Test: the same file asserts the guard can see the defect: a `UnitRun` copied with `model_copy(update={"groups": [1]})` records the warning when serialised, and the same value passed through `model_validate` does not, and that the enum case of `test_held_state_plain_text.py` is still caught by the rebuilt state (a node update holding an off-list enum makes `blocked_on_load` non-empty).
- [x] 2.3 Test: `tests/test_warning_filters.py` (extend it) asserts `[tool.pytest.ini_options]` has a `filterwarnings` entry that begins `error`, matches `Pydantic serializer warnings` and `UserWarning`, and that, applied through `pytester`, a test that serialises a model with a list in a tuple field fails and one that serialises it with a tuple passes, while any other `UserWarning` is still only reported.
- [x] 2.4 Add a helper in `tests/checkpoint_types.py` that builds the state from the node updates through `UnitRun.model_validate` and use it in `test_held_state_plain_text.py`; add the `filterwarnings` entry to `pyproject.toml` (the plugin form `tests.fork_warning_guard` uses if the entry does not make the test fail, per design.md); run the whole suite once with the entry in place and record in the commit whether any other test raised the warning. Confirm the place design.md marks UNVERIFIED (that no production path puts a list in a tuple field) and correct the design where the code says otherwise.

## 3. [agent-build-kit] [tier1] The workflow policy is written down where the guard test points

Done when `AGENTS.md` has a "CI workflows" section giving the rule for action versions, the runner label, how to bump either and the cache-service note, and a test asserts the section exists and that the guard's failure message names it. Estimate: about 60 changed lines.

- [x] 3.1 Test: `tests/docs/test_ci_workflows_documented.py` asserts `AGENTS.md` has a heading `CI workflows`, that its text names the table in `tests/test_ci_workflows.py`, the exact-tag rule and the `ubuntu-24.04` pin, and that the message the guard prints contains the heading.
- [x] 3.2 Add the "CI workflows" section to `AGENTS.md`: every action at an exact release or a commit, on a release that runs on Node 24; the runner label is pinned and moved on purpose; the steps of a bump (read the release notes, edit the workflow and the table, open the first run's log); and that a cache-service warning during a GitHub incident is expected and not a failure.
