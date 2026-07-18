from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Callable

import gi

from .constants import VcpCode
from .utils import clamp

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402


ResultCallback = Callable[[object | None, Exception | None], None]
CommandRequest = tuple[list[str], ResultCallback]


class MonitorError(Exception):
    pass


class MonitorPermissionError(MonitorError):
    pass


class MonitorNotFoundError(MonitorError):
    pass


@dataclass(slots=True)
class MonitorInfo:
    display_id: str
    model: str = "Unknown"
    manufacturer: str = "Unknown"
    connection: str = "Unknown"
    firmware: str = "Unknown"
    vcp_version: str = "Unknown"
    refresh_rate: str = "Unknown"
    resolution: str = "Unknown"


@dataclass(slots=True)
class VcpValue:
    current: int
    maximum: int


class MonitorBackend(ABC):
    @abstractmethod
    def detect(self, callback: ResultCallback) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_vcp(self, display_id: str, code: VcpCode, callback: ResultCallback) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_vcp(
        self,
        display_id: str,
        code: VcpCode,
        value: int,
        callback: ResultCallback,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_info(self, display_id: str, callback: ResultCallback) -> None:
        raise NotImplementedError


class DdcutilBackend(MonitorBackend):
    def __init__(self, binary: str = "ddcutil") -> None:
        self._binary = binary
        self._logger = logging.getLogger(__name__)
        self._command_queue: deque[CommandRequest] = deque()
        self._command_running = False

    def _map_error(self, message: str) -> Exception:
        lower = message.lower()
        if "permission denied" in lower:
            return MonitorPermissionError(message)
        if "no displays found" in lower or "not found" in lower:
            return MonitorNotFoundError(message)
        return MonitorError(message)

    def _run(self, args: list[str], callback: ResultCallback) -> None:
        self._command_queue.append((args, callback))
        if not self._command_running:
            self._run_next()

    def _run_next(self) -> bool:
        if self._command_running or not self._command_queue:
            return GLib.SOURCE_REMOVE

        args, callback = self._command_queue.popleft()
        command = [self._binary, *args]
        self._logger.debug("Running command: %s", " ".join(command))
        self._command_running = True
        try:
            proc = Gio.Subprocess.new(
                command,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
            )
        except GLib.Error as error:
            self._complete_command(callback, None, MonitorError(str(error)))
            return GLib.SOURCE_REMOVE

        def on_done(subprocess: Gio.Subprocess, result: Gio.AsyncResult) -> None:
            try:
                _, stdout, stderr = subprocess.communicate_utf8_finish(result)
            except GLib.Error as error:
                self._complete_command(callback, None, MonitorError(str(error)))
                return

            if subprocess.get_exit_status() != 0:
                self._complete_command(callback, None, self._map_error(stderr.strip() or "ddcutil command failed"))
                return

            self._complete_command(callback, stdout, None)

        proc.communicate_utf8_async(None, None, on_done)
        return GLib.SOURCE_REMOVE

    def _complete_command(
        self,
        callback: ResultCallback,
        data: object | None,
        error: Exception | None,
    ) -> None:
        try:
            callback(data, error)
        finally:
            self._command_running = False
            GLib.idle_add(self._run_next)

    def detect(self, callback: ResultCallback) -> None:
        def on_detect(output: object | None, error: Exception | None) -> None:
            if error:
                callback(None, error)
                return
            text = str(output or "")
            displays = re.findall(r"Display\s+(\d+)", text)
            callback(displays, None)

        self._run(["detect", "--brief"], on_detect)

    def get_vcp(self, display_id: str, code: VcpCode, callback: ResultCallback) -> None:
        hex_code = f"0x{int(code):02x}"
        terse_args = ["--display", display_id, "--terse", "getvcp", hex_code]
        verbose_args = ["--display", display_id, "getvcp", hex_code]

        def on_verbose(output: object | None, error: Exception | None) -> None:
            if error:
                callback(None, error)
                return

            value = self._parse_vcp_value(str(output), hex_code)
            if value is None:
                callback(None, MonitorError(f"Unable to parse VCP value for {hex_code}"))
                return

            callback(value, None)

        def on_terse(output: object | None, error: Exception | None) -> None:
            if error:
                callback(None, error)
                return

            value = self._parse_vcp_value(str(output), hex_code)
            if value is not None:
                callback(value, None)
                return

            self._run(verbose_args, on_verbose)

        self._run(terse_args, on_terse)

    def set_vcp(
        self,
        display_id: str,
        code: VcpCode,
        value: int,
        callback: ResultCallback,
    ) -> None:
        hex_code = f"0x{int(code):02x}"
        args = ["--display", display_id, "setvcp", hex_code, str(clamp(value, maximum=0xFFFF))]
        self._run(args, callback)

    def get_info(self, display_id: str, callback: ResultCallback) -> None:
        def on_detect(output: object | None, error: Exception | None) -> None:
            if error:
                callback(None, error)
                return

            block = self._extract_display_block(str(output), display_id)
            info = MonitorInfo(
                display_id=display_id,
                model=self._extract_field(block, "Model", default="Unknown"),
                manufacturer=self._extract_field(block, "Mfg id", default="Unknown"),
                connection=self._extract_field(block, "I2C bus", default="Unknown"),
                vcp_version=self._extract_field(block, "VCP version", default="Unknown"),
            )
            callback(info, None)

        self._run(["detect"], on_detect)

    @staticmethod
    def _extract_display_block(text: str, display_id: str) -> str:
        pattern = re.compile(rf"Display\s+{re.escape(display_id)}\b(.*?)(?=\nDisplay\s+\d+\b|\Z)", re.S)
        match = pattern.search(text)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_field(text: str, field_name: str, default: str = "Unknown") -> str:
        pattern = re.compile(rf"{re.escape(field_name)}:\s*(.+)")
        match = pattern.search(text)
        return match.group(1).strip() if match else default

    @staticmethod
    def _parse_vcp_value(output: str, hex_code: str) -> VcpValue | None:
        terse_line = next((line.strip() for line in output.splitlines() if line.strip().startswith("VCP")), None)
        if terse_line:
            terse_value = DdcutilBackend._parse_terse_vcp_value(terse_line, hex_code)
            if terse_value is not None:
                return terse_value

        verbose_match = re.search(
            r"current value\s*=\s*([x0-9a-fA-F]+),\s*max value\s*=\s*([x0-9a-fA-F]+)",
            output,
            re.I,
        )
        if verbose_match:
            maybe_current = DdcutilBackend._token_to_int(verbose_match.group(1))
            maybe_maximum = DdcutilBackend._token_to_int(verbose_match.group(2))
            if maybe_current is not None and maybe_maximum is not None:
                return VcpValue(current=maybe_current, maximum=maybe_maximum)

        volume_match = re.search(r"Volume level:\s*([x0-9a-fA-F]+)(?:\s*\(([x0-9a-fA-F]+)\))?", output, re.I)
        if volume_match:
            maybe_current = DdcutilBackend._token_to_int(volume_match.group(1))
            if maybe_current is None and volume_match.group(2):
                maybe_current = DdcutilBackend._token_to_int(volume_match.group(2))
            if maybe_current is not None:
                return VcpValue(current=maybe_current, maximum=100)

        table_match = re.search(
            rf"VCP code\s*{re.escape(hex_code)}.*?sl\s*=\s*([x0-9a-fA-F]+).*?sh\s*=\s*([x0-9a-fA-F]+)",
            output,
            re.I,
        )
        if table_match:
            maybe_current = DdcutilBackend._token_to_int(table_match.group(1))
            maybe_maximum = DdcutilBackend._token_to_int(table_match.group(2))
            if maybe_current is not None and maybe_maximum is not None:
                return VcpValue(current=maybe_current, maximum=maybe_maximum)

        return None

    @staticmethod
    def _parse_terse_vcp_value(line: str, hex_code: str) -> VcpValue | None:
        tokens = line.split()
        if len(tokens) < 5 or tokens[0] != "VCP":
            return None

        parsed_code = DdcutilBackend._vcp_code_to_int(tokens[1])
        expected_code = DdcutilBackend._vcp_code_to_int(hex_code)
        if parsed_code is None or expected_code is None or parsed_code != expected_code:
            return None

        value_kind = tokens[2].upper()
        numbers = [DdcutilBackend._token_to_int(token) for token in tokens[3:]]
        if value_kind == "C" and len(numbers) >= 2:
            maybe_current, maybe_maximum = numbers[0], numbers[1]
            if maybe_current is not None and maybe_maximum is not None:
                return VcpValue(current=maybe_current, maximum=maybe_maximum)

        if value_kind in {"CNC", "NC"} and len(numbers) >= 4:
            maybe_maximum = DdcutilBackend._combine_high_low(numbers[0], numbers[1])
            maybe_current = DdcutilBackend._combine_high_low(numbers[2], numbers[3])
            if maybe_current is not None and maybe_maximum is not None:
                return VcpValue(current=maybe_current, maximum=maybe_maximum)

        return None

    @staticmethod
    def _combine_high_low(high: int | None, low: int | None) -> int | None:
        if high is None or low is None:
            return None
        return (high << 8) | low

    @staticmethod
    def _vcp_code_to_int(token: str) -> int | None:
        cleaned = token.strip().strip(",;()[]").lower()
        try:
            if cleaned.startswith("0x"):
                return int(cleaned, 16)
            return int(cleaned, 16)
        except ValueError:
            return None

    @staticmethod
    def _token_to_int(token: str) -> int | None:
        cleaned = token.strip().strip(",;()[]").lower()
        if cleaned == "null":
            return None
        try:
            if cleaned.startswith("0x"):
                return int(cleaned, 16)
            if re.fullmatch(r"0+x[0-9a-f]+", cleaned):
                return int(cleaned.split("x", 1)[1], 16)
            if cleaned.startswith("x"):
                return int(cleaned[1:], 16)
            if re.fullmatch(r"[0-9a-f]+", cleaned) and any(ch.isalpha() for ch in cleaned):
                return int(cleaned, 16)
            return int(cleaned, 10)
        except ValueError:
            return None


class Monitor:
    def __init__(self, backend: MonitorBackend) -> None:
        self._backend = backend
        self._logger = logging.getLogger(__name__)
        self._display_id: str | None = None
        self._detected_displays: list[str] = []
        self._info_cache: dict[str, MonitorInfo] = {}

    @property
    def display_id(self) -> str | None:
        return self._display_id

    @property
    def displays(self) -> tuple[str, ...]:
        return tuple(self._detected_displays)

    def detect(self, callback: ResultCallback) -> None:
        def on_detect(data: object | None, error: Exception | None) -> None:
            if error:
                callback(None, error)
                return

            displays = [str(display) for display in list(data or [])]
            if not displays:
                callback(None, MonitorNotFoundError("No DDC/CI monitor found"))
                return

            self._detected_displays = displays
            self._display_id = displays[0]
            self._logger.info("Active display set to %s", self._display_id)
            callback(self._display_id, None)

        self._backend.detect(on_detect)

    def detect_all(self, callback: ResultCallback) -> None:
        def on_detect(data: object | None, error: Exception | None) -> None:
            if error:
                callback(None, error)
                return

            displays = [str(display) for display in list(data or [])]
            if not displays:
                callback(None, MonitorNotFoundError("No DDC/CI monitor found"))
                return

            self._detected_displays = displays
            if self._display_id not in self._detected_displays:
                self._display_id = self._detected_displays[0]
            callback(self._detected_displays, None)

        self._backend.detect(on_detect)

    def set_display(self, display_id: str) -> None:
        if self._detected_displays and display_id not in self._detected_displays:
            raise MonitorNotFoundError(f"Display {display_id} is not available")
        self._display_id = display_id

    def get_info(self, callback: ResultCallback) -> None:
        if not self._display_id:
            callback(None, MonitorNotFoundError("No active monitor selected"))
            return

        if self._display_id in self._info_cache:
            callback(self._info_cache[self._display_id], None)
            return

        def on_info(data: object | None, error: Exception | None) -> None:
            if error:
                callback(None, error)
                return
            info = data if isinstance(data, MonitorInfo) else MonitorInfo(display_id=self._display_id or "1")
            self._info_cache[self._display_id or "1"] = info
            callback(info, None)

        self._backend.get_info(self._display_id, on_info)

    def _get_vcp(self, code: VcpCode, callback: ResultCallback) -> None:
        if not self._display_id:
            callback(None, MonitorNotFoundError("No active monitor selected"))
            return
        self._backend.get_vcp(self._display_id, code, callback)

    def _set_vcp(self, code: VcpCode, value: int, callback: ResultCallback) -> None:
        if not self._display_id:
            callback(None, MonitorNotFoundError("No active monitor selected"))
            return
        self._backend.set_vcp(self._display_id, code, value, callback)

    def get_brightness(self, callback: ResultCallback) -> None:
        self._get_vcp(VcpCode.BRIGHTNESS, callback)

    def set_brightness(self, value: int, callback: ResultCallback) -> None:
        self._set_vcp(VcpCode.BRIGHTNESS, value, callback)

    def get_contrast(self, callback: ResultCallback) -> None:
        self._get_vcp(VcpCode.CONTRAST, callback)

    def set_contrast(self, value: int, callback: ResultCallback) -> None:
        self._set_vcp(VcpCode.CONTRAST, value, callback)

    def get_volume(self, callback: ResultCallback) -> None:
        self._get_vcp(VcpCode.VOLUME, callback)

    def set_volume(self, value: int, callback: ResultCallback) -> None:
        self._set_vcp(VcpCode.VOLUME, value, callback)

    def get_red_gain(self, callback: ResultCallback) -> None:
        self._get_vcp(VcpCode.RED_GAIN, callback)

    def set_red_gain(self, value: int, callback: ResultCallback) -> None:
        self._set_vcp(VcpCode.RED_GAIN, value, callback)

    def get_green_gain(self, callback: ResultCallback) -> None:
        self._get_vcp(VcpCode.GREEN_GAIN, callback)

    def set_green_gain(self, value: int, callback: ResultCallback) -> None:
        self._set_vcp(VcpCode.GREEN_GAIN, value, callback)

    def get_blue_gain(self, callback: ResultCallback) -> None:
        self._get_vcp(VcpCode.BLUE_GAIN, callback)

    def set_blue_gain(self, value: int, callback: ResultCallback) -> None:
        self._set_vcp(VcpCode.BLUE_GAIN, value, callback)

    def get_sharpness(self, callback: ResultCallback) -> None:
        self._get_vcp(VcpCode.SHARPNESS, callback)

    def set_sharpness(self, value: int, callback: ResultCallback) -> None:
        self._set_vcp(VcpCode.SHARPNESS, value, callback)

    def set_color_preset(self, value: int, callback: ResultCallback) -> None:
        self._set_vcp(VcpCode.COLOR_PRESET, value, callback)

    def set_power_mode(self, value: int, callback: ResultCallback) -> None:
        self._set_vcp(VcpCode.POWER_MODE, value, callback)
