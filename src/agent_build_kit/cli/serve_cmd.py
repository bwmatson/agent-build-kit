"""`abk serve`: a loopback web server over the pipeline's stores."""

from __future__ import annotations

import argparse
import threading

from agent_build_kit.installation import Installation
from agent_build_kit.serve.server import start_server

DEFAULT_PORT = 8765


def cmd_serve(args: argparse.Namespace, inst: Installation) -> int:
    with start_server(inst, port=args.port) as server:
        print(f"abk serve: listening on {server.url} (Ctrl-C to stop)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("serve", help="serve the pipeline's state on the loopback address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.set_defaults(func=cmd_serve)
