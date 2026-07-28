"""Entry point for ``python -m src.tui`` — launches the Cepheus Adventure TUI."""
from src.tui.app import CepheusApp


def main() -> None:
    """Run the Cepheus Adventure TUI application."""
    app = CepheusApp()
    app.run()


if __name__ == "__main__":
    main()
