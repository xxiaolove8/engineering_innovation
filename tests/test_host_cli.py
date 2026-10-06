import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from host import range_check, serial_check
from host.legacy import ble_check
from host.protocol import SimLink


class LegacySimLink(SimLink):
    """Keep legacy CLI tests independent of optional BLE libraries and hardware."""

    def __init__(self, target, **kwargs):
        super().__init__()
        self.connection_details = {"name": target}

    def receive_diagnostics(self):
        return {"byte_count": 0}


class CloseFailureSimLink(SimLink):
    def close(self):
        raise OSError("close failed")


class FakeClock:
    """Advance logger time only when its polling loop sleeps."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class HostCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        printer = patch("builtins.print")
        printer.start()
        self.addCleanup(printer.stop)
        self.clock = FakeClock()
        clock_patch = patch.object(range_check, "time", self.clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)

    def test_serial_check_writes_sensor_report(self):
        output = self.root / "serial.json"
        self.assertEqual(serial_check.main(["--simulate", "--output", str(output)]), 0)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(report["ok"])
        self.assertTrue(report["simulated"])
        self.assertEqual(report["line"]["settle_us"], 500)
        self.assertEqual(report["line"]["raw_bits"], 231)
        self.assertEqual(report["exchanges"][0], {"direction": "TX", "line": "PING"})

    def test_serial_check_preserves_connection_error_in_report(self):
        output = self.root / "failure.json"
        with patch.object(serial_check, "SerialLink", side_effect=OSError("COM3 unavailable")):
            result = serial_check.main(["--port", "COM3", "--output", str(output)])
        self.assertEqual(result, 1)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(report["ok"])
        self.assertEqual(report["error"], "COM3 unavailable")

    def test_serial_ping_only_does_not_read_sensors(self):
        output = self.root / "ping.json"
        with patch.object(SimLink, "request", autospec=True, return_value="PONG 2") as request:
            result = serial_check.main(["--simulate", "--ping-only", "--output", str(output)])
        self.assertEqual(result, 0)
        self.assertEqual([call.args[1] for call in request.call_args_list], ["PING"])
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(report["handshake_ok"])
        self.assertNotIn("hardware", report)

    def test_serial_check_saves_raw_bytes_when_handshake_fails(self):
        output = self.root / "raw_failure.json"
        class FailedLink:
            def request(self, command):
                raise TimeoutError("non-ASCII reply")
            def close(self):
                pass
            def receive_diagnostics(self):
                return {"port": "COM5", "last_tx_hex": "50 49 4E 47 0A",
                        "last_rx_hex": "BF BF FF", "last_rx_bytes": 3}
        with patch.object(serial_check, "SerialLink", return_value=FailedLink()):
            result = serial_check.main(["--port", "COM5", "--ping-only", "--output", str(output)])
        self.assertEqual(result, 1)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(report["ok"])
        self.assertEqual(report["serial"]["last_rx_hex"], "BF BF FF")
        self.assertEqual(report["serial"]["last_rx_bytes"], 3)

    def test_serial_check_close_error_still_saves_report(self):
        output = self.root / "close.json"
        with patch.object(serial_check, "SimLink", CloseFailureSimLink):
            self.assertEqual(serial_check.main(["--simulate", "--output", str(output)]), 1)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["close_error"], "close failed")

    def test_serial_check_preserves_existing_output(self):
        output = self.root / "serial.json"
        output.write_text("previous measurement", encoding="utf-8")
        self.assertEqual(serial_check.main(["--simulate", "--output", str(output)]), 1)
        self.assertEqual(output.read_text(encoding="utf-8"), "previous measurement")

    def test_range_check_logs_all_three_probes(self):
        output = self.root / "range.csv"
        self.assertEqual(range_check.main(["--simulate", "--duration", ".01", "--output", str(output)]), 0)
        with output.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([row["side"] for row in rows], ["L", "C", "R"])
        self.assertTrue(all(row["distance_mm"] == "500" for row in rows))
        self.assertEqual(self.clock.sleeps, [.01])

    def test_range_check_keeps_legacy_ble_transport_available(self):
        output = self.root / "legacy-range.csv"
        with patch("host.legacy.ble_link.BleLink", LegacySimLink):
            result = range_check.main(["--ble", "BT24", "--duration", ".01", "--output", str(output)])
        self.assertEqual(result, 0)
        self.assertTrue(output.is_file())

    def test_range_check_close_failure_returns_error(self):
        output = self.root / "range.csv"
        with patch.object(range_check, "SimLink", CloseFailureSimLink):
            result = range_check.main(["--simulate", "--duration", ".01", "--output", str(output)])
        self.assertEqual(result, 1)
        self.assertTrue(output.is_file())

    def test_legacy_ble_check_new_entry_point_and_existing_output(self):
        output = self.root / "ble.json"
        with patch.object(ble_check, "BleLink", LegacySimLink):
            self.assertEqual(ble_check.main(["--target", "BT24", "--output", str(output)]), 0)
            previous = output.read_text(encoding="utf-8")
            self.assertEqual(ble_check.main(["--output", str(output)]), 1)
        self.assertTrue(json.loads(previous)["protocol_ready"])
        self.assertEqual(output.read_text(encoding="utf-8"), previous)


if __name__ == "__main__":
    unittest.main()
