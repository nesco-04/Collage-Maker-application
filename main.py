"""Application entry point.

Run with ``python main.py`` for development, or launch the PyInstaller-
built executable for a standalone Windows deployment. Both paths open the
same PySide6 desktop GUI -- no console window and no server process is
involved.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from app.main_window import MainWindow


def _configure_logging() -> None:
    log_dir = Path.home() / ".collage_maker"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "collage_maker.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> int:
    """Start the Collage Maker desktop application. Returns the process
    exit code."""

    _configure_logging()
    logger = logging.getLogger(__name__)

    app = QApplication(sys.argv)
    app.setApplicationName("Collage Maker")
    app.setOrganizationName("CollageMaker")

    try:
        window = MainWindow()
        window.show()
        return app.exec()
    except Exception:  # noqa: BLE001 - top-level guard so we never crash silently
        logger.exception("Unhandled exception in application")
        QMessageBox.critical(
            None,
            "Collage Maker - Unexpected Error",
            "An unexpected error occurred and the application must close. "
            "Details have been written to the log file.",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
