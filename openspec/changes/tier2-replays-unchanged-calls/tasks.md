# Tasks

Priority: 4

## 1. [agent-build-kit] [unit-test] A record/replay proxy with cassettes keyed by the request

Done when a proxy in front of a fake upstream records a passing test's calls, replays an identical request and
goes live on any difference, with nothing secret stored.

- [x] 1.1 Settle first, and write down in `docs/agent-runtimes.md`, the UNVERIFIED points of design.md: how each
      agent the tier-2 tests start is pointed at a model endpoint, how the package tools are pointed at an index
      (and the second host for files), and the model provider's streaming formats. An upstream that cannot be
      pointed is left out and said so; stop and report if none can.
- [x] 1.2 Test: a request with the same method, path, query, allowlisted headers and body gives the same key;
      a different body, query, path, or allowlisted header gives another; a different credential header gives
      the same key and appears in no cassette.
- [x] 1.3 Test: against a local fake upstream, `replay` mode answers an identical request from the cassette
      without the upstream being called, and a request differing in body, query, path or model goes to the
      upstream and is recorded under its own key.
- [x] 1.4 Test: nothing is recorded before a passing test: a test that fails leaves no cassette in the directory,
      and one that passes promotes exactly its staged calls.
- [x] 1.5 Test: a secret value in a response body fails the recording and stores nothing; secrets in request
      headers are in no key and no file.
- [x] 1.6 Test: with no declared rule two requests differing in a temporary directory prefix miss; with a
      declared rule they hit, and the rule is stored in the cassette and listed in the report.
- [x] 1.7 Test: a `<redacted>` cassette replays only on an exact key and not past `<redacted>_max_age_days`; a `deterministic`
      one past `max_age_days` is a miss and is re-recorded; the ages are read from `ReplayConfig`.
