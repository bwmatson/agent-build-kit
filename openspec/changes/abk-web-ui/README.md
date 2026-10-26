# abk-web-ui

`abk serve`: a local web UI for the pipeline. Per-unit status, cause, logs and usage; a page of every
metric the pipeline gathers (from Prometheus/Tempo when reachable, otherwise from local files); unit
actions; and chat with the agents behind the project's units, in the same Claude Code and ACP sessions
an editor drives. Editing from chat is `ui-chat-editing`; review and a diff view are `ui-review`; a
local forge is `local-forge`.
