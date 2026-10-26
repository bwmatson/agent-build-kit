# acp-policy-covers-global-option-spellings

The pipeline's own command rules and its policy check now see through a tool's global options: `git -C <dir> commit
--amend`, `git -c k=v push origin main`, `gh -R owner/repo pr merge` and the raw-API spelling of a merge are judged as the
commands they are, not allowed because the subcommand is not the first word after the program. The policy check no longer
tries only the plain spelling of each forbidden class: it tries a fixed table of spellings, and `abk doctor` names the
spelling an agent lets through. An unattended agent ran an amend as `git -C <worktree> commit --amend` and nothing refused
it, and the check, which tried one spelling, could not have said so. The agent-side deny list is outside this change.