- [x] 1.8 Test: the in-stack host set is built from exactly the keys of design.md (`verify.env` URL values, the
      repositories' code hosts, the stack settings, loopback and single-label names), nothing else contributes,
      an upstream whose host matches fails at startup naming the key, and a host in the set is never given a
      listener.
- [x] 1.9 Test: mode `off` starts no listener and changes no environment; `live` ignores cassettes and writes
      new ones after a pass; the mode is the `ABK_REPLAY_MODE` setting and an unknown value is refused.
- [x] 1.10 Test: a streamed response is stored as its chunk sequence and replayed in the same order; an
      oversized body is not recorded and is reported; a gzip-encoded body is replayed byte for byte.
- [x] 1.11 Add `src/agent_build_kit/replay/` (`Frozen` models, `StrEnum`s for mode, kind and outcome; key,
      normalisation, store) and the `replay_mode` setting in `settings.py`.
- [x] 1.12 Add `ReplayConfig` to `TestsConfig` in `config.py` (upstreams, directory, ages, size limits,
      `review_after_runs`), absent by default, with a test that a misspelled key is refused.
- [x] 1.13 Add the proxy and the pytest plugin under `tests/replay/` (fixture that yields each upstream's
      address and the environment to hand the code under test; promotion from `pytest_runtest_makereport`).
- [x] 1.14 Document the proxy in `docs/agent-runtimes.md` (the test markers paragraph) and the config and setting
      in `docs/configuration.md`, and add a changelog entry.

## 2. [agent-build-kit] [unit-test] Recordings stay honest: staleness, review and the report

Needs: fix-flaky-tests-replay-test-replay-proxy-edges-py-test-an-ups-8fa56e03 group 1 merged — flaky test tests/replay/test_replay_proxy_edges.py::test_an_upstream_that_cannot_be_reached_is_answered_502_and_nothing_is_recorded

Done when a run reports what replayed and what went live, a recording no longer used is held for review, and
status and doctor say how many wait.

- [x] 2.1 Test: after a run the report lists the calls hit, the misses that went live with the difference from
      the nearest earlier cassette for the same test and call index ("differs at the system prompt", "path
      differs"), the unused cassettes, the aged-out ones, and the declared rules used.
- [x] 2.2 Test: an unused cassette and one superseded by a live recording for the same test and call index are
      marked `needs_review` with a reason and are not deleted.
- [x] 2.3 Test: a replayed test is labelled `replayed` with N of M external calls replayed and K live, in the
      terminal summary and in the test's `user_properties`, and its outcome is unchanged; a test that replayed
      nothing carries no label.
- [x] 2.4 Test: billed calls avoided are totalled from recorded usage figures, and a response without figures
      adds nothing.
- [x] 2.5 Test: `abk status` prints the count of cassettes waiting for review and `abk doctor` has a note for
      some waiting and a warning for one unreviewed past `review_after_runs`; neither prints for a repository
      with no `tests.replay` section.
- [x] 2.6 Test: `abk replay review` lists each waiting cassette with the diff of request summaries, `--keep`
      clears the mark and `--delete` removes the file.
- [x] 2.7 Test: a set unreviewed past `review_after_runs` makes the next run print a warning and does not fail
      it.
- [x] 2.8 Test: `last_hit_at` and the unreviewed-run count change a gitignored state file and not the committed
      cassette.
- [x] 2.9 Add the report, the review marks and the local state to `src/agent_build_kit/replay/` and to the plugin.
- [x] 2.10 Add `agent_build_kit.cli.replay_cmd` (`register(sub)`), list it in `COMMAND_MODULES` in
      `cli/__init__.py`, add the count line to `cmd_status` and the check to `run_doctor`.
- [x] 2.11 Document the report, the review command and the live refresh in `docs/agent-runtimes.md`,
      `docs/cli.md` and `docs/configuration.md`, and add a changelog entry.

## 3. [agent-build-kit] [e2e-test] [acceptance] A live pass, a replay, and a changed input going live


Needs: tier2-tests-are-tagged-by-runtime group 18 — parked until the live tests are tagged by runtime and the drift test guards them, so an ACP test that cannot run (the model backend is out of budget) is held instead of failing
Split: claude_code

Done when one scratch unit is built live and recorded, rebuilt from the recordings, and rebuilt with one input
changed, and the proxy behaved as the first two groups say each time. The acceptance runs on Claude Code only: the
acp split is held (its model backend is out of budget), so a `runtime_acp` test here would park and run nothing.
Estimate: about 120 changed lines.

- [x] 3.1 Test: `tests/integration/test_replay_unit.py`, marked like the other acceptance tests. Make the fixtures
      deterministic first (fixed scratch locations, commit identity and dates) and use the `dry-guidance` group 4
      scratch application if it exists, `scratch_app` otherwise. Step one, in `record` mode with the Claude Code agent: the test passes and cassettes
      were promoted. [Review point 3.1 (round 1) is already fixed, commit 40ec5a8a; the changes below are the
      Claude-only conversion of that code.]
- [x] 3.2 Test: the build the three steps run (`tests/integration/replay_unit_build.py`) is an e2e-test test in its own
      session: collecting that file under the options the driver passes shows its test carries the `local_stack`
      marker, so it runs under the e2e-test time limit and not the 60-second default. (The file has no marker today
      and the driver runs it with `-o addopts=`, so the build is cut at 60 seconds: `test exceeded the time limit
      of 60 seconds`.)
- [x] 3.3 Test: the replay proxy and the package-index proxy stay up until the scratch build's `abk tick` has
      exited. Assert with a fake long-running child that a request made after the time the session's limit would
      have fired is still answered, and that the proxies stop only after the child is gone. (Today the proxies
      belong to the inner session, which ends at 60 seconds while the build is running; the agent then meets
      `Connection refused` on the proxy port.)
- [x] 3.4 Test: the model hit rate in the report counts only the recorded model calls that were asked for again
      and hit. With one recorded model call that is not asked for again and one miss, the rate is below 100%.
      (Today `replayed_model` removes the recorded keys that are absent from the misses' keys; a miss's key is
      never a recorded key, so nothing is removed and the rate is always 100%.)
- [x] 3.5 Test: step two in `replay` mode: the calls to the deterministic upstream with an identical key were
      replayed, the result is labelled `replayed` with the counts, and no billed model call was made for the
      calls replayed. Assert the deterministic upstream first; report the model hit rate and do not weaken any
      assertion to obtain a hit. Zero model hits is a valid finding.
- [x] 3.6 Test: step three: edit the task text and run again in `replay` mode. Exactly the calls whose request
      changed went live, a new cassette was written for each, the old one is marked `needs_review`, and the
      report names the difference.
- [x] 3.7 Add the fixture determinism work and the three-step driver (test code only).
- [x] 3.8 Document how to run it and the weekly `live` refresh in `docs/agent-runtimes.md`.
- [x] 3.9 Make the acceptance Claude-only, in `tests/integration/replay_unit_build.py` and `test_replay_unit.py`.
      The helper builds its scratch with `runtime_scratch("claude_code", ...)` (it was `"acp"`, at
      `replay_unit_build.py:118`). The three tests carry `runtime_claude_code` instead of `runtime_acp`: not
      `RUNTIME_PARAMS`, and no module-level `runtime_acp` `pytestmark` (`tests/runtime_tags.py` refuses two runtime
      tags); where a fixture must be parametrized use `CLAUDE_CODE_PARAMS`, as `tests/integration/test_graph_unit.py`
      does. The three `ACP_ONLY_REASONS` entries are deleted. Test: collecting the module under
      `-m "local_stack and runtime_claude_code"` selects the three tests and under `runtime_acp` none.
- [x] 3.10 Test: `test_the_unit_is_built` is a helper that the driver runs by id, not a test of the suite, and when
      `ABK_REPLAY_UNIT_ROOT`, `ABK_REPLAY_UNIT_CASSETTES` and `ABK_REPLAY_UNIT_MARKER` are not all set it is skipped
      with a reason naming the missing ones (a module-level `skipif`), not an error: the kit's e2e selection names
      it by id and it died without its environment. With all three set it is collected and runs as before.
- [x] 3.11 Test: the agent's model calls are recorded and replayed through a plain-http proxy at
      `ANTHROPIC_BASE_URL`, with these measured facts (Claude Code 2.1.303, 2026-10-19) as requirements of the
      acceptance. Login works through a plain-http proxy; the model upstream is `https://api.anthropic.com`, call
      `POST /v1/messages?beta=true`. Across two runs from the same working directory the only request field that
      varies is `metadata.user_id`, a JSON string holding a `session_id` UUID; from a different working directory
      the environment block text and the memory-directory path in `system[2]` vary too, so the scratch root stays
      fixed (it already is: `ABK_REPLAY_UNIT_ROOT`) and no rule hides a path. The one normalisation is a `Rule`
      (`agent_build_kit.replay.models.Rule`: `pattern`, `placeholder`, applied by `re.sub` to the request body text,
      path and query before keying, stored in the cassette and listed in the report), a regex rule, declared on the
      model upstream's `ReplayConfig` in `replay_unit_build.py`. Its pattern matches the UUID after `session_id` as
      it stands in the body, where the `user_id` string is JSON inside JSON (the quotes are escaped), and its
      placeholder keeps the text before it, so no other field is touched. Assert that two requests differing only in
      that UUID have the same key, that a request differing in any other field (a message, the model, the system
      text) has another, and that step three below is not weakened: the edited task text still changes the
      conversation, so those calls go live.
