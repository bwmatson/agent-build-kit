# agent-runtime-seam

Put one seam behind every "run an agent and get a result" call in
agent-build-kit: an `AgentRuntime` Protocol with a registry, the current Claude
Code behaviour moved behind it unchanged, and `runtime`/`runtimes` in
`abk.yaml` so a workspace can name a different one later.

Nothing about how the pipeline behaves changes here. Claude Code stays the
runtime, the argv it builds stay identical, and the policy hook and usage guard
keep working exactly as now — they simply live in one adapter instead of being
spread across seven call sites. The design is `docs/agent-runtimes.md` in
agent-build-kit; the second adapter is the next change.
