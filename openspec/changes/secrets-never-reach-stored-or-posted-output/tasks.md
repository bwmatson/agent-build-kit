# Tasks

Acceptance: none — tier-1 tests over generated output prove it: text is built from fakes holding sample values and what each boundary stores or sends is read back.

Priority: 1

## 1. [agent-build-kit] [unit-test] A redaction function replaces known secret values by name

Done when there is a function that takes text and returns it with each known secret value replaced by `[redacted:<NAME>]` and token-shaped strings by `[redacted:token-shape]`, built from a set that holds every source under its own name and is rebuilt when settings reload.

- [x] 1.1 Test: the set gathered from a configuration holds each source under its own name (`verify.env`, each credential setting, `runtimes.*.env`, the `redact` list, a minted
      gateway key), is rebuilt when settings reload, shows names only when printed, and leaves out a value whose provider fails with one warning that holds no value.
- [x] 1.2 Test: redaction replaces an exact case-sensitive value with `[redacted:<NAME>]` and nothing else of the value; a value inside a URL and after `Bearer ` keeps the rest of the
      string; two secrets in one string, one twice, are each replaced under their own name; a value that contains another is replaced whole; a value of 7 characters and a value of
      `true` are left alone, and a value of 8 is replaced.
- [x] 1.3 Test: a string shaped like a `sk-`, `ghp_` or `github_pat_` token that is not in the set becomes `[redacted:token-shape]`; a 52-character plain string is untouched.
- [x] 1.4 Add the redaction module (the set, the function, the token shapes, the failure notice), the `redact` setting in the configuration model, the settings module's list of
      credential fields, and gather the set at tick start and settings reload; register each minted gateway key.

## 2. [agent-build-kit] [unit-test] Stored and printed output is redacted before it is written

Done when no known secret value appears in a unit's saved feedback, run log, transcript, the usage ledger, tier-1 or tier-2 output or the printed output, and a redaction failure withholds the text without changing a tier-2 verdict.

- [x] 2.1 Test: the unit store's `set_feedback` holds the replacement for each feedback source; a tier-2 failure whose output holds a value is saved and said to the run log without
      it; the run log, a whole agent reply in it, the printed output and the usage ledger's `outcome` hold the replacement.
- [x] 2.2 Test: a transcript tool result longer than its limit with the value before the limit holds no part of the value; tier-2 output with the value straddling the 4000-character
      cut holds none.
- [x] 2.3 Test: when redaction raises, feedback, a run log line, a transcript event and a ledger line hold `[redaction failed: text withheld]`, the tier-2 counts and
      verdict are unchanged, and exactly one log line records the failure with neither the text nor the exception's message.
- [x] 2.4 Apply it at the unit store's `set_feedback`, the run log's `emit`, the transcript's `record` (before the result cut), the printed output, the ledger append, tier-2 output
      (before `[-4000:]`) and tier-1 output.

## 3. [agent-build-kit] [unit-test] Posted text and rework prompts are redacted, and the set's leaks are guarded

Done when no known secret value appears in a posted body or a rework prompt, the acceptance tests' failure messages do not show the environment, and `abk doctor` warns about weak or unset secret names.

- [x] 3.1 Test: the pull request description built from a failing e2e-test holds the replacement in its "Full output" block; a posted comment and a posted status description sent to a
      fake host hold the replacement; the status description is still the counts.
- [x] 3.2 Test: a rework prompt assembled from feedback saved with a value holds the replacement and the stored feedback is unchanged by assembly.
- [x] 3.3 Test: when redaction raises, a posted body holds `[redaction failed: text withheld]`, the tier-2 counts and verdict are unchanged, and exactly one log line records the
      failure with neither the text nor the exception's message.
- [x] 3.4 Test: `Scratch` in both acceptance tests omits `env` from its repr; a tier-1 test builds each test-support model under `tests/` that has an `env`/`environ` mapping field with
      a sample value and fails, naming the model, when the value is in its repr; a `Settings` field whose name ends in `token`, `key`, `pat` or `secret` that is neither a listed
      credential nor on the not-a-secret list fails.
- [x] 3.5 Test: `abk doctor` warns, by name, for a configured `verify.env` or `redact` variable whose value is under 8 characters, and for a `redact` name that is not set.
- [x] 3.6 Apply it at the forge's write methods (titles, bodies, comments, statuses) and the rework prompt assembly. Add `repr=False` to `Scratch.env` in both
      acceptance tests, and add the doctor warnings.

## 4. [agent-build-kit] [unit-test] The operator can redact history already saved

Done when `abk redact-history` reports and, on request, rewrites the saved files, and the architecture and configuration docs and the changelog describe the boundaries.

- [x] 4.1 Test: `abk redact-history` without `--apply` reports files and names, writes nothing and prints no value; with `--apply` it replaces the values in the unit store, run logs,
      transcripts and ledger, keeps a copy of each changed file, reports nothing on a second run, and makes no call to a code host.
- [x] 4.2 Add the temporary command `abk redact-history` (dry run by default, `--apply`, a copy kept beside each changed file).
- [x] 4.3 Update `docs/architecture.md` (the boundaries, the journal now redacted, the token shapes as heuristics) and `docs/configuration.md` (`redact`), add a changelog entry that
      says history already saved is not rewritten, names `abk redact-history` as temporary, and says a secret sent to a provider cannot be recalled and rotation is the operator's decision.
