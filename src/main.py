from __future__ import annotations

import argparse
import logging

import gi

from .constants import APP_ID, APP_NAME, APP_VERSION
from .utils import setup_logging
from .window import MonitorControlWindow

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw  # noqa: E402


class MonitorControlApplication(Adw.Application):
    def __init__(self, debug: bool = False) -> None:
        super().__init__(application_id=APP_ID)
        self._debug = debug
        self._logger = logging.getLogger(__name__)

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = MonitorControlWindow(self)
        window.present()
        self._logger.debug("Application activated")

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._logger.info("%s %s starting", APP_NAME, APP_VERSION)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="monitor-control", description=APP_NAME)
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(debug=args.debug)
    app = MonitorControlApplication(debug=args.debug)
    return app.run(None)


if __name__ == "__main__":
    raise SystemExit(main())

