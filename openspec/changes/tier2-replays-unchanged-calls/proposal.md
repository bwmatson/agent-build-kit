# Proposal

## Why

Tier-2 acceptance tests run a real agent against a real local stack and bill per token for minutes. The same run
repeated with nothing changed pays again for answers it already had: the model provider's, the package index's, a
code host's. Mocking these by hand hides regressions; a blanket mock is wrong as soon as an input differs.

The rule that keeps replaying honest is that a recorded answer is valid only for the request it was recorded
against. This change adds a record/replay proxy for the calls that leave the stack, keyed by the request, that
records only after a passing live run, replays only on an identical request, goes live on any difference, and
holds a recording that is no longer used for a person to review.

## What Changes

- **A reverse proxy for test runs**, one listener per configured external upstream, with a cassette per call keyed
  by a canonical hash of what the upstream would see. Credentials are never in a key or a cassette.
- **Modes** `off` (default), `record`, `replay`, `live`, set per run in a machine setting.
- **Two kinds of upstream.** A deterministic one (package index, code-host reads) replays on an exact key up to a
  maximum age; a model one replays only on an exact key over the whole conversation, with a shorter age.
- **A replay report** per test and in total: hits, misses that went live, unused, aged out, declared
  normalisations, and billed calls avoided. A run that replayed anything is labelled `replayed`.
- **Review of recordings no longer relevant**: marked `needs_review`, counted by `abk status` and `abk doctor`,
  resolved by a new `abk replay review`; a stale unreviewed set warns the next run.
- **An acceptance test** proving a live pass, a replay, and a changed input going live.

## Impact

- Capability: `test-coverage` (added requirements).
- Code, in the agent-build-kit repository: a `replay` package for the cassette format, key, store and report
  (used by the proxy and by the command line), the proxy and a pytest plugin under `tests/`, one setting, a
  `tests.replay` config section, one new command module, a line in `abk status` and a check in `abk doctor`.
  No pipeline behaviour changes: with the mode `off` nothing differs.
- Docs: `docs/agent-runtimes.md` (test markers), `docs/configuration.md`, `docs/cli.md`, the changelog.
- Not done here: pointing the agent runtime at the proxy is UNVERIFIED (see design.md); the first task of
  group 1 settles it, and the change's scope narrows to the upstreams that can be pointed.
