"""`abk telemetry push-dashboard`: push the framework's Grafana dashboard.

The dashboard is package data (`telemetry/dashboards/pipeline.json`) querying
the metrics `telemetry.py` emits. Pushing is idempotent: the folder is found by
title or created, and the dashboard, which has a fixed uid, is overwritten.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from importlib import resources
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.settings import settings


def _call(method: str, path: str, body: object | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if settings.grafana_token:
        headers["Authorization"] = f"Bearer {settings.grafana_token}"
    request = urllib.request.Request(
        settings.grafana_url.rstrip("/") + path,
        data=data,
        method=method,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


def _folder_uid(title: str) -> str:
    """The uid of the folder titled `title`, created when there is none."""
    for folder in _call("GET", "/api/folders"):
        if folder["title"] == title:
            return str(folder["uid"])
    uid = re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-") or "abk"
    return str(_call("POST", "/api/folders", {"uid": uid, "title": title})["uid"])


def cmd_push_dashboard(args: argparse.Namespace, inst: Installation | None) -> int:
    if not settings.grafana_url:
        print("abk telemetry push-dashboard: set ABK_GRAFANA_URL")
        return 2
    path = resources.files("agent_build_kit") / "telemetry" / "dashboards" / "pipeline.json"
    dashboard = json.loads(path.read_text())
    try:
        folder = _folder_uid(settings.grafana_folder)
        _call(
            "POST",
            "/api/dashboards/db",
            {"dashboard": dashboard, "folderUid": folder, "overwrite": True},
        )
    except urllib.error.HTTPError as error:
        if error.code in (401, 403) and not settings.grafana_token:
            print(
                f"abk telemetry push-dashboard: {settings.grafana_url} refused the anonymous "
                f"push (HTTP {error.code}); set ABK_GRAFANA_TOKEN to a service-account token"
            )
        else:
            print(f"abk telemetry push-dashboard: {settings.grafana_url}: {error}")
        return 1
    except (urllib.error.URLError, OSError) as error:
        print(f"abk telemetry push-dashboard: {settings.grafana_url}: {error}")
        return 1
    print(f"pushed '{dashboard['title']}' to {settings.grafana_url} ({settings.grafana_folder})")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("telemetry", help="telemetry helpers")
    commands = parser.add_subparsers(dest="telemetry_command", required=True)
    push = commands.add_parser(
        "push-dashboard",
        help="push the pipeline's Grafana dashboard (ABK_GRAFANA_URL, _TOKEN optional, _FOLDER)",
    )
    push.set_defaults(func=cmd_push_dashboard, needs_installation="optional")
