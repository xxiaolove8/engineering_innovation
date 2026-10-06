"""Tk controller regressions using simulated links and the real event pump."""

import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import tkinter as tk
except ImportError:
    tk = None

if tk is not None:
    from host.gui import App
else:
    App = None

from host.protocol import ControlStatus, ServoSettings, SimLink, Status


class GuiLink(SimLink):
    """Simulated protocol with observable cleanup and controllable slow I/O."""

    def __init__(self, hardware_reply="HW 1 READY"):
        super().__init__()
        self.hardware_reply = hardware_reply
        self._commands = []
        self._record_lock = threading.Lock()
        self.closed = threading.Event()
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.block_command = None

    @property
    def commands(self):
        with self._record_lock:
            return self._commands.copy()

    def request(self, command):
        with self._record_lock:
            self._commands.append(command)
        if command == self.block_command:
            self.blocked.set()
            if not self.release.wait(5):
                raise TimeoutError("GUI test gate timed out")
        if command == "HW?":
            return self.hardware_reply
        return super().request(command)

    def close(self):
        self.closed.set()


@unittest.skipIf(tk is None, "Tk is not installed")
class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display is unavailable: {error}")
        self.root.withdraw()
        self.callback_errors = []
        self.root.report_callback_exception = lambda _kind, error, _trace: self.callback_errors.append(error)
        self.links = []
        self.gates = []
        self.app = None
        # Do not enumerate actual ports; every connection in this file is fake.
        with patch.object(App, "_refresh_ports", return_value=None):
            self.app = App(self.root)

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        for link in self.links:
            link.release.set()
        if self.app is not None:
            if not self.app.closed:
                self.app._close()
            self.app.worker.join(3)
            self.assertFalse(self.app.worker._thread.is_alive())
        else:
            self.root.destroy()
        self.assertEqual(self.callback_errors, [], "uncaught exception in a Tk callback")

    def pump_until(self, condition, timeout=4):
        """Process Tk on its owner thread while the session worker runs."""
        deadline = time.monotonic() + timeout
        while True:
            self.root.update()
            self.assertEqual(self.callback_errors, [], "uncaught exception in a Tk callback")
            if condition():
                return
            if time.monotonic() >= deadline:
                self.fail(f"GUI did not reach expected state; notice={self.app.notice.get()!r}, "
                          f"pending={self.app._pending}, state={self.app.last_state!r}")
            time.sleep(.005)

    def connect(self, link=None, ready=True):
        link = link or GuiLink()
        self.links.append(link)
        with patch("host.gui.SimLink", return_value=link):
            self.app._connect_sim()
            self.pump_until(lambda: self.app.connected and not self.app.connecting and
                            self.app.last_state == "IDLE" and self.app.ready == ready and
                            not self.app._pending)
        self.app._cancel_timer("poll_timer")
        return link

    def settled(self, state="IDLE"):
        self.pump_until(lambda: self.app.last_state == state and not self.app._pending)
        self.app._cancel_timer("poll_timer")

    def heartbeat(self):
        ticks = []

        def tick():
            ticks.append(time.monotonic())
            if len(ticks) < 3:
                self.root.after(10, tick)

        self.root.after(10, tick)
        self.pump_until(lambda: len(ticks) == 3)
        return ticks

    def enter_debug(self, link=None, page="remote_page"):
        link = self.connect(link)
        self.app._enable_debug()
        self.settled("DEBUG")
        self.app.view.tabs.select(getattr(self.app.view, page))
        self.root.update()
        return link

    def key(self, keysym, *, widget=None, state=0, release=False):
        event = SimpleNamespace(keysym=keysym, widget=widget or self.root, state=state)
        return (self.app._key_release if release else self.app._key_press)(event)

    def finish_requests(self, state="DEBUG"):
        # Motion requests do not set _pending, so use a queued barrier before
        # reading simulator fields that change after command dispatch.
        self.app._queue("probe", lambda client: client.status())
        self.settled(state)

    def wait_interval(self, milliseconds=250):
        elapsed = []
        self.root.after(milliseconds, lambda: elapsed.append(True))
        self.pump_until(lambda: bool(elapsed))

    def show_invisible_window(self):
        """Map a transparent test window so Tcl can hold real native focus."""
        self.root.attributes("-alpha", 0)
        self.root.deiconify()
        self.root.focus_force()
        self.root.update()

    def focus_combobox_popup(self):
        combo = self.app.view.transport_picker
        popup = str(self.root.tk.call("ttk::combobox::PopdownWindow", str(combo)))
        self.root.tk.call("wm", "attributes", popup, "-alpha", 0)
        self.root.tk.call("wm", "deiconify", popup)
        path = popup + ".f.l"
        self.root.tk.call("focus", "-force", path)
        self.root.update()
        self.assertEqual(str(self.root.tk.call("focus", "-displayof", str(self.root))), path)
        return path

    def test_simulation_initializes_view_and_disconnect_clears_session(self):
        link = self.connect()
        self.assertTrue(self.app.simulated)
        self.assertEqual(self.app.state.get(), "待机")
        self.assertEqual([var.get() for var in self.app.ranges], ["500"] * 3)
        self.assertEqual(self.app.pid_vars[0].get(), "27.000")
        self.assertEqual(self.app.view.sensor_strip.bits, 24)
        self.assertTrue(self.app.view.speed_chart.samples)
        self.assertFalse(self.app.view.buttons["arm"].instate(["disabled"]))
        self.assertTrue(any("PONG 2" in line for line in self.app._logs))
        generation = self.app.generation

        self.app._disconnect()
        self.pump_until(link.closed.is_set)
        self.assertGreater(self.app.generation, generation)
        self.assertFalse(self.app.connected or self.app.connecting or self.app.ready or self.app.simulated)
        self.assertEqual(self.app.last_state, "")
        self.assertEqual(self.app._pending, set())
        self.assertIsNone(self.app.poll_timer)
        self.assertIsNone(self.app.drive_timer)
        self.assertEqual([var.get() for var in self.app.ranges], ["—"] * 3)
        self.assertTrue(all(var.get() == "—" for var in self.app.pid_vars))
        self.assertIsNone(self.app.view.sensor_strip.bits)
        self.assertFalse(self.app.view.speed_chart.samples)
        self.assertTrue(self.app.view.buttons["arm"].instate(["disabled"]))

    def test_slow_connection_keeps_tk_processing_events(self):
        entered, release = threading.Event(), threading.Event()
        self.gates.append(release)
        link = GuiLink()
        self.links.append(link)

        def factory(progress):
            entered.set()
            progress("waiting for simulated adapter")
            if not release.wait(5):
                raise TimeoutError("GUI factory test gate timed out")
            return link

        self.app._start_connection(factory, "slow simulation", simulated=True)
        self.pump_until(entered.is_set)
        self.heartbeat()
        self.assertTrue(self.app.connecting)
        self.assertFalse(self.app.connected)
        release.set()
        self.pump_until(lambda: self.app.connected and self.app.ready and not self.app._pending)

    def test_port_refresh_prefers_ch340_usb_and_retains_valid_selection(self):
        ports = [
            SimpleNamespace(device="COM3", description="标准串行蓝牙链路", hwid="BTHENUM\\DEV_01"),
            SimpleNamespace(device="COM7", description="FT232 USB UART", hwid="USB VID:PID=0403:6001"),
            SimpleNamespace(device="COM11", description="USB-SERIAL CH340", hwid="USB VID:PID=1A86:7523"),
            SimpleNamespace(device="COM1", description="Communications Port", hwid="ACPI\\PNP0501"),
        ]
        with patch("serial.tools.list_ports.comports", return_value=ports):
            self.app._refresh_ports()
            self.assertEqual(self.app.view.port_picker.cget("values"), ("COM11", "COM7", "COM1", "COM3"))
            self.assertEqual(self.app.port.get(), "COM11")
            self.assertIn("USB-SERIAL CH340", self.app.port_hint.get())
            self.assertIn("9600 bps · 8N1", self.app.port_hint.get())

            # An intentional existing Bluetooth selection must not be silently
            # replaced merely because a USB adapter has higher default priority.
            self.app.port.set("com3")
            self.app._refresh_ports()
            self.assertEqual(self.app.port.get(), "COM3")
            self.assertIn("标准串行蓝牙链路", self.app.port_hint.get())
            self.app.transport.set("旧 BT24 BLE")
            self.app.view.transport_picker.event_generate("<<ComboboxSelected>>")
            self.root.update()
            self.assertIn("可选 BLE", self.app.port_hint.get())
            self.app.transport.set("USB 串口 / JDY-31")
            self.app.view.transport_picker.event_generate("<<ComboboxSelected>>")
            self.root.update()
            self.assertIn("COM3 · 标准串行蓝牙链路", self.app.port_hint.get())

        with patch("serial.tools.list_ports.comports", return_value=ports[1:]):
            self.app._refresh_ports()
        self.assertEqual(self.app.port.get(), "COM11")
        with patch("serial.tools.list_ports.comports", return_value=[]):
            self.app._refresh_ports()
        self.assertEqual(self.app.port.get(), "")
        self.assertEqual(self.app.view.port_picker.cget("values"), "")
        self.assertIn("未检测到 COM", self.app.port_hint.get())

    def test_serial_connection_logs_actual_port_open_and_pong_handshake_separately(self):
        link = GuiLink()
        link.block_command = "PING"
        self.links.append(link)
        self.app.port.set("com7")
        with patch("host.gui.SerialLink", return_value=link) as serial_link:
            self.app._connect_serial()
            self.pump_until(lambda: link.blocked.is_set() and
                            any("串口 COM7 已打开" in line for line in self.app._logs))
            serial_link.assert_called_once_with("COM7")
            self.assertTrue(self.app.connecting)
            self.assertFalse(self.app.connected)
            logs = list(self.app._logs)
            opening = next(i for i, line in enumerate(logs) if "正在打开串口 COM7" in line)
            opened = next(i for i, line in enumerate(logs) if "串口 COM7 已打开" in line)
            self.assertLess(opening, opened)
            self.assertIn("9600 bps · 8N1 · DTR/RTS 关闭", logs[opening])
            self.assertFalse(any("固件握手通过" in line for line in logs))
            link.release.set()
            self.pump_until(lambda: self.app.connected and self.app.ready and
                            self.app.last_state == "IDLE" and not self.app._pending)
        self.app._cancel_timer("poll_timer")
        self.assertEqual(self.app.connection.get(), "● COM7")
        self.assertTrue(any("固件握手通过：PONG 2 · COM7" in line for line in self.app._logs))

    def test_serial_open_failure_does_not_report_open_or_handshake_success(self):
        self.app.port.set("COM8")
        with patch("host.gui.SerialLink", side_effect=OSError("port busy")):
            self.app._connect_serial()
            self.pump_until(lambda: not self.app.connecting and "port busy" in self.app.notice.get())
        self.assertFalse(self.app.connected)
        self.assertTrue(any("正在打开串口 COM8" in line for line in self.app._logs))
        self.assertFalse(any("已打开" in line or "固件握手通过" in line for line in self.app._logs))

    def test_serial_handshake_timeout_reports_open_port_without_claiming_connection(self):
        link = GuiLink()
        self.links.append(link)
        self.app.port.set("COM9")
        with patch("host.gui.SerialLink", return_value=link), \
                patch.object(link, "request", side_effect=TimeoutError("没有收到 PONG 2")):
            self.app._connect_serial()
            self.pump_until(lambda: not self.app.connecting and "没有收到 PONG 2" in self.app.notice.get())
        self.assertTrue(link.closed.is_set())
        self.assertFalse(self.app.connected)
        self.assertTrue(any("串口 COM9 已打开" in line for line in self.app._logs))
        self.assertFalse(any("固件握手通过" in line for line in self.app._logs))

    def test_slow_telemetry_keeps_tk_processing_events(self):
        link = self.connect()
        link.block_command = "STATUS?"
        self.app._refresh()
        self.pump_until(link.blocked.is_set)
        self.heartbeat()
        self.assertIn("telemetry", self.app._pending)
        self.assertTrue(self.app.connected)
        link.release.set()
        self.settled()

    def test_debug_hold_sends_drive_and_release_returns_motors_to_zero(self):
        link = self.connect()
        self.app._command("debug")
        self.settled("DEBUG")
        self.app.drive_left.set(18)
        self.app.drive_right.set(-6)
        self.app.drive_steer.set(1570)
        self.app._drive_press()
        self.pump_until(lambda: "DRIVE 180 -60 1570" in link.commands)
        self.assertTrue(self.app._holding)
        self.assertIsNotNone(self.app.drive_timer)

        self.app._drive_release()
        self.pump_until(lambda: "DRIVE 0 0 1500" in link.commands)
        # A command is recorded at dispatch; wait for an operation after it to
        # finish before reading the simulator's resulting motor state.
        self.app._queue("probe", lambda client: client.status())
        self.settled("DEBUG")
        self.assertFalse(self.app._holding)
        self.assertIsNone(self.app.drive_timer)
        self.assertEqual(link.state, "DEBUG")
        self.assertEqual((link.motor_left, link.motor_right, link.steer_us), (0, 0, 1500))
        self.assertLess(link.commands.index("DRIVE 180 -60 1570"),
                        link.commands.index("DRIVE 0 0 1500"))

    def test_focus_loss_stops_held_drive_and_cancels_repeated_drive_timer(self):
        link = self.connect()
        self.app._command("debug")
        self.settled("DEBUG")
        self.app.drive_left.set(14)
        self.app.drive_right.set(16)
        self.app.drive_steer.set(1540)
        self.app._drive_press()
        demand = "DRIVE 140 160 1540"
        self.pump_until(lambda: demand in link.commands)
        self.assertTrue(self.app._holding)
        self.assertIsNotNone(self.app.drive_timer)

        self.root.tk.call("focus", "")
        self.app._focus_out()
        self.pump_until(lambda: not self.app._holding and "DRIVE 0 0 1500" in link.commands)
        self.assertIsNone(self.app.drive_timer)
        self.app._queue("probe", lambda client: client.status())
        self.settled("DEBUG")
        self.assertEqual((link.motor_left, link.motor_right, link.steer_us), (0, 0, 1500))

        # Run past the original 200 ms repetition interval. Cancellation must
        # prevent a stale scheduled callback from restoring the old demand.
        sent_demands = link.commands.count(demand)
        interval_elapsed = []
        self.root.after(250, lambda: interval_elapsed.append(True))
        self.pump_until(lambda: bool(interval_elapsed))
        self.assertEqual(link.commands.count(demand), sent_demands)
        self.assertFalse(self.app._holding)
        self.assertIsNone(self.app.drive_timer)

    def test_old_firmware_hardware_query_keeps_connection_and_disables_motion(self):
        link = self.connect(GuiLink("ERR COMMAND"), ready=False)
        self.assertTrue(self.app.connected)
        self.assertIn("旧固件不支持", self.app.hardware_info.get())
        self.assertTrue(self.app.view.buttons["arm"].instate(["disabled"]))
        self.assertTrue(self.app.view.buttons["debug"].instate(["disabled"]))
        self.assertIn("HW?", link.commands)
        self.assertFalse(link.closed.is_set())

    def test_stop_cancels_queued_arm_and_resets_pending_controls(self):
        link = self.connect()
        link.block_command = "STATUS?"
        self.app._refresh()
        self.pump_until(link.blocked.is_set)
        self.app._command("arm")
        self.assertIn("mode", self.app._pending)
        self.assertTrue(self.app._stop())
        link.release.set()
        self.settled()
        self.assertIn("STOP", link.commands)
        self.assertNotIn("AUTO ARM", link.commands)
        self.assertEqual(link.state, "IDLE")
        self.assertFalse(self.app.view.buttons["arm"].instate(["disabled"]))
        self.assertEqual(self.app._pending, set())

    def test_pid_modification_is_disabled_until_hardware_is_ready(self):
        link = self.connect(GuiLink("HW 0 CLOCK"), ready=False)
        self.app.pid_vars[0].set("35")
        self.app._apply_pid(0)
        self.assertEqual(self.app._pending, set())
        self.assertFalse(any(command.startswith("PID SET") for command in link.commands))
        self.assertTrue(self.app.view.buttons["pid:line_kp"].instate(["disabled"]))
        self.assertTrue(self.app.view.buttons["pid_save"].instate(["disabled"]))
        self.assertTrue(all(widget.instate(["disabled"]) for widget in self.app.view.pid_inputs))
        self.assertIn("硬件正常", self.app.notice.get())

    def test_pid_modification_requires_idle_and_reads_back_successful_changes(self):
        link = self.connect()
        self.app._command("debug")
        self.settled("DEBUG")
        self.app.pid_vars[0].set("35")
        self.app._apply_pid(0)
        self.assertFalse(any(command.startswith("PID SET") for command in link.commands))
        self.assertEqual(self.app._pending, set())
        self.assertTrue(self.app.view.buttons["pid:line_kp"].instate(["disabled"]))

        self.app._stop()
        self.settled()
        self.app.pid_vars[0].set("35")
        self.app._apply_pid(0)
        self.settled()
        self.assertIn("PID SET line_kp 35.000", link.commands)
        self.assertEqual(link.pid_values["line_kp"], 35)
        self.assertEqual(self.app.pid_vars[0].get(), "35.000")

    def test_simulation_inputs_update_real_protocol_fields_and_line_diagnostics(self):
        link = self.connect()
        self.app.sim_line.set("10000001")
        for variable, value in zip(self.app.sim_ranges, (123, 456, 789)):
            variable.set(value)
        self.app._apply_sim()
        self.settled()
        self.assertEqual([var.get() for var in self.app.ranges], ["123", "456", "789"])
        self.assertEqual(self.app.view.sensor_strip.bits, 129)
        self.app._read_line()
        self.settled()
        self.assertIn("LINE?", link.commands)
        self.assertIn("OUT 01111110", self.app.line_info.get())

    def test_remote_forward_reverse_and_steering_send_bounded_pwm(self):
        link = self.enter_debug()
        self.app.remote_pwm.set(300)
        self.app.remote_turn.set(200)
        for direction, command in (
                ((1, 0), "DRIVE 300 300 1500"),
                ((-1, 0), "DRIVE -300 -300 1500"),
                ((1, -1), "DRIVE 300 300 1300"),
                ((-1, 1), "DRIVE -300 -300 1700")):
            with self.subTest(direction=direction):
                self.app._remote_press(direction)
                self.pump_until(lambda: command in link.commands)
                self.assertEqual(self.app._motion_source, "remote")
                self.app._drive_release()
                self.finish_requests()
                self.assertEqual((link.motor_left, link.motor_right, link.steer_us), (0, 0, 1500))
                self.assertFalse(self.app._holding)
                self.assertIsNone(self.app.drive_timer)

    def test_invalid_remote_values_never_send_nonzero_motion(self):
        link = self.enter_debug()
        for pwm, turn in ((301, 120), (-1, 120), (120, 1001), (120, -1), ("bad", 120)):
            with self.subTest(pwm=pwm, turn=turn):
                previous = len(link.commands)
                self.app.remote_pwm.set(pwm)
                self.app.remote_turn.set(turn)
                self.app._remote_press((1, 1))
                self.finish_requests()
                drives = [command for command in link.commands[previous:] if command.startswith("DRIVE ")]
                self.assertTrue(all(command == "DRIVE 0 0 1500" for command in drives))
                self.assertFalse(self.app._holding)
                self.assertIsNone(self.app.drive_timer)

    def test_remote_focus_loss_cancels_repeats_and_stops(self):
        link = self.enter_debug()
        self.app._remote_press((1, -1))
        command = "DRIVE 120 120 1380"
        self.pump_until(lambda: command in link.commands)
        self.root.tk.call("focus", "")
        self.app._focus_out()
        self.pump_until(lambda: not self.app._holding and "DRIVE 0 0 1500" in link.commands)
        self.finish_requests()
        sent = link.commands.count(command)
        self.wait_interval()
        self.assertEqual(link.commands.count(command), sent)
        self.assertEqual((link.motor_left, link.motor_right), (0, 0))
        self.assertIsNone(self.app.drive_timer)

    def test_native_combobox_popup_keeps_focus_check_and_connection_alive(self):
        link = self.enter_debug()
        self.show_invisible_window()
        self.app._remote_press((1, -1))
        demand = "DRIVE 120 120 1380"
        self.pump_until(lambda: demand in link.commands)
        path = self.focus_combobox_popup()
        # Reproduce the actual native Tcl focus that broke the Python wrapper.
        with self.assertRaises(KeyError):
            self.root.focus_displayof()
        self.assertEqual(self.app._widget_class(path), "Listbox")
        self.app._focus_out()
        self.root.update()
        self.assertEqual(self.callback_errors, [])
        self.assertTrue(self.app._holding)
        self.assertTrue(self.app.connected)
        self.finish_requests()
        self.assertEqual((link.motor_left, link.motor_right, link.steer_us), (120, 120, 1380))
        self.app._drive_release()
        self.finish_requests()
        self.assertEqual((link.motor_left, link.motor_right, link.steer_us), (0, 0, 1500))

    def test_keyboard_ignores_native_popup_and_destroyed_widget_paths(self):
        link = self.enter_debug()
        self.show_invisible_window()
        path = self.focus_combobox_popup()
        before = len(link.commands)
        for widget in (path, str(self.app.view.transport_picker) + ".destroyed"):
            for key in ("w", "Up", "space"):
                self.assertIsNone(self.key(key, widget=widget))
        self.wait_interval(50)
        self.assertFalse(self.app._holding)
        self.assertEqual(link.commands[before:], [])

    def test_focus_in_another_toplevel_stops_keyboard_motion_without_restarting(self):
        link = self.enter_debug()
        self.show_invisible_window()
        self.key("w")
        demand = "DRIVE 120 120 1500"
        self.pump_until(lambda: demand in link.commands)
        other = tk.Toplevel(self.root)
        other.attributes("-alpha", 0)
        entry = tk.Entry(other)
        entry.pack()
        self.root.update()
        entry.focus_force()
        self.root.update()
        self.assertEqual(str(self.root.tk.call("focus", "-displayof", str(self.root))), str(entry))
        self.app._focus_out()
        self.pump_until(lambda: not self.app._holding and "DRIVE 0 0 1500" in link.commands)
        self.finish_requests()
        self.assertEqual((link.motor_left, link.motor_right, link.steer_us), (0, 0, 1500))
        self.assertIsNone(self.app.drive_timer)
        self.assertIn("w", self.app._blocked_keys)
        sent = link.commands.count(demand)
        self.root.focus_force()
        self.root.update()
        self.key("w")
        self.wait_interval()
        self.assertEqual(link.commands.count(demand), sent)
        self.assertFalse(self.app._holding)

    def test_leaving_remote_or_speed_tab_stops_held_motion(self):
        link = self.enter_debug()
        for page, start, demand in (
                (self.app.view.remote_page, lambda: self.app._remote_press((1, 0)), "DRIVE 120 120 1500"),
                (self.app.view.pid_page, self.app._speed_press, "SPEED 20.000 20.000")):
            with self.subTest(page=str(page)):
                self.app.view.tabs.select(page)
                self.root.update()
                start()
                self.pump_until(lambda: demand in link.commands)
                self.app.view.tabs.select(self.app.view.debug_page)
                self.pump_until(lambda: not self.app._holding)
                self.finish_requests()
                self.assertEqual((link.motor_left, link.motor_right, link.steer_us), (0, 0, 1500))
                self.assertIsNone(self.app.drive_timer)
                sent = link.commands.count(demand)
                self.wait_interval()
                self.assertEqual(link.commands.count(demand), sent)

    def test_remote_keyboard_combines_w_and_arrow_then_releases_each_axis(self):
        link = self.enter_debug()
        self.assertEqual(self.key("w"), "break")
        self.pump_until(lambda: "DRIVE 120 120 1500" in link.commands)
        self.assertEqual(self.key("Right"), "break")
        self.pump_until(lambda: "DRIVE 120 120 1620" in link.commands)
        self.assertEqual(self.app._remote_direction, (1, 1))

        self.key("Right", release=True)
        self.pump_until(lambda: self.app._remote_direction == (1, 0))
        self.finish_requests()
        self.assertEqual((link.motor_left, link.motor_right, link.steer_us), (120, 120, 1500))
        self.key("w", release=True)
        self.pump_until(lambda: not self.app._holding)
        self.finish_requests()
        self.assertEqual((link.motor_left, link.motor_right, link.steer_us), (0, 0, 1500))

    def test_keyboard_is_ignored_in_text_input_other_tabs_and_with_modifiers(self):
        link = self.enter_debug()
        entry = tk.Entry(self.root)
        spinbox = tk.Spinbox(self.root)
        text = tk.Text(self.root)
        before = len(link.commands)
        for widget in (entry, spinbox, text, self.app.view.command_entry):
            for key in ("w", "Up", "space"):
                self.assertIsNone(self.key(key, widget=widget))
        for state in (0x0004, 0x0008):
            self.assertIsNone(self.key("w", state=state))
        self.app.view.tabs.select(self.app.view.pid_page)
        self.root.update()
        self.assertIsNone(self.key("Up"))
        self.wait_interval(50)
        self.assertFalse(self.app._holding)
        self.assertEqual(link.commands[before:], [])

    def test_space_brake_blocks_held_key_autorepeat_until_release(self):
        link = self.enter_debug()
        demand = "DRIVE 120 120 1500"
        self.key("w")
        self.pump_until(lambda: demand in link.commands)
        self.assertEqual(self.key("space"), "break")
        self.pump_until(lambda: "DRIVE 0 0 1500" in link.commands)
        self.finish_requests()
        sent = link.commands.count(demand)
        for _ in range(4):
            self.key("w")
        self.wait_interval()
        self.assertEqual(link.commands.count(demand), sent)
        self.assertFalse(self.app._holding)
        self.assertIn("w", self.app._blocked_keys)

        self.key("w", release=True)
        self.pump_until(lambda: "w" not in self.app._blocked_keys)
        self.key("w")
        self.pump_until(lambda: link.commands.count(demand) > sent)
        self.assertTrue(self.app._holding)
        self.app._drive_release()

    def test_stop_pending_behind_telemetry_cannot_restart_from_held_key(self):
        link = self.enter_debug()
        demand = "DRIVE 120 120 1500"
        self.key("w")
        self.pump_until(lambda: demand in link.commands)
        link.block_command = "STATUS?"
        self.app._refresh()
        self.pump_until(link.blocked.is_set)
        sent = link.commands.count(demand)
        # Exercise the same handler bound to Esc while the worker is awaiting
        # a reply. Repeated key presses must remain blocked before/after STOP.
        self.assertTrue(self.app._stop())
        self.assertIn("stop", self.app._pending)
        for _ in range(4):
            self.key("w")
        self.assertFalse(self.app._holding)
        self.assertIsNone(self.app.drive_timer)
        link.release.set()
        self.settled()
        self.key("w")
        self.wait_interval()
        self.assertEqual(link.commands.count(demand), sent)
        self.assertEqual(link.state, "IDLE")
        self.assertEqual((link.motor_left, link.motor_right), (0, 0))

    def test_speed_hold_uses_closed_loop_command_and_release_clears_targets(self):
        link = self.enter_debug(page="pid_page")
        self.app.test_left.set("15.25")
        self.app.test_right.set("22.5")
        self.app._speed_press()
        self.pump_until(lambda: "SPEED 15.250 22.500" in link.commands)
        self.finish_requests()
        self.assertEqual(self.app._motion_source, "speed")
        self.assertTrue(self.app._holding)
        self.assertEqual((link.left_target, link.right_target), (15.25, 22.5))
        self.assertTrue(link._speed_active)
        self.app._drive_release()
        self.finish_requests()
        self.assertEqual((link.left_target, link.right_target), (0, 0))
        self.assertEqual((link.motor_left, link.motor_right), (0, 0))
        self.assertFalse(link._speed_active)
        self.assertIsNone(self.app.drive_timer)

    def test_invalid_speed_input_never_sends_speed_command(self):
        link = self.enter_debug(page="pid_page")
        for left, right in (("bad", "20"), ("nan", "20"), ("inf", "20"),
                            ("-1", "20"), ("20", "501")):
            with self.subTest(left=left, right=right):
                previous = len(link.commands)
                self.app.test_left.set(left)
                self.app.test_right.set(right)
                self.app._speed_press()
                self.finish_requests()
                self.assertFalse(any(command.startswith("SPEED ") for command in link.commands[previous:]))
                self.assertFalse(self.app._holding)
                self.assertIsNone(self.app.drive_timer)

    def test_motor_tune_stops_motion_applies_five_values_and_remains_idle(self):
        link = self.enter_debug(page="pid_page")
        self.app._speed_press()
        self.pump_until(lambda: "SPEED 20.000 20.000" in link.commands)
        updates = ("4", "1.5", "0.1", "25", "220")
        for index, value in zip((3, 4, 5, 6, 7), updates):
            self.app.pid_vars[index].set(value)
        previous = len(link.commands)
        self.app._tune_motor_pid()
        self.assertFalse(self.app._holding)
        self.assertIsNone(self.app.drive_timer)
        self.settled()
        commands = link.commands[previous:]
        expected = ["STOP", "PID SET speed_kp 4.000", "PID SET speed_ki 1.500",
                    "PID SET speed_kd 0.100", "PID SET target_ticks 25.000",
                    "PID SET feedforward_pwm 220.000", "PID?", "PID STORE?"]
        self.assertEqual(commands[:len(expected)], expected)
        self.assertEqual([self.app.pid_vars[index].get() for index in (3, 4, 5, 6, 7)],
                         [f"{float(value):.3f}" for value in updates])
        self.assertEqual(link.state, "IDLE")
        self.assertEqual((link.motor_left, link.motor_right), (0, 0))
        self.assertFalse(self.app._holding)
        self.wait_interval()
        self.assertFalse(any(command.startswith(("DRIVE ", "SPEED ")) for command in link.commands[previous:]))

    def test_invalid_motor_tune_is_rejected_before_stop_or_parameter_writes(self):
        link = self.enter_debug(page="pid_page")
        for index, text in ((3, "bad"), (3, "51"), (4, "nan"), (5, "11"),
                            (6, "0"), (6, "0.0001"), (7, "501")):
            with self.subTest(index=index, value=text):
                old = self.app.pid_vars[index].get()
                self.app.pid_vars[index].set(text)
                previous = len(link.commands)
                self.app._tune_motor_pid()
                self.wait_interval(20)
                self.assertEqual(link.commands[previous:], [])
                self.assertEqual(self.app._pending, set())
                self.app.pid_vars[index].set(old)

    def test_telemetry_updates_shared_speed_values_and_all_three_charts(self):
        link = self.connect()
        self.assertEqual(len(self.app.view.speed_charts), 3)
        counts = [len(chart.samples) for chart in self.app.view.speed_charts]
        status = Status.parse("STAT DEBUG 0 24 500 500 500 13 17 0 111 222 1530")
        control = ControlStatus.parse("CTRL 0.50 13.25 17.75 20.50 25.50 111 222 1530")
        self.app._render_telemetry(status, control)
        self.assertEqual([v.get() for v in self.app.speed_targets], ["20.50", "25.50"])
        self.assertEqual([v.get() for v in self.app.speed_measured], ["13.25", "17.75"])
        self.assertEqual([v.get() for v in self.app.speed_pwm], ["+111", "+222"])
        for chart, before in zip(self.app.view.speed_charts, counts):
            self.assertEqual(len(chart.samples), before + 1)
            self.assertEqual(chart.samples[-1], (13.25, 17.75, 20.5, 25.5))
        self.app._disconnect()
        self.pump_until(link.closed.is_set)
        self.assertEqual([v.get() for v in self.app.speed_targets], ["—", "—"])
        self.assertEqual([v.get() for v in self.app.speed_measured], ["—", "—"])
        self.assertEqual([v.get() for v in self.app.speed_pwm], ["—", "—"])
        self.assertTrue(all(not chart.samples for chart in self.app.view.speed_charts))

    def test_pwm_unlock_reads_back_limit_and_percent_drive_stops_on_release(self):
        link = self.connect()
        self.app.pwm_limit_percent.set("80.5")
        self.app._unlock_pwm()
        self.settled("DEBUG")
        self.assertEqual(self.app.debug_pwm_limit, 805)
        self.assertIn("80.5%", self.app.pwm_limit_info.get())
        self.assertEqual((link.motor_left, link.motor_right), (0, 0))
        self.assertFalse(self.app._holding)
        self.assertEqual(float(self.app.view.drive_inputs[0].cget("to")), 80.5)
        self.app.drive_left.set(73.2)
        self.app.drive_right.set(0)
        self.app._drive_press()
        self.pump_until(lambda: "DRIVE 732 0 1500" in link.commands)
        self.app._drive_release()
        self.finish_requests()
        self.assertEqual((link.motor_left, link.motor_right), (0, 0))

    def test_locked_pwm_and_invalid_percentages_never_send_nonzero_drive(self):
        link = self.enter_debug(page="debug_page")
        for value in (30.1, 101, -101, float('nan'), float('inf')):
            with self.subTest(value=value):
                before = len(link.commands)
                self.app.drive_left.set(value)
                self.app.drive_right.set(0)
                self.app._drive_press()
                self.finish_requests()
                self.assertFalse(self.app._holding)
                self.assertFalse(any(c.startswith("DRIVE ") and c != "DRIVE 0 0 1500"
                                     for c in link.commands[before:]))

    def test_invalid_pwm_unlock_never_changes_mode_or_limit(self):
        link = self.connect()
        for value in ("bad", "nan", "inf", "0", "100.1", "-1"):
            with self.subTest(value=value):
                before = len(link.commands)
                self.app.pwm_limit_percent.set(value)
                self.app._unlock_pwm()
                self.wait_interval(20)
                self.assertEqual(link.commands[before:], [])
                self.assertEqual(self.app.debug_pwm_limit, 300)

    def test_pwm_unlock_is_disabled_while_holding_and_stop_relocks(self):
        link = self.connect()
        self.app._unlock_pwm()
        self.settled("DEBUG")
        self.app.view.tabs.select(self.app.view.debug_page)
        self.root.update()
        self.app.drive_left.set(40)
        self.app.drive_right.set(0)
        self.app._drive_press()
        self.pump_until(lambda: "DRIVE 400 0 1500" in link.commands)
        self.assertTrue(self.app.view.buttons['pwm_unlock'].instate(['disabled']))
        before = len(link.commands)
        self.app._unlock_pwm()
        self.assertFalse(any(c.startswith('DEBUG LIMIT ') for c in link.commands[before:]))
        self.app._stop()
        self.settled()
        self.assertEqual(self.app.debug_pwm_limit, 300)
        self.assertEqual((link.motor_left, link.motor_right), (0, 0))

    def test_old_firmware_never_appears_unlocked_and_keeps_low_pwm_working(self):
        class OldLimitLink(GuiLink):
            def request(self, command):
                if command == 'DEBUG LIMIT?':
                    return 'ERR COMMAND'
                return super().request(command)
        link = self.connect(OldLimitLink())
        self.assertFalse(self.app.pwm_limit_supported)
        self.assertIn('新版固件', self.app.pwm_limit_info.get())
        self.assertTrue(self.app.view.buttons['pwm_unlock'].instate(['disabled']))
        self.app._command('debug')
        self.settled('DEBUG')
        self.assertFalse(self.app.pwm_limit_supported)
        self.app.drive_left.set(12)
        self.app.drive_right.set(0)
        self.app._drive_press()
        self.pump_until(lambda: 'DRIVE 120 0 1500' in link.commands)
        self.app._drive_release()
        self.finish_requests()
        self.assertFalse(self.app.pwm_limit_supported)

    def test_watchdog_relock_is_read_from_board(self):
        link = self.connect()
        self.app._unlock_pwm()
        self.settled('DEBUG')
        self.app._queue('probe', lambda client: client.drive(500, 0, 1500))
        self.settled('DEBUG')
        time.sleep(.55)
        self.app._refresh()
        self.settled('DEBUG')
        self.assertEqual(self.app.debug_pwm_limit, 300)
        self.assertEqual((link.motor_left, link.motor_right), (0, 0))

    def test_servo_group_application_updates_actual_limits_and_independent_flash(self):
        link = self.connect()
        self.assertTrue(self.app.servo_supported)
        self.assertFalse(self.app.view.buttons["servo_apply"].instate(["disabled"]))
        self.app.servo_center.set("1630")
        self.app.servo_span.set("270")
        # Unapplied text must not change the current output or driver limits.
        self.assertEqual(self.app.servo_settings, ServoSettings())
        self.assertEqual(float(self.app.view.drive_inputs[2].cget("from")), 1300)
        self.app._apply_servo()
        self.settled()
        self.assertIn("SERVO SET 1630 270", link.commands)
        self.assertEqual(self.app.servo_settings, ServoSettings(1630, 270))
        self.assertEqual((float(self.app.view.drive_inputs[2].cget("from")),
                          float(self.app.view.drive_inputs[2].cget("to"))), (1360, 1900))
        self.assertEqual(float(self.app.view.remote_inputs[1].cget("to")), 270)
        self.assertEqual(self.app.drive_steer.get(), 1630)
        self.assertIn("1360 / 1630 / 1900 µs", self.app.servo_bounds_info.get())
        self.assertIn("1.360 / 1.630 / 1.900 ms", self.app.servo_bounds_info.get())
        self.assertIn("未保存", self.app.servo_flash_status.get())
        self.app._save_servo()
        self.settled()
        self.assertIn("已保存", self.app.servo_flash_status.get())
        self.assertIn("未保存", self.app.flash_status.get())
        self.app._reset_servo()
        self.settled()
        self.assertEqual(self.app.servo_settings, ServoSettings())
        self.app._restore_servo()
        self.settled()
        self.assertEqual(self.app.servo_settings, ServoSettings(1630, 270))
        link.reboot()
        self.app._read_servo()
        self.settled()
        self.assertEqual(self.app.drive_steer.get(), 1630)

    def test_invalid_servo_pair_never_sends_or_changes_actual_limits(self):
        link = self.connect()
        for center, span in (("500", "1"), ("2500", "1"), ("1500", "1001"),
                             ("nan", "200"), ("1500.0", "200"), ("1500", "-1")):
            with self.subTest(center=center, span=span):
                before = len(link.commands)
                self.app.servo_center.set(center)
                self.app.servo_span.set(span)
                self.app._apply_servo()
                self.wait_interval(20)
                self.assertEqual(link.commands[before:], [])
                self.assertEqual(self.app.servo_settings, ServoSettings())

    def test_servo_controls_require_idle_and_hardware_ready(self):
        link = self.enter_debug()
        self.app.servo_center.set("1600")
        self.app.servo_span.set("250")
        before = len(link.commands)
        for operation in (self.app._apply_servo, self.app._save_servo, self.app._restore_servo,
                          self.app._reset_servo):
            operation()
        self.assertFalse(any(command.startswith("SERVO SET ") for command in link.commands[before:]))
        for key in ("servo_apply", "servo_save", "servo_load", "servo_reset"):
            self.assertTrue(self.app.view.buttons[key].instate(["disabled"]))
        self.app._stop()
        self.settled()
        self.app.ready = False
        self.app._update_controls()
        self.assertTrue(self.app.view.buttons["servo_apply"].instate(["disabled"]))

    def test_nondefault_servo_bounds_remote_clamping_and_release_center(self):
        link = GuiLink()
        link.request("SERVO SET 1800 300")
        self.enter_debug(link)
        self.app.remote_turn.set(900)
        self.app._remote_press((1, 1))
        self.pump_until(lambda: "DRIVE 120 120 2100" in link.commands)
        self.app._drive_release()
        self.finish_requests()
        self.assertEqual((link.motor_left, link.motor_right, link.steer_us), (0, 0, 1800))
        self.app._remote_press((0, -1))
        self.pump_until(lambda: "DRIVE 0 0 1500" in link.commands)
        self.app._remote_brake()
        self.finish_requests()
        self.assertEqual(link.steer_us, 1800)
        # Filling endpoints only changes the input and never starts drive.
        self.app.view.tabs.select(self.app.view.debug_page)
        self.root.update()
        before = len(link.commands)
        self.app._fill_servo_pulse("right")
        self.assertEqual(self.app.drive_steer.get(), 2100)
        self.assertEqual(link.commands[before:], [])
        self.app.drive_left.set(0)
        self.app.drive_right.set(0)
        self.app.drive_steer.set(2101)
        self.app._drive_press()
        self.finish_requests()
        self.assertFalse(self.app._holding)
        self.assertNotIn("DRIVE 0 0 2101", link.commands)
        self.app._speed_press()
        self.finish_requests()
        self.assertEqual(link.steer_us, 1800)
        self.app._drive_release()
        self.finish_requests()

    def test_servo_zero_span_keeps_remote_and_manual_at_center(self):
        link = GuiLink()
        link.request("SERVO SET 1750 0")
        self.enter_debug(link)
        self.assertEqual(float(self.app.view.remote_inputs[1].cget("to")), 0)
        self.assertEqual(self.app.remote_turn.get(), 0)
        self.app.remote_turn.set(200)
        self.app._remote_press((1, -1))
        self.pump_until(lambda: "DRIVE 120 120 1750" in link.commands)
        self.app._drive_release()
        self.finish_requests()
        self.assertEqual(link.steer_us, 1750)

    def test_board_reboot_refreshes_unsaved_servo_cache_without_reconnecting(self):
        link = self.connect()
        generation = self.app.generation
        self.app.servo_center.set("1700")
        self.app.servo_span.set("100")
        self.app._apply_servo()
        self.settled()
        link.reboot()
        self.app._refresh()
        self.settled()
        self.assertEqual(self.app.generation, generation)
        self.assertEqual(self.app.servo_settings, ServoSettings())
        self.app._enable_debug()
        self.settled("DEBUG")
        self.app.view.tabs.select(self.app.view.remote_page)
        self.root.update()
        self.app._remote_press((1, 1))
        self.finish_requests()
        self.app._drive_release()
        self.finish_requests()
        self.assertEqual(link.steer_us, 1500)
        self.app._stop()
        self.settled()
        # A changed span with the same center is not visible in STATUS.
        self.app.servo_center.set("1500")
        self.app.servo_span.set("50")
        self.app._apply_servo()
        self.settled()
        link.reboot()
        self.app._command("debug")
        self.settled("DEBUG")
        self.assertEqual(self.app.servo_settings, ServoSettings())
        self.assertEqual(float(self.app.view.remote_inputs[1].cget("to")), 200)
        # Drive validation must also use the refreshed CarClient bounds.
        self.app._queue("probe", lambda client: client.drive(0, 0, 1700))
        self.settled("DEBUG")
        self.assertEqual(link.steer_us, 1700)
        self.app._remote_brake()
        self.finish_requests()
        self.assertEqual(link.steer_us, 1500)

    def test_old_servo_firmware_disables_calibration_and_uses_original_bounds(self):
        class OldServoLink(GuiLink):
            def request(self, command):
                if command in ("SERVO?", "SERVO STORE?"):
                    super().request(command)
                    return "ERR COMMAND"
                return super().request(command)
        link = self.connect(OldServoLink())
        self.assertFalse(self.app.servo_supported)
        self.assertIn("旧固件不支持", self.app.servo_flash_status.get())
        self.assertEqual(self.app.servo_settings, ServoSettings())
        self.assertTrue(self.app.view.buttons["servo_apply"].instate(["disabled"]))
        before = len(link.commands)
        self.app._apply_servo()
        self.assertFalse(any(command.startswith("SERVO SET ") for command in link.commands[before:]))
        self.app._enable_debug()
        self.settled("DEBUG")
        self.app.view.tabs.select(self.app.view.remote_page)
        self.root.update()
        self.app._remote_press((1, 1))
        self.pump_until(lambda: "DRIVE 120 120 1620" in link.commands)
        self.app._drive_release()
        self.finish_requests()
        self.assertEqual(link.steer_us, 1500)


if __name__ == "__main__":
    unittest.main()
