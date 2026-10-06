"""Concurrency/lifecycle checks using links that never access real hardware."""

import queue
import threading
import unittest

from host.protocol import SimLink
from host.session import SessionWorker


class RecordingLink(SimLink):
    def __init__(self):
        super().__init__()
        self.commands = []
        self.thread_ids = []
        self.closed = threading.Event()
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.block_command = None
        self.failure_command = None
        self.failure = None
        self.close_started = threading.Event()
        self.close_release = None

    def request(self, command):
        self.commands.append(command)
        self.thread_ids.append(threading.get_ident())
        if command == self.block_command:
            self.blocked.set()
            if not self.release.wait(3):
                raise TimeoutError("test request gate timed out")
        if command == self.failure_command:
            raise self.failure
        if command == "BLOCK":
            return "OK"
        return super().request(command)

    def close(self):
        self.thread_ids.append(threading.get_ident())
        self.close_started.set()
        if self.close_release is not None and not self.close_release.wait(3):
            raise TimeoutError("test close gate timed out")
        self.closed.set()


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.worker = SessionWorker()
        self.links = []
        self.gates = []

    def tearDown(self):
        self.worker.shutdown()
        for gate in self.gates:
            gate.set()
        for link in self.links:
            link.release.set()
            if link.close_release is not None:
                link.close_release.set()
        self.worker.join(3)
        self.assertFalse(self.worker._thread.is_alive(), "session worker did not finish cleanup")

    def wait_event(self, kind, key=None, generation=None):
        for _ in range(100):
            try:
                event = self.worker.events.get(timeout=3)
            except queue.Empty:
                self.fail(f"missing {kind} event for {key}")
            if (event.kind == kind and (key is None or event.key == key) and
                    (generation is None or event.generation == generation)):
                return event
        self.fail(f"too many events before {kind}")

    def connect(self, link=None):
        link = link or RecordingLink()
        self.links.append(link)
        generation = self.worker.connect(lambda progress: link, "test car")
        event = self.wait_event("connected", generation=generation)
        self.assertEqual(event.data, "test car")
        return generation, link

    def complete(self, generation, key, operation):
        self.assertTrue(self.worker.request(generation, key, operation))
        return self.wait_event("result", key, generation).data

    def block(self, generation, link):
        link.block_command = "BLOCK"
        self.worker.request(generation, "block", lambda client: client.request("BLOCK"))
        self.assertTrue(link.blocked.wait(3))

    def test_factory_handshake_operations_and_close_share_one_background_thread(self):
        factory_threads = []
        link = RecordingLink()
        self.links.append(link)

        def factory(progress):
            factory_threads.append(threading.get_ident())
            progress("link ready")
            return link

        generation = self.worker.connect(factory, "test car")
        self.wait_event("progress", generation=generation)
        self.wait_event("connected", generation=generation)
        operation_threads = []

        def operation(client):
            operation_threads.append(threading.get_ident())
            return client.status(), client.control()

        status, control = self.complete(generation, "telemetry", operation)
        self.assertEqual(status.state, "IDLE")
        self.assertEqual(control.steer_us, 1500)
        disconnected = self.worker.disconnect()
        self.wait_event("disconnected", generation=disconnected)
        self.assertEqual(len(set(factory_threads + operation_threads + link.thread_ids)), 1)
        self.assertNotEqual(factory_threads[0], threading.get_ident())
        self.assertTrue(link.closed.is_set())

    def test_cancelled_factory_closes_late_link_without_handshake(self):
        entered, release = threading.Event(), threading.Event()
        self.gates.append(release)
        old_link, new_link = RecordingLink(), RecordingLink()
        self.links.extend((old_link, new_link))

        def slow_factory(progress):
            entered.set()
            self.assertTrue(release.wait(3))
            progress("obsolete progress")
            return old_link

        old_generation = self.worker.connect(slow_factory, "old")
        self.assertTrue(entered.wait(3))
        new_generation = self.worker.connect(lambda progress: new_link, "new")
        self.assertFalse(self.worker.request(old_generation, "obsolete", lambda client: client.status()))
        release.set()
        event = self.wait_event("connected", generation=new_generation)
        self.assertEqual(event.data, "new")
        self.assertTrue(old_link.closed.is_set())
        self.assertEqual(old_link.commands, [])
        self.assertEqual(new_link.commands, ["PING"])
        self.assertTrue(all(event.generation == new_generation for event in self.worker.drain()))

    def test_cancel_during_handshake_closes_client_and_suppresses_stale_result(self):
        link = RecordingLink()
        link.block_command = "PING"
        self.links.append(link)
        generation = self.worker.connect(lambda progress: link, "slow handshake")
        self.assertTrue(link.blocked.wait(3))
        self.worker.drain()
        cancelled = self.worker.disconnect()
        link.release.set()
        self.wait_event("disconnected", generation=cancelled)
        self.assertTrue(link.closed.is_set())
        self.assertFalse(any(event.generation == generation for event in self.worker.drain()))

    def test_stop_cancels_pending_commands_and_drives(self):
        generation, link = self.connect()
        self.complete(generation, "debug", lambda client: client.debug())
        self.block(generation, link)
        self.worker.request(generation, "drive", lambda client: client.drive(50, 50, 1500))
        self.worker.request(generation, "misc", lambda client: client.pid())
        self.worker.request(generation, "drive", lambda client: client.drive(100, 100, 1500))
        self.worker.request(generation, "stop", lambda client: client.stop())
        link.release.set()
        self.wait_event("result", "stop", generation)
        commands = link.commands[2:]
        self.assertEqual(commands, ["BLOCK", "STOP"])
        self.assertEqual(link.state, "IDLE")

    def test_stop_cancels_arm_queued_behind_active_telemetry(self):
        generation, link = self.connect()
        link.block_command = "STATUS?"
        self.worker.request(generation, "telemetry", lambda client: client.status())
        self.assertTrue(link.blocked.wait(3))
        self.worker.request(generation, "arm", lambda client: client.arm())
        self.worker.request(generation, "stop", lambda client: client.stop())
        link.release.set()
        self.wait_event("result", "stop", generation)
        self.assertEqual(self.complete(generation, "status", lambda client: client.status()).state, "IDLE")
        self.assertNotIn("AUTO ARM", link.commands)
        self.assertEqual(link.commands, ["PING", "STATUS?", "STOP", "STATUS?"])

    def test_tune_cancels_pending_motion_and_mode_after_active_telemetry(self):
        generation, link = self.connect()
        self.complete(generation, "mode", lambda client: client.debug())
        link.block_command = "STATUS?"
        self.worker.request(generation, "telemetry", lambda client: client.status())
        self.assertTrue(link.blocked.wait(3))
        self.worker.request(generation, "drive", lambda client: client.drive(100, 100, 1500))
        self.worker.request(generation, "mode", lambda client: client.debug())
        self.worker.request(generation, "raw", lambda client: client.request("AUTO ARM"))

        def apply_pid(client):
            client.stop()
            client.set_pid("speed_kp", 4.0)
            client.set_pid("speed_ki", 1.5)
            client.set_pid("speed_kd", 0.1)
            return client.pid()

        self.worker.request(generation, "tune", apply_pid, priority=True, cancel_drives=True)
        link.release.set()
        settings = self.wait_event("result", "tune", generation).data
        self.assertEqual(settings.values["speed_kp"], 4.0)
        self.assertEqual(settings.values["speed_ki"], 1.5)
        self.assertEqual(settings.values["speed_kd"], 0.1)
        self.assertEqual(link.commands, [
            "PING", "DEBUG", "STATUS?", "STOP", "PID SET speed_kp 4.000",
            "PID SET speed_ki 1.500", "PID SET speed_kd 0.100", "PID?",
        ])
        self.assertEqual(link.state, "IDLE")
        self.assertEqual((link.motor_left, link.motor_right), (0, 0))

    def test_drive_release_cancels_only_pending_drive_requests(self):
        generation, link = self.connect()
        self.complete(generation, "mode", lambda client: client.debug())
        self.block(generation, link)
        executed = []
        self.worker.request(generation, "drive", lambda client: client.drive(100, 100, 1500))
        self.worker.request(generation, "mode", lambda client: executed.append("mode"))
        self.worker.request(generation, "raw", lambda client: client.pid())
        self.worker.request(generation, "telemetry", lambda client: client.control())
        self.worker.request(generation, "drive", lambda client: client.drive(0, 0, 1500),
                            priority=True, cancel_drives=True)
        self.worker.request(generation, "done", lambda client: "done")
        link.release.set()
        self.wait_event("result", "done", generation)
        self.assertEqual(executed, ["mode"])
        self.assertEqual(link.commands, ["PING", "DEBUG", "BLOCK", "DRIVE 0 0 1500", "PID?", "CTRL?"])
        self.assertEqual(link.state, "DEBUG")

    def test_pwm_unlock_cancels_pending_motion_and_auto_start(self):
        generation, link = self.connect()
        self.block(generation, link)
        self.worker.request(generation, 'mode', lambda client: client.arm())
        self.worker.request(generation, 'drive', lambda client: client.drive(300, 0, 1500))
        def unlock(client):
            client.stop()
            client.debug()
            client.set_debug_limit(1000)
            return client.debug_limit()
        self.worker.request(generation, 'pwm_unlock', unlock)
        link.release.set()
        self.assertEqual(self.wait_event('result', 'pwm_unlock', generation).data, 1000)
        self.assertNotIn('AUTO ARM', link.commands)
        self.assertFalse(any(c.startswith('DRIVE ') for c in link.commands))
        self.assertEqual((link.motor_left, link.motor_right), (0, 0))

    def test_latest_tune_replaces_older_pending_tuning_transaction(self):
        generation, link = self.connect()
        self.complete(generation, "mode", lambda client: client.debug())
        self.block(generation, link)
        executed = []

        def tune(client, label, value):
            executed.append(label)
            client.stop()
            client.set_pid("speed_kp", value)
            return client.pid()

        self.worker.request(generation, "tune", lambda client: tune(client, "old", 4.0))
        self.worker.request(generation, "tune", lambda client: tune(client, "new", 5.0))
        link.release.set()
        settings = self.wait_event("result", "tune", generation).data
        self.assertEqual(executed, ["new"])
        self.assertEqual(settings.values["speed_kp"], 5.0)
        self.assertEqual(link.commands, ["PING", "DEBUG", "BLOCK", "STOP", "PID SET speed_kp 5.000", "PID?"])

    def test_telemetry_and_drive_backlogs_keep_only_latest_pending_operation(self):
        generation, link = self.connect()
        self.complete(generation, "debug", lambda client: client.debug())
        self.block(generation, link)
        executed = []
        for number in range(10):
            self.worker.request(generation, "telemetry", lambda client, n=number: executed.append(("telemetry", n)))
            self.worker.request(generation, "drive", lambda client, n=number: (
                executed.append(("drive", n)), client.drive(n, n, 1500)))
        self.worker.request(generation, "done", lambda client: "done")
        link.release.set()
        self.wait_event("result", "done", generation)
        self.assertEqual(executed, [("telemetry", 9), ("drive", 9)])
        self.assertEqual(sum(command.startswith("DRIVE") for command in link.commands), 1)

    def test_priority_request_does_not_overtake_queued_connection(self):
        generation, old_link = self.connect()
        self.block(generation, old_link)
        new_link = RecordingLink()
        self.links.append(new_link)
        generation = self.worker.connect(lambda progress: new_link, "replacement")
        self.worker.request(generation, "stop", lambda client: client.stop())
        old_link.release.set()
        self.wait_event("result", "stop", generation)
        self.assertEqual(new_link.commands, ["PING", "STOP"])
        self.assertTrue(old_link.closed.is_set())

    def test_tune_preserves_and_follows_queued_connection(self):
        generation, old_link = self.connect()
        self.block(generation, old_link)
        new_link = RecordingLink()
        self.links.append(new_link)
        generation = self.worker.connect(lambda progress: new_link, "replacement")
        self.worker.request(generation, "tune", lambda client: client.stop(),
                            priority=True, cancel_drives=True)
        old_link.release.set()
        self.wait_event("result", "tune", generation)
        self.assertEqual(new_link.commands, ["PING", "STOP"])
        self.assertTrue(old_link.closed.is_set())

    def test_validation_and_firmware_rejection_keep_the_connection_usable(self):
        generation, link = self.connect()
        self.complete(generation, "debug", lambda client: client.debug())
        for key, operation, error_type in (
                ("invalid", lambda client: client.drive(1001, 0, 1500), ValueError),
                ("locked", lambda client: client.drive(301, 0, 1500), RuntimeError),
                ("rejected", lambda client: client.arm(), RuntimeError)):
            self.worker.request(generation, key, operation)
            event = self.wait_event("error", key, generation)
            self.assertFalse(event.fatal)
            self.assertIsInstance(event.error, error_type)
        self.assertEqual(self.complete(generation, "status", lambda client: client.status()).state, "DEBUG")
        self.assertFalse(link.closed.is_set())

    def test_transport_errors_close_connection_and_cancel_pending_commands(self):
        for failure in (TimeoutError("no response"), ValueError("invalid transport bytes"),
                        RuntimeError("vendor transport error")):
            with self.subTest(failure=type(failure).__name__):
                generation, link = self.connect()
                self.block(generation, link)
                link.failure_command, link.failure = "FAIL", failure
                self.worker.request(generation, "failure", lambda client: client.request("FAIL"))
                self.worker.request(generation, "drive", lambda client: client.drive(100, 100, 1500))
                link.release.set()
                event = self.wait_event("error", "failure", generation)
                self.assertTrue(event.fatal)
                self.assertIs(event.error, failure)
                self.assertTrue(link.closed.is_set())
                self.assertFalse(any(command.startswith("DRIVE") for command in link.commands))

    def test_disconnect_debug_stops_but_auto_keeps_running(self):
        for mode, operation, expected_stop in (
                ("DEBUG", lambda client: client.debug(), True),
                ("ARMED", lambda client: client.arm(), False)):
            with self.subTest(mode=mode):
                generation, link = self.connect()
                self.complete(generation, "mode", operation)
                generation = self.worker.disconnect()
                self.wait_event("disconnected", generation=generation)
                self.assertEqual("STOP" in link.commands, expected_stop)
                self.assertEqual(link.state, "IDLE" if expected_stop else mode)

    def test_disconnect_does_not_wait_for_slow_close(self):
        generation, link = self.connect()
        link.close_release = threading.Event()
        cancelled = self.worker.disconnect()
        self.assertGreater(cancelled, generation)
        self.assertTrue(link.close_started.wait(3))
        self.assertFalse(link.closed.is_set())
        link.close_release.set()
        self.wait_event("disconnected", generation=cancelled)

    def test_shutdown_during_request_cancels_queue_and_closes_after_request_finishes(self):
        generation, link = self.connect()
        self.block(generation, link)
        self.worker.request(generation, "pending", lambda client: client.arm())
        self.worker.drain()
        shutdown_generation = self.worker.shutdown()
        self.assertGreater(shutdown_generation, generation)
        self.assertFalse(self.worker.request(shutdown_generation, "ignored", lambda client: client.stop()))
        link.release.set()
        self.worker.join(3)
        self.assertTrue(link.closed.is_set())
        self.assertEqual(link.commands, ["PING", "BLOCK"])
        self.assertEqual(self.worker.drain(), [])
        self.assertEqual(self.worker.shutdown(), shutdown_generation)
        with self.assertRaises(RuntimeError):
            self.worker.connect(lambda progress: RecordingLink(), "closed")

    def test_failed_handshake_is_fatal_and_releases_link(self):
        link = RecordingLink()
        link.failure_command, link.failure = "PING", TimeoutError("wrong port")
        self.links.append(link)
        generation = self.worker.connect(lambda progress: link, "no firmware")
        event = self.wait_event("error", "connect", generation)
        self.assertTrue(event.fatal)
        self.assertTrue(link.closed.is_set())


if __name__ == "__main__":
    unittest.main()
