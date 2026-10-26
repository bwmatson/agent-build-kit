# Proposal

## Why

The live policy check sends the agent one prompt listing every forbidden command and watches which it refuses. Four things
are wrong with it as the product's check.

- It spends model tokens and asks "spends tokens; run it? [y/N]" for a question a configuration answers. The deny list the
  recommended policy fills is a list of command globs in a file the kit already reads; whether a command is refused by it is
  a question for the kit's own matcher, which already exists with its dialect.
- It has no overall deadline and prints nothing until the end. In two runs a person reported, with `--yes`, it hung 25 and
  15 minutes without output and left the agent's process running.
- It fails a configuration that applies the recommendation completely: the six classes the recommendation leaves to the
  person by design are counted like any other, so `abk doctor` fails on a perfect configuration and teaches a person to
  ignore it.
- Its replacement must not be a new way to run the agent. An earlier design of this change asked the agent's own private
  matcher through the agent's interpreter; that runs another program's internal code from a diagnostic, and an update that
  renames the function breaks the check. The framework must be self-contained.

## What changes

- The check becomes static. For a known agent with an applier, doctor, `abk init --policy-only` and the init policy step read
  the deny list from the agent's real configuration (a missing file is a failure) and judge every command of the probe list
  with the kit's own `matches` and dialect. No external code runs: the agent is never started, never imported from, and no
  program of another product is run.
- Each result names the pattern that refused it. Classes the recommendation does not cover are reported "not covered by
  design" and never fail. The report is labelled "what the configuration says, in abk's dialect; not observed from the
  agent".
- An agent with no table entry, or an entry with no applier, is "cannot check: abk has no policy for this agent": non-zero in
  `--policy-only`, a warning in doctor, never a pass.
- `abk policy check` runs the check on demand. The live probe, its deadline and progress, `--live`, the token question and
  the 15-minute cache are removed; the check is instant, so nothing is kept.
- One e2e-test acceptance test drives the real agent over the probe commands, with a client that runs nothing, and asserts the
  agent's behaviour agrees with the static verdict for each command, so the kit's dialect is shown to match reality. It has
  its own deadline and progress and cleans up its process group and temporary directories. The old probe's logic moves into
  that test's harness.

## Impact

Capability `agent-tool-policy`: one requirement on the check reading the configuration, one on running no code of the
agent, one on the classes left to the person, one on a check that cannot be made, one on doctor and init, one on `abk policy
check`, one on the acceptance test, and one on the documents; and three requirements modified (the spelling check, setup,
and `abk policy apply`) because they described an agent call, a cache and a live check. Code under `runtimes/`
(`policy_check.py`, `base.py`, `acp.py`, `known_agents.py` unchanged in shape), `cli/doctor.py`, `cli/init.py`,
`cli/policy_cmd.py`; tests under `tests/runtimes/`, `tests/cli/` and `tests/integration/`; the docs and two skills. The
agent's own repository may keep a test of its own if it needs one; nothing here requires or removes it.
