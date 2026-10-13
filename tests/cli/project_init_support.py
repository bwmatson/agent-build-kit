"""A commented abk.yaml and a driver for `abk project init`."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_build_kit.cli import main

COMMENTED = """# The workspace: who builds what.
repos:
  # The application.
  app:
    path: {app}
    slug: example/app
    projects:
      # The service that exists today.
      - path: svc-a
        profile: python-uv

  # A repo with no projects yet.
  platform:
    path: {platform}
    slug: example/platform

# Limits keep a tick small.
limits:
  max_concurrent_stacks: 2  # kept low
"""


def write_commented(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    app, platform = root / "app", root / "platform"
    app.mkdir()
    platform.mkdir()
    path = root / "abk.yaml"
    path.write_text(COMMENTED.format(app=app, platform=platform))
    return path


def project_init(config: Path, *argv: str) -> int:
    return main(["--config", str(config), "project", "init", *argv])


def projects_of(config: Path, repo: str) -> list[dict]:
    return yaml.safe_load(config.read_text())["repos"][repo].get("projects", [])
