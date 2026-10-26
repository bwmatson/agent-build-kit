## From `tier2-runs-on-a-schedule/1`

- src/agent_build_kit/cli/pipeline.py:664 — `abk status` decides whether to print by comparing the stored note to an exact string (`unit.note == NO_TEST_RAN`). The `set_state` docstring (unit_store.py:608-609) says the note is prose for people and nothing reads it.
- src/agent_build_kit/pipeline/wiring.py:2140 — `E2eSession.run` calls `_work` a second time only to look up each run's toolchain by `where`, even though `e2e_scope` already had it.
- src/agent_build_kit/pipeline/wiring.py:1975 — `E2eScope.ids` adds every id under a project whenever any of that project's commands takes some id, so it can list tests that no command runs. In a workspace repo, root `where` gets both members' ids, even though only one member's command took any.

## From `tier2-runs-on-a-schedule/2`

- Two changelog bullets now describe this one change: group 1's `e2e_unit_scope` bullet and this `e2e_schedule` bullet. The convention says one change is one bullet across pull requests, so tasks 4.4/4.5 should fold them into one when they write the final entry.
- The design says a change with no `specs/` is accepted by `openspec archive` and that `abk check` only warns. The builder added `.openspec.yaml` with `skip_specs: true` so that strict validation passes (I checked the integration test, and the key exists in the pinned OpenSpec CLI). The design in the planning repo should record this, as task 2.5 asks.
- src/agent_build_kit/pipeline/e2e_schedule.py:88 — `_write_change` makes the change directory first and then writes four files one at a time. If the tick dies partway, the directory is left without `tasks.md` (or with only some of its files).

## From `tier2-runs-on-a-schedule/3`

- src/agent_build_kit/pipeline/wiring.py:2392 — The `E2eSession.run` docstring still says that on the dev stack nothing is classified. A scheduled unit's run on the dev stack now does set `verdict`, through `_scheduled_verdict`.

## From `tier2-runs-on-a-schedule/4`

- tests/cli/test_tick_scheduled_e2e.py imports tick_pass twice (`from tests import tick_pass` and `from tests.tick_pass import isolate`). One import style would read more cleanly.
