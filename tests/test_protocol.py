import unittest
from types import SimpleNamespace
from unittest.mock import patch

from host.protocol import CarClient, ControlStatus, HardwareStatus, LineDiagnostics, PidSettings, RangeDiagnostics, SerialLink, ServoSettings, SimLink, Status, parse_debug_limit


def serial_bytes(response, reads=None):
    """Fake a UART input buffer that consumes at most the requested byte count."""
    pending = bytearray(response)

    def read(size):
        if reads is not None:
            reads.append(size)
        result = bytes(pending[:size])
        del pending[:size]
        return result

    return read


class TimedSerialPort:
    """A fake UART whose byte arrival times advance a monotonic test clock."""

    def __init__(self, arrivals):
        self.now = 0.0
        self.arrivals = list(arrivals)
        self._timeout = 2.0
        self.timeout_writes = []
        self.reads = []
        self.writes = []

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        self.timeout_writes.append(value)
        self._timeout = value

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def read(self, size):
        if size != 1:
            raise AssertionError("fake UART reads one byte at a time")
        self.reads.append((self.now, self.timeout))
        if self.arrivals and self.arrivals[0][0] <= self.now + self.timeout:
            self.now, data = self.arrivals.pop(0)
            return data
        self.now += self.timeout
        return b""

    def close(self):
        pass

    def reset_input_buffer(self):
        pass


