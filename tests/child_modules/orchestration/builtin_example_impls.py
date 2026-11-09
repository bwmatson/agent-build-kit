"""A built-in module: registers a local implementation when the registry imports it."""

from agent_build_kit import orchestration

orchestration.register("store", "local", lambda installation: "built-in")
