# Design

## What the incident was, exactly

- The printed dictionary was the acceptance fixture's `env`: `process_env(...)` starts from a copy of the whole process environment (leaving out only `GH_TOKEN` and
  `ABK_GH_TOKEN`) and adds to it. In a tier-2 run the child's environment is `{**os.environ, **verify.env}` (`E2eSession`), so the dictionary held the ambient environment as well
  as `verify.env`. A secret exported in the shell that runs `abk` is exposed the same way as one resolved from `verify.env`. The set below therefore cannot be only `verify.env`; the
  repr rule is the root fix and redaction the net.
- Two acceptance tests declare a `Scratch` model with an `env` field (the ACP build-unit test and the graph-ACP test); the model is frozen pydantic, so its repr lists every field.

## What leaves a run today

| Text | Where it goes |
|---|---|
| tier-2 output | `E2eResult.output` (last 4000 characters) -> `build_snapshot` -> the PR description's "E2e-test results" section, "Full output" block; and `snapshot` returned to the graph node |
| tier-2 or tier-1 failure | `set_feedback` -> `runs/units.json`; the run log via `say`; the journal; later the rework prompt |
| commit status | `post_status` sends the context, ok and a description of counts and seconds only (`"N passed, M failed in Ss"`, cut at 139 characters). **The status never carries output.** |
| PR description | `create_pr` / `update_pr` bodies, from `build_pr_body`: the snapshot, open points (feedback of a unit that spent its rounds) |
| comments | `post_comment` in the reply step: an agent's replies to reviewers |
| run log, transcript | files under the state directory, appended per entry |
| usage ledger | `UsageRecord` lines; the free-text field is `outcome`, with `unit`, `node`, `model` and the other strings |

## The set of known values

Built by one function from the active installation and settings, as a mapping from name to value:

- every `verify.env` value, named by its variable (`Installation.verify_env()` resolves them, and a command provider runs a subprocess to do so, which is why the set is built once
  and not on each use);
- every credential field of `Settings`: `gh_token`, `ado_pat`, `gateway_master_key`, `grafana_token`. A field is a credential by being listed in the settings module's one tuple of
  credential field names, so a new credential field is a one-line addition, and a test fails when a `Settings` field whose name ends in `token`, `key`, `pat` or `secret` is not in
  that tuple or on an explicit "not a secret" list;
- every value in `runtimes.*.env`, named `runtimes.<runtime>.<VAR>`;
- the value of every environment variable named in the new `redact` list (`redact: [NAME, ...]` in abk.yaml), read from the process environment and the planning root's `.env`, so a
  secret the framework has no field for can be added without a code change;
- each per-call key the gateway layer mints, added at `begin` under the name `gateway-key`, kept until the process ends. The key is revoked at `finish`, but text written before the
  revoke still holds it, and keeping a revoked key in the set costs a few bytes.

A value that cannot be resolved (a provider that fails) is left out and named in one warning, without a value; it must not stop the tick, since redaction is a protection and not a gate.

### Matching

- By value: an exact, case-sensitive substring. Longer values are replaced first, so a value that contains another is replaced whole.
- **Minimum length 8.** A shorter value is not redacted. The reasons: short values in configuration are overwhelmingly not secrets (`1`, `true`, a port, a region name); replacing them
  would turn every `1` in a test log into `[redacted:NAME]` and make failures unreadable; and a secret of fewer than 8 characters is guessable and protects little, so redacting it is
  false assurance. Eight is also longer than any word in the framework's own output that a variable holds. `abk doctor` warns, by name, for a configured variable whose value is shorter
  than 8, so the gap is visible.
- A value found inside a larger string (a URL with a key in it, `Bearer <key>`, a path) is replaced in place; the rest of the string stays.
- The replacement is `[redacted:<NAME>]`. The name is the source variable; the value, a prefix of it, and its length are never written.
- Redaction runs **before** any cut. E2e-test keeps the last 4000 characters, and the transcript cuts a tool result at its limit; a cut through a secret would leave a half that matches
  nothing. Redaction therefore applies to the whole text, then it is cut.
- A secret split across two transcript events is not found. Each event is one tool result, message or reply, and joining events to search across them is not attempted.

### Token shapes (the second net)

