"""Entry point for ``python -m src.tui`` — launches the Andromeda TUI."""

from src.tui.app import CepheusApp


def main() -> None:
    """Run the Andromeda TUI application."""
    app = CepheusApp()
    app.run()


if __name__ == "__main__":
    main()
