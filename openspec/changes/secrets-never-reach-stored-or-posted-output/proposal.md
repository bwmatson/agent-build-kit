# Proposal

## Why

A tier-2 acceptance run failed with an assertion whose message printed the test fixture's `Scratch` object, and that object's repr includes `env`, a copy of the environment the
tests run in. The dictionary included a gateway key that `verify.env` resolves for the live-stack tests. Pytest's whole output then travelled the way every failure text does:

- e2e-test captured it in `E2eResult.output` (the last 4000 characters of a failing command) and `build_snapshot` put it in the "E2e-test results" section, inside a "Full output"
  details block;
- the graph's `e2e-test` node saved the same text as the unit's `feedback` in the unit store (`runs/units.json`) and said its last lines into the run log;
- the rework agent is given that feedback as its prompt, so on a rework the key would have been sent to the model provider;
- the pull request description built from the snapshot carries the "Full output" block, and is written to the code host by `create_pr` and `update_pr`.

The same exposure exists for any value the pipeline passes on through configuration: `verify.env` values, the code-host token (`GH_TOKEN`, `ABK_GH_TOKEN`), the Azure DevOps PAT
(`AZURE_DEVOPS_EXT_PAT`, `ABK_ADO_PAT`), the gateway master key, the per-call keys the gateway layer mints, `runtimes.*.env`, and the Grafana token. Nothing in the pipeline looks
for a secret before text is stored or posted.

## What Changes

- **One redaction over known values.** A set of secret values is gathered from the workspace configuration and the settings, and one function replaces each occurrence with
  `[redacted:<NAME>]`. A second pass over well-known token shapes is a net for what the set does not hold.
- **Applied where text leaves a run:** saved feedback, run logs, transcripts, the pipeline's printed output, the usage ledger's text, tier-1 and tier-2 result text, the pull request
  description, posted comments and statuses, and the prompt a rework agent is given.
- **The set is built once per tick** and rebuilt when settings reload; it is never logged or written to disk.
- **Redaction that fails withholds the text:** a short notice is stored or posted in its place and the failure is logged without the text.
- **The framework's own tests do not print the environment:** the acceptance tests' `Scratch` object leaves `env` out of its repr, and a tier-1 test fails for any test-support object
  that carries an environment dictionary in its repr.
- **History is not rewritten by this change.** A temporary command, `abk redact-history`, lets the operator redact what is already stored; a follow-up removes it after it has run.

## What this cannot do

- A secret already sent to a model provider cannot be recalled. This change stops the next send.
- Text already posted to a code host is not edited by this change.
- Whether a key that reached any stored or posted text is rotated is the operator's decision. The change makes it possible to find out (the cleanup command's dry run reports which
  stored files held which names) and nothing more.

## Impact

- agent-build-kit: a redaction module and its set builder, the unit store's `set_feedback`, the run log, the transcript, the usage ledger writer, the tier-2 session and tier-1 result
  text, the pull request body and comment posting, the rework prompt assembly, the gateway layer's mint, the tick start, the two acceptance tests' `Scratch` classes, one temporary
  command, `docs/architecture.md`, `docs/configuration.md` (the `redact` list) and the changelog.
- Configuration: an optional `redact` list of environment variable names whose values count as secret.
