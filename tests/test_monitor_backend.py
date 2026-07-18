from __future__ import annotations

import unittest

from src.constants import VcpCode
from src.monitor import DdcutilBackend, ResultCallback


class DdcutilBackendParsingTest(unittest.TestCase):
    def test_parses_continuous_terse_value(self) -> None:
        value = DdcutilBackend._parse_vcp_value("VCP 10 C 1 100", "0x10")

        self.assertIsNotNone(value)
        assert value is not None
        self.assertEqual(value.current, 1)
        self.assertEqual(value.maximum, 100)

    def test_parses_cnc_volume_high_low_bytes(self) -> None:
        value = DdcutilBackend._parse_vcp_value("VCP 62 CNC x00 x64 x00 x2b", "0x62")

        self.assertIsNotNone(value)
        assert value is not None
        self.assertEqual(value.current, 43)
        self.assertEqual(value.maximum, 100)

    def test_parses_verbose_volume_level(self) -> None:
        output = "VCP code 0x62 (Audio speaker volume): Volume level: 43 (00x2b)"
        value = DdcutilBackend._parse_vcp_value(output, "0x62")

        self.assertIsNotNone(value)
        assert value is not None
        self.assertEqual(value.current, 43)
        self.assertEqual(value.maximum, 100)

    def test_ignores_verbose_line_as_terse_value(self) -> None:
        output = "VCP code 0x62 (Audio speaker volume): Volume level: 43 (00x2b)"
        value = DdcutilBackend._parse_terse_vcp_value(output, "0x62")

        self.assertIsNone(value)

    def test_parses_sharpness_range_from_terse_value(self) -> None:
        value = DdcutilBackend._parse_vcp_value("VCP 87 C 4 4", "0x87")

        self.assertIsNotNone(value)
        assert value is not None
        self.assertEqual(value.current, 4)
        self.assertEqual(value.maximum, 4)


class DdcutilBackendSetVcpTest(unittest.TestCase):
    def test_set_vcp_keeps_raw_vcp_values_above_100(self) -> None:
        backend = CapturingDdcutilBackend()

        backend.set_vcp("1", VcpCode.SHARPNESS, 500, lambda _data, _error: None)

        self.assertEqual(backend.last_args, ["--display", "1", "setvcp", "0x87", "500"])

    def test_set_vcp_clamps_to_unsigned_16_bit_range(self) -> None:
        backend = CapturingDdcutilBackend()

        backend.set_vcp("1", VcpCode.SHARPNESS, 100_000, lambda _data, _error: None)

        self.assertEqual(backend.last_args, ["--display", "1", "setvcp", "0x87", "65535"])


class CapturingDdcutilBackend(DdcutilBackend):
    def __init__(self) -> None:
        super().__init__(binary="ddcutil")
        self.last_args: list[str] | None = None

    def _run(self, args: list[str], callback: ResultCallback) -> None:
        self.last_args = args
        callback("", None)


if __name__ == "__main__":
    unittest.main()
