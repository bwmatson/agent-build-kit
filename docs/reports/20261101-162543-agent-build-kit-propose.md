# Propose 20261101-162543 — agent-build-kit

Tracker refresh: `grafana-url-env-test` and `agui-read-events-test` are both still in flight under `openspec/changes/`; left as-is. The health entries carry no unactioned candidates, so the only source was the improve run of this date.

## Issues chosen

1. **AGENTS.md layout incomplete** — improve candidate 2. Ten source packages and `docs/designs/` are missing from the layout block.
2. **Work tracker undocumented** — improve candidate 1. No architecture or CLI section, and stale "interim" wording in `docs/hand-off.md`.

## Change written

`openspec/changes/agent-build-kit-track-20261101-162543/`, two `[unit-test]` groups, each a failing documentation test followed by the doc edit: (1) the layout block names every source package; (2) the work-tracker section, CLI mention and wording fix. No acceptance group: documentation only. `abk tags` passes, and the change is valid in `abk check`. `abk check` as a whole still fails because of other changes and specs that were already invalid (for example `agent-build-kit-track-20261026-125001` has no deltas); I did not touch them.

## Skipped

- Candidate 3 (`os.environ` reads into `settings.py`): the reads have differing precedence rules (`claude_account` orders process before `.env`; `detect_host` takes an injectable mapping), and the pass-through sites need a helper decision. A design decision for a human.
- Candidate 4 (git shell-outs bypassing `pipeline.shell`): the finding offers two answers (route through the shell or document an exception), and one site may be deliberate (`hooks/policy.py`). A design decision.
- Candidate 5 (`Path.home()` cache path in `usage_guard.py`): the right replacement location is not stated; a design decision.
- Candidate 6 (rerun lint-and-types and dependency-staleness): not a fix; it needs an improve rerun with Bash and network.
- No candidate needed another repo.
