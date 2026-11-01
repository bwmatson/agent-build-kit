# Improve 20261101-162543 — agent-build-kit

Tracker refresh: both pending entries (grafana-url-env-test, agui-read-events-test) are still in flight under `openspec/changes/`; left as-is. No prior improve run existed, so step 2 was skipped.

Categories that did not finish: **lint-and-types** and **dependency-staleness**. Their subagents were denied Bash (so no `pre-commit run --all-files`, `uv pip list --outdated`, `npm outdated`) and had no registry access. "Nothing found" is NOT the result for these; they need rerunning with Bash and network.

## Findings

### lint-and-types
Not completed (see above). No findings.

### dependency-staleness
Not completed (see above). Unverified observations only: exact or upper-bounded Python pins most likely to be behind are `langgraph==1.2.*`, `langgraph-checkpoint-sqlite==3.1.*`, `agent-client-protocol==0.12.1`, `githubkit<0.17`. CI action pins are held in `tests/test_ci_workflows.py`, so any bump needs a matching table edit.

### readme-drift
1. The work-tracker subsystem (`src/agent_build_kit/trackers/`: levels, manual_parent, reconciler, wanted_board, start_decision; `pipeline/tracker_file.py`; the tracker call path in `cli/pipeline.py`) has no section in `docs/architecture.md`, nothing in `docs/cli.md`, and no README mention. Only the `tracker:` config block in `docs/configuration.md` is current. `docs/hand-off.md` still calls the tracker hold "interim". Fix size: one doc section plus a small wording edit.
2. The `AGENTS.md` layout block omits `trackers/`, `forges/`, `runtimes/`, `sandboxes/`, `graph/`, `serve/` and `docs/designs/`. Fix size: about 10 lines.
3. Low confidence: worker admission/occupancy changes (`pipeline/admission.py`, `occupancy.py`, `slots.py`) may not be reflected in `docs/architecture.md`; `docs/designs/worker-design.md` may already cover it. Unconfirmed.

### convention-adherence
1. `os.environ` is read outside `settings.py`, against "no `os.environ` reads elsewhere": `config.py:1949` (CONFIG_ENV), `claude_account.py:68-69` (CLAUDE_CONFIG_DIR, ABK_CLAUDE_HOME), `pipeline/usage_guard.py:321` (CLAUDE_CODE_OAUTH_TOKEN), `init/detect.py:405-412` (WSL_DISTRO_NAME). Eight further sites pass the whole environment through (`cli/e2e_cmd.py:125`, `runtimes/base.py:200`, `pipeline/git_output.py:37`, `pipeline/wiring.py:2185` and `:3345`, `pipeline/verify.py:305` and `:377`, `sandboxes/confinement.py:36`); these may be acceptable but have no shared helper. Fix size: small for the four named reads (~30-60 lines); pass-throughs need a decision (e.g. one `settings` helper).
2. Git shell-outs bypassing `pipeline.shell`: `pipeline/wiring.py:365-373` (`_run` default runner for the commit paths), `pipeline/verify.py:344,406-424` (includes network `git pull --ff-only`), `path_discovery.py:56`, `hooks/policy.py:71` (possibly a deliberate exception for the self-contained hook), `init/detect.py:113,314`, `cli/doctor.py:178`. Most are local and token-less, so either route them through `pipeline.shell` or add an explicit exception to the convention. Fix size: small per site, about 6 sites.
3. Home-relative paths resolved with `Path.home()` outside `Installation`/`config.active()`: `pipeline/usage_guard.py:619` (`~/.cache/agent-build-kit`, the likeliest real violation), `claude_account.py:85,134`, `installation.py:51` (probably the legitimate root). Fix size: small.

Clean: no dataclasses in `src`, no `__init__.py` in `tests/`, no private-name imports in tests, no `Co-Authored-By` trailers. The ecosystem-names guard and leak scan were not run.

## Actionable candidates for the next propose run

1. [proposed — agent-build-kit-track-20261101-162543] Document the work-tracker subsystem: add a "Work tracker" section to `docs/architecture.md` (reconciler, wanted board, mapping file by level, Epic header/manual parent, claim and ownership read gating unit start), mention it in `docs/cli.md`, and drop the "interim" wording in `docs/hand-off.md`.
2. [proposed — agent-build-kit-track-20261101-162543] Complete the `AGENTS.md` layout block with `trackers/`, `forges/`, `runtimes/`, `sandboxes/`, `graph/`, `serve/` and `docs/designs/`.
3. [not-yet-actioned] Move the named-variable `os.environ` reads (`config.py`, `claude_account.py`, `pipeline/usage_guard.py`, `init/detect.py`) into `settings.py`, and decide on a single process-environment helper for the pass-through sites.
4. [not-yet-actioned] Resolve the git shell-out convention gap: route the direct `subprocess` git calls (notably `pipeline/wiring.py` `_run`, `pipeline/verify.py` including `git pull`) through `pipeline.shell`, or document an exception for local read-only calls.
5. [not-yet-actioned] Resolve the `usage_guard.py:619` `Path.home()` cache path (and `claude_account.py` paths) through `Installation`/settings.
6. [not-yet-actioned] Rerun lint-and-types and dependency-staleness with Bash and network access; this run produced no result for either.
