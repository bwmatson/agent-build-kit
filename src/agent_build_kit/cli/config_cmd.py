"""`abk config`: which abk.yaml is in force, and what it says once every
default is filled in."""

from __future__ import annotations

import argparse
import sys

import yaml

from agent_build_kit.config import (
    deprecation_notice,
    deprecations,
    locate,
    overlay_path,
    read_overlay,
)
from agent_build_kit.installation import Installation


def cmd_config(args: argparse.Namespace, inst: Installation) -> int:
    if args.path:
        path = locate(args.config)
        print(path)
        if overlay_path(path).is_file():
            print(overlay_path(path))
        return 0
    path = locate(args.config)
    for key in deprecations(path):
        print(deprecation_notice(key), file=sys.stderr)
    local = read_overlay(path)
    if local:
        print(f"{overlay_path(path)} set: {', '.join(local)}", file=sys.stderr)
    data = inst.config.model_dump(by_alias=True, mode="json")
    print(yaml.safe_dump(data, sort_keys=False, default_flow_style=False), end="")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("config", help="show the effective workspace config, or its path")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--show", action="store_true", help="the effective config with defaults filled (default)"
    )
    mode.add_argument(
        "--path",
        action="store_true",
        help="the abk.yaml in force, and the overlay when there is one",
    )
    parser.set_defaults(func=cmd_config)
