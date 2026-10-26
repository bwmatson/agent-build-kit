# init-asks-which-runtime

`abk init` stops assuming the agent runtime. It probes what this machine can run, shows the candidates (usable ones
first, each unusable one with the reason), asks which to use, asks that runtime's own setup questions, and records the
answers in `abk.yaml` — before anything that depends on a runtime runs. Choosing never makes a model call.

It also gives `abk init --policy-only` (and `--policy-fix`): the guided policy step alone, to patch an existing
installation's agent policy and see per class and spelling what is now refused. Priority 1.

Specs only so far: nothing is built, ticked or started. The design is `design.md`; the research behind the table of
known agents is `docs/research/acp-agent-commands.md`.
