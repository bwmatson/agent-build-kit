## From `unit-size-defaults-and-estimates/1`

- The proposal says `abk report` (which exists: cli/report_cmd.py) should show estimated against actual per unit. Neither the design, the spec requirements nor the tasks carry that, so this unit rightly leaves it out. A later change could add an actual_lines column next to the estimate in usage_report.
- A restack after a parent merges (events.restack → push_with_lease) does not re-record actual_lines. Either record it there or narrow the 'after each push' wording in CHANGELOG.md and docs/architecture.md.
- GitHubForge.pr_files could be derived from pr_changes so the paged list_files call is written once.
- src/agent_build_kit/pipeline/events.py:1537 — When a parent merges and the restack pushes the child, the child's actual_lines is not recorded again. Only a push that goes through the unit graph (PUSH → OPEN_PR → build_open_pr) records it.
- src/agent_build_kit/forges/github.py:459 — pr_changes and pr_files make the same paged list_files call. pr_files could be written as [c.path for c in self.pr_changes(...)].
- src/agent_build_kit/forges/github_models.py:59 — FileDoc.additions and FileDoc.deletions default to 0. A response that lacked them would count as a 0-line PR instead of failing to parse.