After the value pass, text is searched for: `sk-` followed by 20 or more of `[A-Za-z0-9_-]`; `ghp_`, `gho_`, `ghu_`, `ghs_` or `ghr_` followed by 36 or more alphanumerics;
`github_pat_` followed by 22 or more of `[A-Za-z0-9_]`; and the value after `Authorization: Bearer ` or `Bearer ` of 20 or more token characters. A match is replaced by
`[redacted:token-shape]`. **Patterns are heuristics.** They miss a key with no recognisable prefix (an Azure DevOps PAT is 52 plain characters, which no pattern here claims) and they
can match a harmless string that looks like a key. The set is the guarantee; the patterns catch a secret nobody configured, such as one a test printed from a vault.

## Where it is applied

One function, `redact(text) -> str`, held on a small object (the set is private to it, and its repr shows names only). It is applied at the last step before text leaves:

- `set_feedback` in the unit store, for every source, so no caller has to remember it;
- the run log's `emit` and the transcript's `record` (the text of an event, before the tool-result cut);
- the pipeline's own printed output (`say`), because the journal is stored by the service manager and the same output is printed;
- the usage ledger's string fields at append;
- the tier-1 and tier-2 result text where it is made (`E2eSession` output before `[-4000:]`; the checks' output in the tier-1 step), so the snapshot, feedback and journal all start
  clean;
- everything handed to the forge for writing: PR titles and bodies, comments, and a status description. The status carries counts only today, but the boundary is the forge's write
  methods, not what the status happens to hold now;
- the prompt a rework agent is given: the stored feedback is redacted again as the prompt is assembled. This is the line that protects the provider from history that was saved before
  this change and has not yet been cleaned.

Putting the call at the store, the writers and the forge's write methods, and not in every caller, is the design: callers are many and change; the places text is stored or sent are few.

## Computed per tick, never persisted

The set is built when a tick starts (at `Installation.activate`, which also reloads settings) and again when settings reload. It lives in memory only. It is not logged, not in
telemetry attributes, not in the checkpoint database, and not in the usage ledger. A line that reports it says how many names it holds, and nothing else. The object's repr and
`str` show names only, and a test prints it to prove it.

## Failure behaviour

If `redact` raises, the text is not written. In its place goes `[redaction failed: text withheld]`, and one log line records the failure's type and where it happened, never the text
or the exception message (which can quote it). For a tier-2 result the counts and pass/fail stay and only the output is withheld; for feedback, the notice is the feedback, so the
rework agent is told to look at the run on the machine. A run log or transcript entry becomes the notice. The pipeline does not stop for a redaction failure: it is a protection that
fails closed for the text, not for the run.

## The test-support rule

The root fix is that the acceptance tests do not print the environment. `Scratch.env` becomes `Field(repr=False)` in both tests that declare it. A tier-1 test walks the test-support
models under `tests/` (every class a fixture or helper returns that has a field typed as a mapping of strings to strings and named `env`, or `environ`) and fails for any whose repr
contains a value from a sample environment. A new such object that forgets the rule fails the suite instead of the next incident.

## History already saved

This change does not rewrite what is stored: units.json, run logs, transcripts and the ledger on an installation keep what they hold, and the pull request descriptions already posted
keep theirs. Two protections apply meanwhile: the rework prompt is redacted as it is assembled, and the cleanup command below.

### One-time cleanup: a temporary command, justified

A documented manual step is not enough here. The values to look for come from the configuration and several providers (an env file, a command, a YAML path), so a person would have to
resolve and grep each by hand across a JSON store, a directory of logs and JSON-lines files, and a mistake in editing units.json by hand loses the store. The command builds the same set the
pipeline does and reuses the same function, so it is little code. It is temporary: `abk redact-history` takes the state directory of the active workspace, defaults to a dry run that
reports, per file, which names were found (never the values), and rewrites only with `--apply`, keeping a `.pre-redact` copy of each changed file beside it for the operator to delete.
It does not touch pull request descriptions or comments on the host; those are the operator's to edit or delete by hand. Temporary commands in this project have been removed once run
(`abk usage backfill-costs` was), so a follow-up TODO to remove this one is recorded in `follow-ups.md`, to be done when each installation's dry run reports nothing.

## Decisions

- The status carries no output today, so the brief's concern about a posted status is met by the forge-write boundary, not by a change to `post_status`. The place the full output is
  posted is the PR description.
- Journal output is redacted. That changes the run-logs capability's "the journal still receives everything" requirement, which is MODIFIED here.
- Rotation is not automated. The operator decides, and the change's output tells them which names were exposed where.
