# ci-gives-npm-a-longer-timeout

The CI `integration` job failed on 2026-10-21 and 2026-10-22 because npm was slow, in two places: the step "Fetch the pinned OpenSpec CLI" timed out on all three
attempts at 120 s (runs 39711881837 and 39714359908; the same package fetched fine at 03:07), and the vitest test in
`tests/integration/test_node_npm_red_command_vitest.py` hit the 60-second per-test limit while `npx vitest` downloaded vitest (runs 39666378362 and
39711335246). This change raises the per-attempt npm timeout in `.github/scripts/warm-openspec.sh` from 120 s to 300 s (an env var, `OPENSPEC_ATTEMPT_TIMEOUT`,
default 300; still three attempts), raises the step's `timeout-minutes` from 10 to 20, and lets one test carry its own time limit through a new
`time_limit(seconds)` marker, which the vitest test sets to 180. It helps when the registry is slow, not when it is unreachable, and adds no lockfile.
Priority 1.
