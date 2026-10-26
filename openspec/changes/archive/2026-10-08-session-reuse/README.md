# session-reuse

Every agent node records the session it ran in, under a role: `build` for the nodes that
write the code (tests, implement, fix_checks, rework, adapt) and `review` for the judge. A
role whose reuse is on continues its previous session, with a short prompt carrying only
what is new, so a fix round starts from an agent that already knows the change. Review
stays its own session. Reuse is a per-role switch in `abk.yaml`, on for `build`; turning
another role on is one line. Both runtimes support it: Claude Code with `--resume`, ACP
with `session/resume` guarded by `session/list`.