class ProtocolTests(unittest.TestCase):
    def test_servo_settings_accept_symmetric_endpoints_and_zero_span(self):
        for center, span in ((1500, 200), (1500, 1000), (500, 0), (2500, 0), (1600, 300)):
            settings = ServoSettings.parse(f"SERVO {center} {span}")
            self.assertEqual((settings.minimum_us, settings.maximum_us), (center - span, center + span))
        for response in ("SERVO 1500 -1", "SERVO 1500 1001", "SERVO 500 1", "SERVO 2500 1",
                         "SERVO 499 0", "SERVO 2501 0", "SERVO 1500 200 extra", "SERVO 1500.0 200",
                         "SERVO １５００ 200", "SERVO +1500 200", "ERR COMMAND"):
            with self.subTest(response=response), self.assertRaises(ValueError):
                ServoSettings.parse(response)

    def test_servo_invalid_pair_is_rejected_atomically_before_send(self):
        lines = []
        client = CarClient(SimLink(), lambda direction, line: lines.append((direction, line)))
        client.set_servo(1600, 300)
        lines.clear()
        for center, span in ((500, 1), (2500, 1), (1600, 1000), (1600, -1), (1500, 1001),
                             (True, 200), (1500.0, 200), (1500, "200")):
            with self.subTest(center=center, span=span), self.assertRaises(ValueError):
                client.set_servo(center, span)
        self.assertEqual(lines, [])
        for command in ("SERVO SET 500 1", "SERVO SET 1600 1000", "SERVO SET 1400 200 extra",
                        "SERVO SET 1400.0 100", "SERVO SET nan 200", "SERVO SET 1400"):
            self.assertEqual(client.link.request(command), "ERR PARAM")
        self.assertEqual(client.servo(), ServoSettings(1600, 300))

    def test_servo_flash_and_pid_flash_are_independent_and_reboot_restores(self):
        link = SimLink()
        client = CarClient(link)
        with self.assertRaisesRegex(RuntimeError, "ERR EMPTY"):
            client.load_servo()
        client.set_pid("line_kp", 32)
        client.save_pid()
        client.set_servo(1620, 280)
        self.assertFalse(client.servo_saved())
        client.save_servo()
        self.assertTrue(client.servo_saved())
        self.assertTrue(client.pid_saved())
        client.set_pid("line_kp", 45)
        client.set_servo(1510, 100)
        client.load_servo()
        self.assertEqual(client.servo(), ServoSettings(1620, 280))
        self.assertEqual(client.pid().values["line_kp"], 45)
        self.assertFalse(client.pid_saved())
        client.reset_servo()
        self.assertEqual(client.servo(), ServoSettings())
        self.assertFalse(client.servo_saved())
        link.reboot()
        self.assertEqual(client.servo(), ServoSettings(1620, 280))
        self.assertEqual(client.status().steer_us, 1620)
        self.assertEqual(client.pid().values["line_kp"], 32)
        client.set_servo(1530, 90)
        client.load_pid()
        self.assertEqual(client.servo(), ServoSettings(1530, 90))
        client.save_pid()
        link.reboot()
        self.assertEqual(client.servo(), ServoSettings(1620, 280))

    def test_servo_updates_require_idle_and_ready(self):
        client = CarClient(SimLink())
        client.set_servo(1600, 250)
        client.debug()
        for command in ("SERVO SET 1500 200", "SERVO SAVE", "SERVO LOAD", "SERVO RESET"):
            self.assertEqual(client.link.request(command), "ERR STATE")
        self.assertEqual(client.servo(), ServoSettings(1600, 250))
        client.stop()
        client.link.hardware_ready = False
        for command in ("SERVO SET 1500 200", "SERVO SAVE", "SERVO LOAD", "SERVO RESET"):
            self.assertEqual(client.link.request(command), "ERR HARDWARE")
        self.assertEqual(client.servo(), ServoSettings(1600, 250))

    def test_servo_drive_and_all_recentering_use_readback_settings(self):
        with patch("host.protocol.time.monotonic", return_value=100.0):
            client = CarClient(SimLink())
            # Read settings changed through another protocol entry point.
            self.assertEqual(client.link.request("SERVO SET 1800 300"), "OK")
            client.servo()
            client.debug()
            client.drive(0, 0, 2100)
            self.assertEqual(client.status().steer_us, 2100)
            client.link.last_drive -= 1
            self.assertEqual(client.control().steer_us, 1800)
            for pulse in (1499, 2101):
                with self.assertRaises(ValueError):
                    client.drive(0, 0, pulse)
                self.assertEqual(client.link.request(f"DRIVE 0 0 {pulse}"), "ERR STATE_OR_RANGE")
            client.speed(20, 20)
            self.assertEqual(client.control().steer_us, 1800)
            client.drive(200, 0, 2100)
            client.link.last_drive -= 1
            self.assertEqual(client.control().steer_us, 1800)
            client.drive(0, 0, 1500)
            client.stop()
            self.assertEqual(client.status().steer_us, 1800)
            client.set_servo(1700, 0)
            client.debug()
            client.drive(100, 100, 1700)
            with self.assertRaises(ValueError):
                client.drive(0, 0, 1701)

    def test_servo_unsupported_firmware_reports_update(self):
        link = SimpleNamespace(request=lambda command: "PONG 2" if command == "PING" else "ERR COMMAND",
                               close=lambda: None)
        client = CarClient(link)
        for operation in (client.servo, client.servo_saved, client.save_servo, client.load_servo,
                          client.reset_servo, lambda: client.set_servo(1500, 200)):
            with self.assertRaisesRegex(RuntimeError, "不支持舵机"):
                operation()
        self.assertEqual(client.servo_settings, ServoSettings())

    def test_status_and_control_accept_servo_hardware_endpoints(self):
        for pulse in (500, 1200, 1800, 2500):
            self.assertEqual(ControlStatus.parse(f"CTRL 0 0 0 0 0 0 0 {pulse}").steer_us, pulse)
            self.assertEqual(Status.parse(f"STAT IDLE 0 24 500 500 500 0 0 0 0 0 {pulse}").steer_us, pulse)
        for pulse in (499, 2501):
            with self.assertRaises(ValueError):
                ControlStatus.parse(f"CTRL 0 0 0 0 0 0 0 {pulse}")
            with self.assertRaises(ValueError):
                Status.parse(f"STAT IDLE 0 24 500 500 500 0 0 0 0 0 {pulse}")

    def test_line_diagnostics_raw_and_normalized(self):
        for raw in range(256):
            for level in (0, 1):
                bits = raw if level else raw ^ 255
                d = LineDiagnostics.parse(f"LINE {raw} {bits} {level} 500 10")
                self.assertEqual(d.line_bits, bits)
                self.assertEqual(d.raw_bits, raw)
        self.assertEqual(CarClient(SimLink()).line_diagnostics().line_bits, 24)
        for response in ("LINE 256 0 0 500 0", "LINE 24 24 0 500 0",
                         "LINE 0 255 2 500 0", "LINE 0 255 0 0 0",
                         "LINE 0 255 0 500 -1", "ERR NOT_READY"):
            with self.assertRaises(ValueError):
                LineDiagnostics.parse(response)

    def test_hardware_status(self):
        self.assertFalse(HardwareStatus.parse("HW 0 CLOCK").ready)
        self.assertEqual(CarClient(SimLink()).hardware(), HardwareStatus(True, "READY"))
        for response in ("HW 1 CLOCK", "HW 0 READY", "HW 2 CLOCK", "HW 0 OTHER"):
            with self.assertRaises(ValueError):
                HardwareStatus.parse(response)
        status = Status.parse("STAT FAULT 6 0 -1 -1 -1 0 0 0 0 0 1500")
        self.assertEqual(status.fault, 6)

    def test_range_diagnostics(self):
        d = RangeDiagnostics.parse("RANGE C NO_RISE 0 0 0 -1 20 12 0 0 12 0 12345 167 0 1")
        self.assertIsNone(d.distance_mm)
        self.assertEqual(d.timeouts, 12)
        self.assertTrue(d.timer_running)
        self.assertEqual(d.prescaler, 167)
        never = RangeDiagnostics.parse("RANGE L NEVER 0 0 0 -1 4294967295 0 0 0 0 0 1 167 0 1")
        self.assertIsNone(never.age_ms)
        for response in (
                "RANGE C NO_RISE 1 0 0 -1 20 12 0 0 12 0 12345 167 0 1",
                "RANGE C NO_RISE 0 0 0 -1 20 -1 0 0 12 0 12345 167 0 1",
                "RANGE X OK 1 0 1000 171 0 1 1 1 0 0 1 167 0 1"):
            with self.assertRaises(ValueError):
                RangeDiagnostics.parse(response)
        client = CarClient(SimLink())
        for side in ("L", "C", "R"):
            self.assertEqual(client.range_diagnostics(side).distance_mm, 500)
        with self.assertRaises(ValueError):
            client.range_diagnostics("left")
        client.link.left_mm = None
        self.assertFalse(client.range_diagnostics("L").valid)

    def test_range_wrong_channel_rejected(self):
        link = SimpleNamespace(request=lambda command: "PONG 2" if command == "PING" else
                               "RANGE R OK 1 0 1000 171 0 1 1 1 0 0 1 83 0 1", close=lambda: None)
        with self.assertRaises(ValueError):
            CarClient(link).range_diagnostics("C")

    def test_status_validation(self):
        status = Status.parse("STAT FOLLOW 0 24 500 230 -1 8 -4 2 250 250 1500")
        self.assertEqual(status.line_bits, 24)
        self.assertEqual(status.center_mm, 230)
        self.assertIsNone(status.right_mm)
        with self.assertRaises(ValueError):
            Status.parse("STAT FOLLOW 0 256 500 500 500 0 0 0 0 0 1500")

    def test_mode_guards_and_debug_deadman(self):
        link = SimLink()
        client = CarClient(link)
        client.debug()
        with self.assertRaises(RuntimeError):
            client.arm()
        with self.assertRaisesRegex(RuntimeError, "ERR STATE_OR_RANGE"):
            client.drive(301, 0, 1500)
        client.drive(200, -100, 1550)
        self.assertEqual(client.status().motor_left, 200)
        link.last_drive -= 1
        self.assertEqual(client.status().motor_left, 0)
        client.stop()
        self.assertEqual(client.status().state, "IDLE")

    def test_debug_limit_response_validation(self):
        for limit in (1, 300, 1000):
            self.assertEqual(parse_debug_limit(f"LIMIT {limit}"), limit)
        for response in ("LIMIT 0", "LIMIT 1001", "LIMIT -1", "LIMIT 30.0",
                         "LIMIT nan", "LIMIT +300", "LIMIT ３００", "LIMIT 300 extra",
                         "LIMIT", "OTHER 300", "ERR COMMAND", None):
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_debug_limit(response)

    def test_debug_limit_and_drive_client_reject_invalid_physical_values_before_sending(self):
        lines = []
        client = CarClient(SimLink(), lambda direction, line: lines.append((direction, line)))
        client.debug()
        lines.clear()
        for value in (True, False, "1000", None, 0, -1, 1001, 300.0,
                      float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.set_debug_limit(value)
        for value in (-1001, 1001, 100.0, True, "100", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.drive(value, 0, 1500)
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.drive(0, value, 1500)
        self.assertEqual(lines, [])
        client.set_debug_limit(1000)
        self.assertEqual(client.debug_limit(), 1000)
        client.drive(1000, -1000, 1500)
        self.assertEqual((client.status().motor_left, client.status().motor_right), (1000, -1000))
        self.assertIn(("TX", "DEBUG LIMIT 1000"), lines)
        self.assertIn(("TX", "DEBUG LIMIT?"), lines)

    def test_debug_limit_requires_explicit_stationary_debug_unlock(self):
        with patch("host.protocol.time.monotonic", return_value=100.0):
            client = CarClient(SimLink())
            self.assertEqual(client.debug_limit(), 300)
            with self.assertRaisesRegex(RuntimeError, "ERR STATE_OR_RANGE"):
                client.set_debug_limit(1000)
            client.debug()
            with self.assertRaisesRegex(RuntimeError, "ERR STATE_OR_RANGE"):
                client.drive(1000, 0, 1500)
            client.set_debug_limit(1000)
            client.drive(1000, 0, 1500)
            with self.assertRaisesRegex(RuntimeError, "ERR STATE_OR_RANGE"):
                client.set_debug_limit(500)
            self.assertEqual(client.debug_limit(), 1000)
            client.drive(0, 0, 1500)
            client.set_debug_limit(500)
            client.speed(20, 0)  # Active speed targets count as motion before first PID tick.
            self.assertEqual(client.control().left_pwm, 0)
            with self.assertRaisesRegex(RuntimeError, "ERR STATE_OR_RANGE"):
                client.set_debug_limit(1000)
            self.assertEqual(client.debug_limit(), 500)
            client.speed(0, 0)
            client.set_debug_limit(1000)
            client.stop()
            self.assertEqual(client.debug_limit(), 300)
            client.arm()
            with self.assertRaisesRegex(RuntimeError, "ERR STATE_OR_RANGE"):
                client.set_debug_limit(1000)

    def test_debug_limit_simulator_rejects_malformed_and_out_of_range_commands(self):
        with patch("host.protocol.time.monotonic", return_value=100.0):
            link = SimLink()
            client = CarClient(link)
            client.debug()
            client.set_debug_limit(1000)
            for command in ("DEBUG LIMIT 0", "DEBUG LIMIT -1", "DEBUG LIMIT 1001",
                            "DEBUG LIMIT 30.0", "DEBUG LIMIT nan", "DEBUG LIMIT 3_00",
                            "DEBUG LIMIT 100 200", "DEBUG LIMIT ", "DRIVE 1001 0 1500",
                            "DRIVE 0 -1001 1500"):
                with self.subTest(command=command):
                    self.assertEqual(link.request(command), "ERR STATE_OR_RANGE")
                    self.assertEqual(client.debug_limit(), 1000)
                    self.assertEqual((link.motor_left, link.motor_right), (0, 0))

    def test_debug_limit_stationary_and_release_preserve_session_unlock(self):
        with patch("host.protocol.time.monotonic", return_value=100.0) as clock:
            client = CarClient(SimLink())
            client.debug()
            client.set_debug_limit(1000)
            clock.return_value = 101.0
            self.assertEqual(client.debug_limit(), 1000)
            client.drive(900, 0, 1500)
            clock.return_value = 101.1
            client.drive(0, 0, 1500)
            clock.return_value = 102.0
            self.assertEqual(client.debug_limit(), 1000)
            client.speed(20, 0)
            clock.return_value = 102.1
            client.speed(0, 0)
            clock.return_value = 103.0
            self.assertEqual(client.debug_limit(), 1000)
            self.assertEqual((client.control().left_pwm, client.control().right_pwm), (0, 0))

    def test_debug_limit_watchdog_relocks_motion_but_retains_debug_state(self):
        for motion in (lambda client: client.drive(900, -900, 1500),
                       lambda client: client.speed(20, 0)):
            with self.subTest(motion=motion), patch("host.protocol.time.monotonic", return_value=100.0) as clock:
                client = CarClient(SimLink())
                client.debug()
                client.set_debug_limit(1000)
                motion(client)
                clock.return_value = 100.6
                self.assertEqual(client.debug_limit(), 300)
                status = client.status()
                self.assertEqual((status.state, status.motor_left, status.motor_right), ("DEBUG", 0, 0))
                self.assertEqual(client.control().left_target, 0)
                with self.assertRaisesRegex(RuntimeError, "ERR STATE_OR_RANGE"):
                    client.drive(900, 0, 1500)

    def test_debug_limit_stop_reboot_and_fault_relock(self):
        with patch("host.protocol.time.monotonic", return_value=100.0):
            link = SimLink()
            client = CarClient(link)
            for end in (client.stop, link.reboot):
                client.debug()
                client.set_debug_limit(1000)
                end()
                self.assertEqual(client.debug_limit(), 300)
                client.debug()
                self.assertEqual(client.debug_limit(), 300)
                client.stop()
            client.debug()
            client.set_debug_limit(1000)
            client.drive(900, 0, 1500)
            link.hardware_ready = False
            self.assertEqual(client.debug_limit(), 300)
            self.assertEqual(client.status().state, "FAULT")
            with self.assertRaisesRegex(RuntimeError, "ERR HARDWARE"):
                client.set_debug_limit(1000)
            self.assertEqual(client.control().left_pwm, 0)

    def test_debug_limit_pid_clamp_and_anti_windup_follow_confirmed_limit(self):
        with patch("host.protocol.time.monotonic", return_value=100.0) as clock:
            link = SimLink()
            client = CarClient(link)
            client.debug()
            client.speed(20, 0)
            clock.return_value = 100.01
            self.assertEqual(client.control().left_pwm, 300)
            self.assertEqual(link._speed_integrals[0], 0)
            client.speed(0, 0)
            client.set_debug_limit(1000)
            client.speed(20, 0)
            clock.return_value = 100.02
            self.assertGreater(client.control().left_pwm, 300)
            self.assertGreater(link._speed_integrals[0], 0)
            client.speed(0, 0)
            client.set_debug_limit(100)
            client.speed(500, 0)
            clock.return_value = 100.03
            self.assertEqual(client.control().left_pwm, 100)
            self.assertEqual(link._speed_integrals[0], 0)

    def test_debug_limit_unsupported_firmware_reports_required_update(self):
        link = SimpleNamespace(request=lambda command: "PONG 2" if command == "PING" else
                               "ERR COMMAND", close=lambda: None)
        client = CarClient(link)
        with self.assertRaisesRegex(RuntimeError, "需要更新为新版固件"):
            client.debug_limit()
        with self.assertRaisesRegex(RuntimeError, "需要更新为新版固件"):
            client.set_debug_limit(1000)

    def test_auto_is_read_only_until_stop(self):
        client = CarClient(SimLink())
        client.arm()
        with self.assertRaises(RuntimeError):
            client.debug()
        with self.assertRaises(RuntimeError):
            client.drive(100, 100, 1500)
        client.close()
        self.assertEqual(client.status().state, "ARMED")

    def test_speed_client_formats_targets_and_rejects_before_sending(self):
        lines = []
        client = CarClient(SimLink(), lambda direction, line: lines.append((direction, line)))
        client.debug()
        lines.clear()
        for value in (True, False, "20", None, float("nan"), float("inf"),
                      float("-inf"), -.001, 500.001, 10 ** 400):
            for side in (0, 1):
                targets = [20, 20]
                targets[side] = value
                with self.subTest(value=value, side=side), self.assertRaises(ValueError):
                    client.speed(*targets)
        self.assertEqual(lines, [])
        client.speed(12.3456, 500)
        client.speed(-0.0, 0)
        self.assertEqual([line for direction, line in lines if direction == "TX"],
                         ["SPEED 12.346 500.000", "SPEED 0.000 0.000"])

    def test_speed_requires_debug_and_does_not_relax_pid_guards(self):
        client = CarClient(SimLink())
        with self.assertRaisesRegex(RuntimeError, "ERR STATE_OR_RANGE"):
            client.speed(20, 20)
        client.arm()
        with self.assertRaisesRegex(RuntimeError, "ERR STATE_OR_RANGE"):
            client.speed(20, 20)
        client.stop()
        client.debug()
        client.speed(20, 10)
        with self.assertRaisesRegex(RuntimeError, "ERR STATE"):
            client.set_pid("speed_kp", 4)
        with self.assertRaisesRegex(RuntimeError, "ERR STATE"):
            client.save_pid()

    def test_simulated_speed_targets_measurements_and_bounded_output(self):
        with patch("host.protocol.time.monotonic", return_value=100.0) as clock:
            client = CarClient(SimLink())
            client.debug()
            client.speed(500, 10)
            clock.return_value = 100.2
            control = client.control()
            self.assertEqual((control.left_target, control.right_target), (500, 10))
            self.assertGreater(control.left_measured, 0)
            self.assertGreater(control.right_measured, 0)
            self.assertTrue(0 < control.left_pwm <= 300)
            self.assertTrue(0 < control.right_pwm <= 300)
            self.assertEqual(control.steer_us, 1500)
            client.speed(0, 10)
            control = client.control()
            self.assertEqual((control.left_target, control.left_pwm), (0, 0))

    def test_speed_keepalive_retains_controller_state_and_watchdog_clears_targets(self):
        with patch("host.protocol.time.monotonic", return_value=100.0) as clock:
            link = SimLink()
            client = CarClient(link)
            client.set_pid("feedforward_pwm", 0)
            client.set_pid("speed_kp", 1)
            client.debug()
            client.speed(10, 10)
            clock.return_value = 100.2
            client.speed(10, 10)
            integrals = link._speed_integrals.copy()
            self.assertGreater(integrals[0], 0)
            client.speed(10, 10)
            self.assertEqual(link._speed_integrals, integrals)
            clock.return_value = 100.6  # The repeated request renewed the 500 ms watchdog.
            self.assertGreater(client.control().left_pwm, 0)
            clock.return_value = 100.71
            expired = client.control()
            self.assertEqual((expired.left_target, expired.right_target,
                              expired.left_pwm, expired.right_pwm), (0, 0, 0, 0))
            clock.return_value = 102
            self.assertEqual(client.control().left_pwm, 0)
            self.assertEqual(client.status().state, "DEBUG")

    def test_drive_and_speed_share_watchdog_and_mode_switches_clear_targets(self):
        with patch("host.protocol.time.monotonic", return_value=100.0) as clock:
            client = CarClient(SimLink())
            client.debug()
            client.speed(20, 20)
            clock.return_value = 100.3
            client.drive(-100, 200, 1600)
            control = client.control()
            self.assertEqual((control.left_target, control.right_target), (0, 0))
            clock.return_value = 100.7
            control = client.control()
            self.assertEqual((control.left_pwm, control.right_pwm, control.steer_us), (-100, 200, 1600))
            self.assertGreater(control.left_measured, 0)
            self.assertGreater(control.right_measured, 0)
            measured = (control.left_measured, control.right_measured)
            client.drive(-100, 200, 1600)
            renewed = client.control()
            self.assertEqual((renewed.left_measured, renewed.right_measured), measured)
            clock.return_value = 100.81
            self.assertEqual(client.control().left_pwm, -100)
            clock.return_value = 101.21
            self.assertEqual(client.control().left_pwm, 0)

    def test_new_speed_target_resets_controller_without_clearing_measurement(self):
        with patch("host.protocol.time.monotonic", return_value=100.0) as clock:
            link = SimLink()
            client = CarClient(link)
            client.set_pid("feedforward_pwm", 0)
            client.set_pid("speed_kp", 1)
            client.debug()
            client.speed(10, 10)
            clock.return_value = 100.2
            before = client.control()
            self.assertGreater(link._speed_integrals[0], 0)
            client.speed(15, 10)
            self.assertEqual(link._speed_integrals, [0, 0])
            self.assertEqual(link._speed_previous, [None, None])
            after = client.control()
            self.assertEqual(after.left_measured, before.left_measured)
            self.assertEqual((after.left_target, after.right_target), (15, 10))
            client.speed(0, 0)
            self.assertFalse(link._speed_active)
            self.assertEqual(link._speed_integrals, [0, 0])
            stopped = client.control()
            self.assertEqual((stopped.left_target, stopped.right_target,
                              stopped.left_pwm, stopped.right_pwm), (0, 0, 0, 0))
            self.assertEqual(stopped.left_measured, before.left_measured)

    def test_speed_stop_debug_and_reboot_never_resume_previous_targets(self):
        with patch("host.protocol.time.monotonic", return_value=100.0) as clock:
            link = SimLink()
            client = CarClient(link)
            for end in (client.stop, link.reboot):
                client.debug()
                client.speed(20, 10)
                clock.return_value += .1
                self.assertGreater(client.control().left_pwm, 0)
                end()
                stopped = client.control()
                self.assertEqual((stopped.left_target, stopped.right_target,
                                  stopped.left_pwm, stopped.right_pwm), (0, 0, 0, 0))
                client.debug()
                clock.return_value += .1
                self.assertEqual(client.control().left_pwm, 0)
                client.stop()

    def test_simulated_speed_rejects_malformed_tokens_without_renewing_watchdog(self):
        with patch("host.protocol.time.monotonic", return_value=100.0):
            link = SimLink()
            self.assertEqual(link.request("DEBUG"), "OK")
            self.assertEqual(link.request("SPEED +2.5e1  .5 "), "OK")
            last_drive = link.last_drive
            for command in ("SPEED 1", "SPEED 1 2 3", "SPEED nan 1", "SPEED inf 1",
                            "SPEED 1 -1", "SPEED 501 1", "SPEED 1e400 1", "SPEED 2_0 1",
                            "SPEED 1+2", "SPEED 0x1p1 1", "SPEED 20junk 1",
                            "SPEED 1e-500 1", "SPEED 1e-40 1", "SPEED -1e-500 1"):
                with self.subTest(command=command):
                    self.assertEqual(link.request(command), "ERR STATE_OR_RANGE")
                    self.assertEqual(link.last_drive, last_drive)
                    self.assertEqual((link.left_target, link.right_target), (25, .5))
            self.assertEqual(link.request("SPEED 0e-500 1.2e-38"), "OK")

    def test_simulated_hardware_failure_blocks_manual_motion(self):
        link = SimLink()
        client = CarClient(link)
        client.debug()
        client.speed(20, 20)
        link.hardware_ready = False
        self.assertFalse(client.hardware().ready)
        for command in ("SPEED 20 20", "DRIVE 100 100 1500", "DEBUG", "AUTO ARM"):
            with self.subTest(command=command):
                self.assertEqual(link.request(command), "ERR HARDWARE")
        control = client.control()
        self.assertEqual((control.left_target, control.left_pwm), (0, 0))
        self.assertEqual((client.status().state, client.status().fault), ("FAULT", 6))

    def test_pid_tuning_and_monitor(self):
        lines = []
        link = SimLink()
        client = CarClient(link, lambda direction, line: lines.append((direction, line)))
        self.assertEqual(client.pid().values["line_kp"], 27.0)
        self.assertFalse(client.pid_saved())
        client.set_pid("line_kp", 32.5)
        self.assertEqual(client.pid().values["line_kp"], 32.5)
        self.assertFalse(client.pid_saved())
        client.save_pid()
        self.assertTrue(client.pid_saved())
        link.reboot()
        self.assertEqual(client.pid().values["line_kp"], 32.5)
        client.set_pid("line_kp", 30.0)
        self.assertFalse(client.pid_saved())
        client.load_pid()
        self.assertEqual(client.pid().values["line_kp"], 32.5)
        self.assertEqual(client.control().steer_us, 1500)
        with self.assertRaises(ValueError):
            client.set_pid("differential_gain", 2.0)
        client.arm()
        with self.assertRaises(RuntimeError):
            client.set_pid("line_kp", 30.0)
        with self.assertRaises(RuntimeError):
            client.save_pid()
        client.stop()
        client.reset_pid()
        self.assertEqual(client.pid().values["line_kp"], 27.0)
        self.assertFalse(client.pid_saved())
        self.assertIn(("TX", "PID?"), lines)
        self.assertTrue(any(direction == "RX" and line.startswith("PID ") for direction, line in lines))

    def test_pid_response_validation(self):
        with self.assertRaises(ValueError):
            PidSettings.parse("PID nan 0 0 0 0 0 1 0 0 0")
        with self.assertRaises(ValueError):
            ControlStatus.parse("CTRL nan 0 0 0 0 0 0 1500")

    def test_control_and_encoder_limits(self):
        for response in ("CTRL 0 0 0 0 0 1001 0 1500",
                         "CTRL 0 0 0 0 0 0 -1001 1500",
                         "CTRL 0 0 0 0 0 0 0 2501"):
            with self.assertRaises(ValueError):
                ControlStatus.parse(response)
        with self.assertRaises(ValueError):
            Status.parse("STAT IDLE 0 24 500 500 500 2147483648 0 0 0 0 1500")

    def test_small_target_rounding_rejected_before_send(self):
        lines = []
        client = CarClient(SimLink(), lambda direction, line: lines.append((direction, line)))
        lines.clear()
        for value in (.0001, True, "20"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.set_pid("target_ticks", value)
        self.assertEqual(lines, [])

    def test_simulated_missing_ranges_and_start_fault(self):
        client = CarClient(SimLink())
        client.link.left_mm = None
        client.link.center_mm = -1
        self.assertIsNone(client.status().left_mm)
        self.assertIsNone(client.status().center_mm)
        self.assertFalse(client.range_diagnostics("L").valid)
        client.arm()
        client.link.arm_time -= 4
        client.control()  # Advancement must not depend on STATUS? polling.
        self.assertEqual(client.link.state, "FAULT")
        self.assertEqual(client.status().fault, 2)
        client.stop()
        self.assertEqual(client.status().fault, 0)

    def test_control_query_applies_debug_watchdog(self):
        with patch("host.protocol.time.monotonic", return_value=100.0) as clock:
            client = CarClient(SimLink())
            client.debug()
            client.drive(200, -100, 1550)
            clock.return_value = 100.5
            control = client.control()
        self.assertEqual((control.left_pwm, control.right_pwm, control.steer_us), (0, 0, 1500))

    def test_simulator_error_replies_and_whitespace_match_firmware(self):
        link = SimLink()
        for command, expected in (("UNKNOWN", "ERR COMMAND"),
                                  ("PID SET line_kp", "ERR PARAM"),
                                  ("PID SET line_kp 30 extra", "ERR PARAM"),
                                  ("PID SET line_kp nan", "ERR PARAM"),
                                  ("PID SET line_kp  30 ", "OK"),
                                  ("DRIVE 100 100 1500", "ERR STATE_OR_RANGE"),
                                  ("DEBUG", "OK"),
                                  ("DRIVE +100  -100 +1500 ", "OK"),
                                  ("PID SET line_kp", "ERR STATE"),
                                  ("DRIVE 1+2+1500", "ERR STATE_OR_RANGE")):
            with self.subTest(command=command):
                self.assertEqual(link.request(command), expected)

    def test_simulator_pid_defaults_are_independent(self):
        first, second = SimLink(), SimLink()
        first.pid_values["line_kp"] = 50
        self.assertEqual(second.pid_values["line_kp"], 27)
        self.assertEqual(first.request("PID RESET"), "OK")
        self.assertEqual(first.pid_values, second.pid_values)
        first.pid_values["line_kp"] = 50
        first.reboot()
        self.assertEqual(first.pid_values, second.pid_values)

    def test_serial_partial_ack_requires_reconnect(self):
        port = SimpleNamespace(timeout=.4, write=lambda data: len(data),
                               read=serial_bytes(b"OK"), close=lambda: None, open=lambda: None,
                               reset_input_buffer=lambda: None)
        fake_serial = SimpleNamespace(Serial=lambda *a, **kw: port, EIGHTBITS=8,
                                      PARITY_NONE="N", STOPBITS_ONE=1)
        with patch.dict("sys.modules", {"serial": fake_serial}):
            link = SerialLink("COM3")
        with self.assertRaises(TimeoutError):
            link.request("DRIVE 100 100 1500")
        with self.assertRaises(ConnectionError):
            link.request("DRIVE 0 0 1500")

    def test_spp_serial_configuration_and_flash_timeout(self):
        opened, sent, resets, timeouts, control_at_open = [], [], [], [], []
        pending = bytearray()
        def write(data):
            sent.append(data)
            pending.extend(b"OK\r\n" if data == b"PID SAVE\n" else b"PONG 2\r\n")
            return len(data)
        port = SimpleNamespace(timeout=2.0, write=write,
                               close=lambda: None, reset_input_buffer=lambda: resets.append(True))
        def read(size):
            timeouts.append(port.timeout)
            result = bytes(pending[:size])
            del pending[:size]
            return result
        port.read = read
        port.open = lambda: control_at_open.append((port.port, port.dtr, port.rts))
        def open_port(*args, **kwargs):
            opened.append((args, kwargs))
            return port
        fake_serial = SimpleNamespace(Serial=open_port, EIGHTBITS=8, PARITY_NONE="N", STOPBITS_ONE=1)
        with patch.dict("sys.modules", {"serial": fake_serial}), patch("host.protocol.time.monotonic", return_value=0.0):
            client = CarClient(SerialLink("com12"))
            client.save_pid()
        self.assertEqual(opened[0][0], (None, 9600))
        self.assertEqual(opened[0][1], dict(timeout=2.0, write_timeout=2.0, bytesize=8,
                                         parity="N", stopbits=1, xonxoff=False,
                                         rtscts=False, dsrdtr=False))
        self.assertEqual(resets, [True])
        self.assertEqual(control_at_open, [("COM12", False, False)])
        self.assertEqual(sent, [b"PING\n", b"PID SAVE\n"])
        self.assertEqual(timeouts, [2.0] * 8 + [5.0] * 4)
        self.assertEqual(port.timeout, 2.0)

    def serial_link(self, port):
        if not hasattr(port, "open"):
            port.open = lambda: None
        fake_serial = SimpleNamespace(Serial=lambda *args, **kwargs: port, EIGHTBITS=8,
                                      PARITY_NONE="N", STOPBITS_ONE=1)
        with patch.dict("sys.modules", {"serial": fake_serial}):
            return SerialLink("COM3")

    def test_serial_open_failure_closes_port_and_preserves_error(self):
        closed = []
        def fail_open():
            raise OSError("COM5 is in use")
        def fail_close():
            closed.append(True)
            raise OSError("cleanup failure")
        port = SimpleNamespace(open=fail_open, close=fail_close)
        with self.assertRaisesRegex(OSError, "COM5 is in use"):
            self.serial_link(port)
        self.assertEqual(closed, [True])

    def test_serial_control_line_failure_does_not_open_device(self):
        events = []
        class Port:
            @property
            def dtr(self):
                return True
            @dtr.setter
            def dtr(self, value):
                raise OSError("control line configuration failed")
            def open(self):
                events.append("open")
            def close(self):
                events.append("close")
        with self.assertRaisesRegex(OSError, "control line configuration failed"):
            self.serial_link(Port())
        self.assertEqual(events, ["close"])

    def test_serial_input_reset_failure_closes_opened_port(self):
        events = []
        def fail_reset():
            events.append("reset")
            raise OSError("input reset failed")
        port = SimpleNamespace(open=lambda: events.append("open"),
                               close=lambda: events.append("close"),
                               reset_input_buffer=fail_reset)
        with self.assertRaisesRegex(OSError, "input reset failed"):
            self.serial_link(port)
        self.assertEqual(events, ["open", "reset", "close"])

    def test_serial_rejects_invalid_commands_without_poisoning_connection(self):
        sent = []
        port = SimpleNamespace(timeout=2.0, write=lambda data: sent.append(data) or len(data),
                               read=serial_bytes(b"PONG 2\r\n"), close=lambda: None,
                               reset_input_buffer=lambda: None)
        link = self.serial_link(port)
        for command in ("", "PING\nSTOP", "PING\rSTOP", "PING\x00", "PING\x7f",
                        "PID\tSAVE", "中文", "X" * 91, None):
            with self.subTest(command=command), self.assertRaises(ValueError):
                link.request(command)
        self.assertEqual(sent, [])
        self.assertEqual(link.request("PING"), "PONG 2")

    def test_client_rejects_control_characters_without_invalidating_session(self):
        sent = []
        link = SimpleNamespace(request=lambda command: sent.append(command) or "PONG 2",
                               close=lambda: None)
        client = CarClient(link)
        sent.clear()
        for command in ("PING\x00", "PING\x7f", "PID\tSAVE"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                client.request(command)
        self.assertEqual(sent, [])
        self.assertEqual(client.request("PING"), "PONG 2")

    def test_serial_partial_write_requires_reconnect_without_reading(self):
        reads = []
        port = SimpleNamespace(timeout=2.0, write=lambda data: len(data) - 1,
                               read=serial_bytes(b"OK\n", reads),
                               close=lambda: None, reset_input_buffer=lambda: None)
        link = self.serial_link(port)
        with self.assertRaisesRegex(ConnectionError, "未完整写入"):
            link.request("DRIVE 100 100 1500")
        with self.assertRaises(ConnectionError):
            link.request("STOP")
        self.assertEqual(reads, [])
        diagnostics = link.receive_diagnostics()
        self.assertEqual(diagnostics["last_tx_bytes"], 19)
        self.assertEqual(diagnostics["last_tx_written_bytes"], 18)
        self.assertEqual(diagnostics["last_rx_bytes"], 0)
        self.assertEqual(diagnostics["receive_status"], "write_incomplete")

    def test_serial_diagnostics_distinguish_empty_partial_and_garbled_rx(self):
        cases = ((b"", "zero_bytes", "零字节"),
                 (b"PONG 2", "incomplete", "缺少结尾换行"),
                 (b"\xbf\xbf\xff", "non_ascii", "乱码"))
        for response, status, reason in cases:
            with self.subTest(response=response):
                reads = []
                port = SimpleNamespace(timeout=2.0, write=lambda data: len(data),
                                       read=serial_bytes(response, reads),
                                       close=lambda: None, reset_input_buffer=lambda: None)
                link = self.serial_link(port)
                with self.assertRaisesRegex(TimeoutError, reason) as failure:
                    link.request("PING")
                diagnostics = link.receive_diagnostics()
                self.assertEqual(diagnostics["last_tx_hex"], "50 49 4E 47 0A")
                self.assertEqual(diagnostics["last_tx_bytes"], 5)
                self.assertEqual(diagnostics["last_tx_written_bytes"], 5)
                self.assertEqual(diagnostics["last_rx_hex"], response.hex(" ").upper())
                self.assertEqual(diagnostics["last_rx_bytes"], len(response))
                self.assertEqual(diagnostics["receive_status"], status)
                self.assertIn("HEX=", str(failure.exception))
                self.assertEqual(reads, [1] * (len(response) + 1))
                with self.assertRaises(ConnectionError):
                    link.request("PING")
                self.assertEqual(reads, [1] * (len(response) + 1))

    def test_serial_diagnostics_preserve_non_ascii_error_type_and_bytes(self):
        port = SimpleNamespace(timeout=2.0, write=lambda data: len(data),
                               read=serial_bytes(b"\xbf\xbf\xff\n"),
                               close=lambda: None, reset_input_buffer=lambda: None)
        link = self.serial_link(port)
        with self.assertRaisesRegex(UnicodeDecodeError, "BF BF FF 0A"):
            link.request("PING")
        diagnostics = link.receive_diagnostics()
        self.assertEqual(diagnostics["last_rx_bytes"], 4)
        self.assertEqual(diagnostics["last_rx_hex"], "BF BF FF 0A")
        self.assertEqual(diagnostics["receive_status"], "non_ascii")
        with self.assertRaises(ConnectionError):
            link.request("PING")

    def test_serial_diagnostics_report_settings_without_reading_and_survive_close(self):
        for response in (b"PONG 2\n", b"PONG 2\r\n"):
            with self.subTest(response=response):
                reads = []
                port = SimpleNamespace(timeout=2.0, baudrate=9600, bytesize=8,
                                       parity="N", stopbits=1, write_timeout=2.0,
                                       write=lambda data: len(data),
                                       read=serial_bytes(response, reads),
                                       close=lambda: None, reset_input_buffer=lambda: None)
                link = self.serial_link(port)
                diagnostics = link.receive_diagnostics()
                self.assertEqual(reads, [])
                self.assertEqual(diagnostics["receive_status"], "not_started")
                self.assertEqual(diagnostics["last_rx_bytes"], 0)
                CarClient(link)
                link.close()
                diagnostics = link.receive_diagnostics()
                self.assertEqual(reads, [1] * len(response))
                for name, value in (("port", "COM3"), ("baudrate", 9600),
                                    ("bytesize", 8), ("parity", "N"), ("stopbits", 1),
                                    ("timeout", 2.0), ("write_timeout", 2.0),
                                    ("dtr", False), ("rts", False)):
                    self.assertEqual(diagnostics[name], value)
                self.assertEqual(diagnostics["receive_status"], "complete")
                self.assertEqual(diagnostics["last_rx_hex"], response.hex(" ").upper())
                self.assertEqual(diagnostics["last_rx_bytes"], len(response))

    def test_serial_bad_reply_poisoned_connection(self):
        for response, pending, error in ((b"X" * 161, 0, ValueError),
                                         (b"\xff\n", 0, UnicodeDecodeError),
                                         (b"OK\n", 3, ConnectionError)):
            with self.subTest(response=response, pending=pending):
                port = SimpleNamespace(timeout=2.0, write=lambda data: len(data),
                                       read=serial_bytes(response), in_waiting=pending,
                                       close=lambda: None, reset_input_buffer=lambda: None)
                link = self.serial_link(port)
                with self.assertRaises(error):
                    link.request("STOP")
                with self.assertRaises(ConnectionError):
                    link.request("PING")

    def test_serial_closed_link_rejects_requests_and_close_is_idempotent(self):
        closed = []
        port = SimpleNamespace(timeout=2.0, write=lambda data: len(data),
                               read=serial_bytes(b"OK\n"), close=lambda: closed.append(True),
                               reset_input_buffer=lambda: None)
        link = self.serial_link(port)
        link.close()
        link.close()
        with self.assertRaisesRegex(ConnectionError, "已关闭"):
            link.request("STOP")
        self.assertEqual(closed, [True])

    def test_serial_timeout_restore_preserves_original_error(self):
        class Port:
            restore_failed = False
            _timeout = 2.0

            @property
            def timeout(self):
                return self._timeout

            @timeout.setter
            def timeout(self, value):
                if self.restore_failed:
                    raise OSError("disconnected while restoring timeout")
                self._timeout = value

            def reset_input_buffer(self):
                pass

            def write(self, data):
                return len(data)

            def read(self, size):
                self.restore_failed = True
                raise TimeoutError("original read failure")

            def close(self):
                pass

        link = self.serial_link(Port())
        with self.assertRaisesRegex(TimeoutError, "original read failure"):
            link.request("PID SAVE")
        with self.assertRaises(ConnectionError):
            link.request("PING")

    def test_serial_slow_fragments_share_one_response_deadline(self):
        port = TimedSerialPort([(.6 * (i + 1), bytes([byte]))
                                for i, byte in enumerate(b"PONG 2\n")])
        link = self.serial_link(port)
        with patch("host.protocol.time.monotonic", lambda: port.now):
            with self.assertRaisesRegex(TimeoutError, "缺少结尾换行"):
                link.request("PING")
        self.assertAlmostEqual(port.now, 2.0)
        self.assertEqual(len(port.reads), 4)
        self.assertEqual(port.writes, [b"PING\n"])
        self.assertEqual(link.receive_diagnostics()["last_rx_hex"], "50 4F 4E")
        self.assertEqual(port.timeout, 2.0)
        with self.assertRaises(ConnectionError):
            link.request("PING")
        self.assertEqual(port.writes, [b"PING\n"])

    def test_serial_complete_fragmented_lines_finish_within_deadline(self):
        for response in (b"PONG 2\n", b"PONG 2\r\n"):
            with self.subTest(response=response):
                port = TimedSerialPort([(.1 * (i + 1), bytes([byte]))
                                        for i, byte in enumerate(response)])
                link = self.serial_link(port)
                with patch("host.protocol.time.monotonic", lambda: port.now):
                    CarClient(link)
                self.assertAlmostEqual(port.now, .1 * len(response))
                self.assertEqual(len(port.reads), len(response))
                self.assertTrue(all(wait <= 2.0 - now for now, wait in port.reads))
                self.assertEqual(link.receive_diagnostics()["last_rx_bytes"], len(response))
                self.assertEqual(port.timeout, 2.0)

    def test_serial_empty_response_uses_normal_or_flash_budget(self):
        for command, budget in (("PING", 2.0), ("PID SAVE", 5.0), ("SERVO SAVE", 5.0)):
            with self.subTest(command=command):
                port = TimedSerialPort([])
                link = self.serial_link(port)
                with patch("host.protocol.time.monotonic", lambda: port.now):
                    with self.assertRaisesRegex(TimeoutError, "零字节"):
                        link.request(command)
                self.assertEqual(port.now, budget)
                self.assertEqual(port.reads, [(0.0, budget)])
                self.assertEqual(port.timeout_writes, [] if budget == 2.0 else [5.0, 2.0])
                self.assertEqual(link.receive_diagnostics()["last_rx_bytes"], 0)

    def test_serial_flash_response_gets_five_seconds_in_total(self):
        for arrivals, complete in (([(3.0, b"O"), (3.5, b"K"), (4.5, b"\n")], True),
                                   ([(2.0, b"O"), (4.0, b"K"), (6.0, b"\n")], False)):
            with self.subTest(complete=complete):
                port = TimedSerialPort(arrivals)
                link = self.serial_link(port)
                with patch("host.protocol.time.monotonic", lambda: port.now):
                    if complete:
                        self.assertEqual(link.request("PID SAVE"), "OK")
                    else:
                        with self.assertRaisesRegex(TimeoutError, "缺少结尾换行"):
                            link.request("PID SAVE")
                self.assertEqual(port.now, 4.5 if complete else 5.0)
                self.assertEqual(link.receive_diagnostics()["last_rx_hex"],
                                 "4F 4B 0A" if complete else "4F 4B")
                self.assertTrue(all(wait <= 5.0 - now for now, wait in port.reads))
                self.assertEqual(port.timeout, 2.0)

    def test_serial_servo_save_response_can_arrive_after_two_seconds(self):
        port = TimedSerialPort([(3.0, b"O"), (3.5, b"K"), (4.5, b"\n")])
        link = self.serial_link(port)
        with patch("host.protocol.time.monotonic", lambda: port.now):
            self.assertEqual(link.request("SERVO SAVE"), "OK")
        self.assertEqual(port.now, 4.5)
        self.assertEqual(port.timeout, 2.0)

    def test_serial_line_size_limit_includes_terminator(self):
        for response, allowed in ((b"X" * 159 + b"\n", True),
                                  (b"X" * 160 + b"\n", False)):
            with self.subTest(allowed=allowed):
                reads = []
                port = SimpleNamespace(timeout=2.0, write=lambda data: len(data),
                                       read=serial_bytes(response, reads),
                                       close=lambda: None, reset_input_buffer=lambda: None)
                link = self.serial_link(port)
                with patch("host.protocol.time.monotonic", return_value=0.0):
                    if allowed:
                        self.assertEqual(link.request("PING"), "X" * 159)
                    else:
                        with self.assertRaisesRegex(ValueError, "超过 160"):
                            link.request("PING")
                self.assertEqual(len(reads), len(response))
                self.assertEqual(link.receive_diagnostics()["last_rx_bytes"], len(response))

    def test_serial_write_failure_does_not_reconfigure_unchanged_read_timeout(self):
        class Port(TimedSerialPort):
            def write(self, data):
                raise TimeoutError("write failed before receiving")

            @TimedSerialPort.timeout.setter
            def timeout(self, value):
                raise AssertionError("unchanged timeout must not be rewritten")

        for command in ("PING", "PID SAVE"):
            with self.subTest(command=command):
                port = Port([])
                link = self.serial_link(port)
                with self.assertRaisesRegex(TimeoutError, "write failed before receiving"):
                    link.request(command)
                self.assertEqual(port.reads, [])

    def test_serial_read_failure_keeps_received_bytes_and_original_error(self):
        class Port(TimedSerialPort):
            disconnected = False

            def read(self, size):
                if self.now > 0:
                    self.disconnected = True
                    raise OSError("read failed after partial data")
                return super().read(size)

            @TimedSerialPort.timeout.setter
            def timeout(self, value):
                if self.disconnected:
                    raise OSError("timeout cleanup failed")
                TimedSerialPort.timeout.fset(self, value)

        port = Port([(.1, b"P")])
        link = self.serial_link(port)
        with patch("host.protocol.time.monotonic", lambda: port.now):
            with self.assertRaisesRegex(OSError, "read failed after partial data"):
                link.request("PING")
        self.assertEqual(link.receive_diagnostics()["last_rx_hex"], "50")
        with self.assertRaises(ConnectionError):
            link.request("PING")

    def test_v1_rejected_and_connection_closed(self):
        closed = []
        link = SimpleNamespace(request=lambda command: "PONG 1", close=lambda: closed.append(True))
        with self.assertRaises(ConnectionError):
            CarClient(link)
        self.assertEqual(closed, [True])

    def test_handshake_close_error_preserves_original_failure(self):
        def close():
            raise OSError("close failed")
        link = SimpleNamespace(request=lambda command: "PONG 1", close=close)
        with self.assertRaisesRegex(ConnectionError, "固件握手失败"):
            CarClient(link)


if __name__ == "__main__":
    unittest.main()
