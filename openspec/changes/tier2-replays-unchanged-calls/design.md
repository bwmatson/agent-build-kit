# Design

## What was checked, and what was not

Read in the code: the tier-2 tests start `abk tick` as a process with an environment from `process_env`
(`tests/forges/process_host.py`: a copy of the test's own environment, `PATH` with a stub, and
`ABK_GITHUB_API_URL` set to the in-process fake code host) and an agent command from
`<redacted>` written into the scratch `abk.yaml` under `runtimes.acp.command`
(`tests/integration/test_graph_acp_unit.py`, `test_acp_build_unit.py`). The fake host (`FakeGitHub`,
`tests/forges/github_server.py`) is a `ThreadingHTTPServer` on loopback in the test process. The acp runtime adds a
call's `request.env` to the agent's environment on top of the process environment (`runtimes/acp.py`); the
claude runtime does the same (`spawn`, `runtimes/claude_code.py`). The only model-endpoint setting in the code is
`gateway_url` (a usage-accounting gateway); no code sets a base URL for an agent.

UNVERIFIED, and the first task of group 1 to settle by running the tools: (1) whether the acp agent command
accepts a model endpoint override, by environment variable or argument, and which; (2) whether the claude runtime's
agent honours `ANTHROPIC_BASE_URL` and whether its credentials work against a proxy that forwards them; (3) how the
package tools are pointed at an index (the `uv` index setting and the `npm` registry setting are the usual
mechanisms; whether they reach the tool through an agent's subprocess environment is not shown); (4) that the
index's responses name a second host for the files themselves, which a package index proxy would have to cover
(an upstream of its own, with links rewritten when served, never in the stored body); (5) the model provider's
streaming formats. The proxy treats a body as bytes and a stream as the sequence of chunks it was received in,
so (5) matters only to the secret scan and the request summary, not to replay. An upstream that cannot be pointed
at the proxy is left out and the report says so; nothing in the design depends on a particular upstream being
reachable.

## Where the pieces live

- **`src/agent_build_kit/replay/`** (framework code, because the command line reads it): the cassette model, the
  key, normalisation, the cassette store, the review state and the report model. Models are `Frozen` pydantic
  models; the mode (`off`, `record`, `replay`, `live`), the upstream kind (`deterministic`, `<redacted>`) and a call's
  outcome (`hit`, `missed`, `unused`, `aged_out`) are `StrEnum`s.
- **`tests/replay/`** (test support): the reverse proxy and the pytest plugin. Their tier-1 tests sit beside them,
  as the fake code host's do. The proxy is the `ThreadingHTTPServer` pattern the fake code host uses, with `httpx`
  to the upstream. A reverse proxy, not forward or interception: the code under test is given a base URL, so there
  is no certificate to install, and the proxy speaks TLS to the upstream itself.
- **Mode** is a machine setting, `replay_mode` in `settings.py` (`ABK_REPLAY_MODE`, default `off`), because it
  differs per run and per machine and is not reviewed with the workspace. This corrects the idea of
  `tests.replay.mode`: `tests` is a per-repository section (`RepoConfig.tests`, markers and extras), and a
  per-run switch does not belong in a committed file.
- **Everything else** is a committed section, `repos.<name>.tests.replay` (`ReplayConfig` on `TestsConfig`), absent
  by default: the upstreams, the directory, the ages, the size controls, `review_after_runs`. A repository without
  it has no replay; `abk status` and `abk doctor` say nothing for it. A test suite whose workspace is a throwaway
  (the framework's own tier-2 tests write a scratch `abk.yaml`) passes a `ReplayConfig` to the plugin in code
  instead; the result is the same object either way.

## Upstreams and the in-stack host set

Each upstream is `name`, `url` (its real base URL), `kind` (`deterministic` or `<redacted>`) and `env` (the names of the
environment variables that point the code under test at the proxy's listener, set by the plugin in the
environment it hands to the test; for the code host, `ABK_GITHUB_API_URL`).

A host is in the stack, and so never replayed and never given a listener, when it comes from one of exactly these:

1. `verify.env`: each value, resolved as `Installation.verify_env` resolves it, that parses as an http or https
   URL (its host).
2. Each repository's code host in `repos`: for `forge: github`, the host of the `github_api_url` setting; for
   `forge: azure_devops`, the Azure DevOps host. A code host the workspace names for a repository is part of the
   unit under test; code-host replay is for a host the workspace does not name as a forge.
3. The machine settings that name stack endpoints: `gateway_url`, `prometheus_url`, `tempo_url`, `grafana_url`
   and the three OpenTelemetry endpoints.
4. Always: loopback (`localhost`, `127.0.0.0/8`, `::1`), `host.docker.internal`, private address ranges, and any
   single-label name (a container network name).

No other key contributes: `repos.*.dev_stack` is a script and names no host, and `runtimes.*.command`,
`environment`, `deploy` and `models` name none. The set is built by one function from a workspace and the
settings; at startup each upstream's host is checked against it and a match fails the run, naming the upstream
and the key that put the host in the set. A listener exists only for a configured upstream.

## The key

The key is a hash of what the upstream sees: method, path, query (sorted), an allowlist of headers that change the
answer (content type, accept, the API version header the provider uses, anything that selects a model) and the
body. A JSON body is canonicalised (sorted keys, no whitespace) after any declared rules. Credentials are never
in the key. Headers other than the allowlist are neither keyed nor stored, and a stored response keeps only an
allowlist of its headers. After a recording is made, the response body is scanned for each secret value the plugin
is given (the settings tokens, and any value the test names); a match fails the recording and nothing is stored.

## Normalisation is declared, never implicit

A volatile value in a request (a temporary directory prefix, a commit hash, a timestamp, a request id) makes two
identical logical inputs differ. A test may declare rules, each a pattern and a placeholder, on the cassette
header it passes to the plugin. Each rule is stored in the cassette it applied to and shown in the report. The
default is none, because a broad rule makes a replay match inputs that really differ, which is the failure this
change exists to prevent.

For a model, the conversation carries scratch paths and commit hashes that change on every run. Expect few model
hits until the fixtures are deterministic: fixed scratch locations, fixed commit dates and author data. Making
them deterministic is part of group 3 and is test work, not something the proxy does. The first acceptance run may
show no model hit; that is a finding to report, not a failure.

## Modes

`off`: all live, nothing recorded, no listener started. `record`: all live, the calls of a passing test are
written. `replay`: an exact, fresh match answers from the cassette; anything else goes live and the new answer is
recorded against its own key. `live`: all live, cassettes ignored, recordings written as in `record`; this is the
periodic refresh. A hit is only an exact key match.

## Recording only from a pass

A test's calls are written to a staging directory outside the repository, keyed by the test id. The plugin
reads the test's outcome from `pytest_runtest_makereport` (setup, call and teardown must all pass), then promotes
the staged cassettes to the cassette directory or discards them. A broken live run therefore never becomes the
truth. A recording made in `replay` mode for a miss goes through the same gate.

## Cassettes: location, compression, size

- **Location**: `tests/cassettes/<test id, path-safe>/<call index>-<key prefix>.json.gz` in the repository that
  owns the test (the directory is `ReplayConfig.directory`). Committed, so a replay works in CI and on another
  machine. The repository marks the directory binary in its attributes, so diffs do not print it.
- **One file per call, gzip-compressed JSON**: key, request summary, response, `recorded_at`, upstream kind and
  name, applied rules, model identifier when the response carries one, test id and call index, usage figures
  when present, and `needs_review` with its reason.
- **Request summary, not request body.** The request is stored as method, path, query, body size, body hash, and
  for a JSON body a digest per top-level field and per element of list fields (a conversation's messages), so a
  difference can be named ("differs at the system prompt") without storing prompts, which can hold secrets.
- **Size controls** in `ReplayConfig`: `max_body_bytes` per response body (default 2 MiB; a larger one is not
  recorded and the call is reported as `too_large`, live every time), and `max_directory_mb` (default 100;
  past it the report warns and nothing more is promoted). A stored body is written as received (its content
  encoding kept) so replay is byte-exact.
- **Local state that must not churn git**: `last_hit_at` and the count of runs a cassette has been unreviewed
  live in a gitignored file in the directory, not in the cassette. `needs_review` and its reason are in the
  cassette, so a review decision is shared. This corrects the plan's placing `last_hit_at` in the cassette.
- **Streaming** responses are stored as the chunk sequence received and replayed in order without timing.

## Which calls replay, and when they age out

`deterministic`: exact key and younger than `max_age_days` (default 30); older is a miss and is re-recorded,
because such an upstream still drifts (a new release). `<redacted>`: exact key over the whole conversation, tools,
model and sampling settings, and younger than `<redacted>_max_age_days` (default 14). The recorded model identifier is
shown in the report. The plan's idea that a response whose identifier differs from the provider's current one is
not used cannot be done without a live call, so it is not claimed; the controls are the age, the key including the
model selected, and the `live` refresh.

## Keeping recordings honest (group 2)

After every run the plugin writes a report per test and a total: hits, misses that went live (the key, and what
differed from the nearest earlier cassette for the same test and call index, from the digests), unused cassettes,
aged-out ones, the declared rules used, and billed calls avoided (from recorded usage figures, where a response
carries them). It is printed in the terminal summary by `pytest_terminal_summary`, written as a JSON file in the
state directory, and attached to each test as `user_properties` so a pytest report plugin sees it. A test that
replayed anything is labelled `replayed` with N of M external calls replayed and K live, and the report says which
parts proved nothing about the provider that day. The outcome is still pass or fail; the label is information.

A cassette the run did not ask for, or one superseded by a live recording for the same test and call index with a
different key, is marked `needs_review` and not deleted. A cassette whose test no longer exists is the same.
`abk status` prints a line with the count (in `cmd_status`) and `abk doctor` adds a check (to the list
`run_doctor` assembles): a note when some are waiting, a warning when one has been unreviewed past
`review_after_runs` (default 5) runs. The next run prints the same warning loudly; it does not fail a test,
because recordings are test support, not the product.

`abk replay review` is a new module, `agent_build_kit.cli.replay_cmd`, listed in `COMMAND_MODULES` in
`cli/__init__.py` and exposing `register(sub)` like the others. It needs an installation, since the cassettes
are those of the repositories with a `tests.replay` section. It lists each waiting cassette with the diff of
request summaries, and `--keep` or `--delete` per cassette decides it. A kept cassette is not marked again unless
it is superseded afterwards.

## Never hides a live regression

Recommended and documented: run `live` whenever the prompt text or the code under test changed (the key changes
anyway) and at least weekly otherwise. The label, the counts and the age limits are what keep a replayed pass from
passing for proof of the provider's behaviour.

## Group 3 and its fixtures

Uses one small scratch unit. The scratch application of `dry-guidance` group 4 (`dry_app`, in
`tests/dry_scratch.py`, built on `scratch_app`) is the natural one; that change need not have merged, and if it
has not, group 3 uses `scratch_app` (`tests/factories.py`) with the add-a-marker task of the existing acceptance
tests. The fixtures are made deterministic by group 3: fixed scratch locations and commit identity and dates. The
assertions are not weakened to obtain a hit. The deterministic upstream is asserted first; the model hit rate is
reported. Flake risk: model keys rarely match unless the whole context is static.

The build of the acceptance run is itself an e2e-test test in its own pytest session, so it runs under the e2e-test time limit, not the 60-second default. The replay and package-index proxies live as long as the build's `abk tick`, not as long as that session's limit: when a limit fires, the build must not find its proxies gone.
