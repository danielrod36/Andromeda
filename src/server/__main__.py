"""Sidecar entry point: ``python -m src.server [--port N]`` (M0.6, spec §3).

Binds 127.0.0.1 (random port by default), prints exactly one stdout line —
``LISTENING <port>`` — for the spawning client, then serves until the
client kills the process or the idle watchdog fires (300 s without a
request → self-exit, so orphans never linger).
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import time
from pathlib import Path

import uvicorn

from src.server.app import create_app

#: Self-exit after this many seconds without a request (spec §3).
DEFAULT_IDLE_TIMEOUT = 300


async def _watchdog(server: uvicorn.Server, state, idle_timeout: int) -> None:
    """Flip ``should_exit`` when the app has been idle too long."""
    while True:
        await asyncio.sleep(15)
        if time.monotonic() - state.last_request_at > idle_timeout:
            server.should_exit = True
            return


async def _serve(server: uvicorn.Server, sock: socket.socket, state, idle_timeout: int) -> None:
    watcher = asyncio.create_task(_watchdog(server, state, idle_timeout))
    try:
        await server.serve(sockets=[sock])
    finally:
        watcher.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(prog="andromeda-server")
    parser.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    parser.add_argument("--saves-dir", type=Path, default=Path("saves"))
    parser.add_argument("--settings-dir", type=Path, default=Path("settings"))
    parser.add_argument("--idle-timeout", type=int, default=DEFAULT_IDLE_TIMEOUT)
    args = parser.parse_args()

    app = create_app(saves_dir=args.saves_dir, settings_dir=args.settings_dir)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", args.port))
    sock.listen()
    port = sock.getsockname()[1]
    # The ONLY stdout line the client reads (spec §3 handshake).
    print(f"LISTENING {port}", flush=True)

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    asyncio.run(_serve(server, sock, app.state, args.idle_timeout))


if __name__ == "__main__":
    main()
