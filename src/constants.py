from __future__ import annotations

from enum import IntEnum
from pathlib import Path


APP_ID = "io.github.spyaj.monitorcontrol"
APP_NAME = "Monitor Control"
APP_VERSION = "0.1.0"

SLIDER_DEBOUNCE_MS = 50

LOG_DIR = Path.home() / ".local" / "share" / "monitor-control" / "logs"
LOG_FILE = LOG_DIR / "monitor-control.log"


class VcpCode(IntEnum):
    BRIGHTNESS = 0x10
    CONTRAST = 0x12
    COLOR_PRESET = 0x14
    RED_GAIN = 0x16
    GREEN_GAIN = 0x18
    BLUE_GAIN = 0x1A
    SHARPNESS = 0x87
    VOLUME = 0x62
    POWER_MODE = 0xD6


COLOR_PRESETS: dict[str, int] = {
    "6500K": 0x05,
    "9300K": 0x08,
    "sRGB": 0x01,
    "User": 0x0B,
}

POWER_MODES: dict[str, int] = {
    "On": 0x01,
}
