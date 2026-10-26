## Planned from `secrets-never-reach-stored-or-posted-output`

- TODO: remove the temporary `abk redact-history` command, its tests and its section in `docs/cli.md`, once it has been run with `--apply` on each installation with stored history and
  a second dry run reports nothing found. Keep the redaction function and the set; only the command is temporary. This is the same removal made for `abk usage backfill-costs`.
## From `secrets-never-reach-stored-or-posted-output/1`

- The planning repo's change still lists `runtimes.*.env` as a redaction source in task 1.1 and design.md. The builder removed that source, so a person should update the spec and design to say no runtime env setting exists today. Otherwise the specs describe a source the code does not read.

## From `secrets-never-reach-stored-or-posted-output/2`

- The commit-gate prompt (COMMIT_FIX_PROMPT) still sends raw tool output to the agent. That is a prompt to the provider and belongs to group 3's prompt work, so a later unit of this change should cover it.

## From `secrets-never-reach-stored-or-posted-output/3`

- tests/forges/test_comment_exists_redaction.py imports `top_level` from another test module (tests/forges/test_azure_landed_reads.py:91). Moving it into a shared fixture module such as tests/forges/azure_answers.py would stop test modules from depending on each other.
- redaction.sources still calls the private `installation._resolve`, and doctor's `_verify_env` resolves the providers a second time. This was already the case before this round. A public resolve helper, or reusing the values `sources` already resolved, would remove the import of a private name and the extra provider subprocess.

## From `secrets-never-reach-stored-or-posted-output/4`

- src/agent_build_kit/redaction.py:82 — `found` checks each value with a separate `value in text` test. `redact` uses one compiled alternation, longest value first. The two can disagree when one configured value is a substring of another.
