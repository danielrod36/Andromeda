"""``andromeda-web`` console script entry point (U4).

Runs the FastAPI app via uvicorn on 127.0.0.1 (single-player localhost only).
"""

from __future__ import annotations

import sys


def main() -> None:
    """Run the Andromeda web server."""
    import argparse

    import uvicorn

    from src.web.app import create_app

    parser = argparse.ArgumentParser(description="Andromeda web server")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default 8000)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open a browser (auto-open is not implemented; flag is accepted for scripting)",
    )
    args = parser.parse_args()

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    sys.exit(main() or 0)
