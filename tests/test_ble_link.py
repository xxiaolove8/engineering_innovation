import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from host.legacy.ble_link import (
    ALTERNATE_WRITE_UUID, BleLink, NOTIFY_UUID, SERVICE_UUID, WRITE_UUID,
)
from host.protocol import CarClient


class FakeServices:
    def __init__(self, services):
        self._services = services

    def __iter__(self):
        return iter(self._services)

    def get_service(self, uuid):
        return next((service for service in self._services if service.uuid == uuid), None)


class FakeClient:
    instances = []
    fail_connect = False
    fail_notify = False
    no_service = False
    alternate_present = True
    notify_properties = ["notify", "write", "write-without-response"]
    alternate_properties = ["write-without-response"]
    uart_write_uuid = NOTIFY_UUID
    max_write_size = 20

    def __init__(self, device, disconnected_callback, timeout, winrt):
        self.device = device
        self.timeout = timeout
        self.winrt = winrt
        self.callback = disconnected_callback
        self.connected = False
        self.chunks = []
        self.data = bytearray()
        self.mode = "normal"
        self.uart_write_uuid = type(self).uart_write_uuid
        notify = SimpleNamespace(uuid=NOTIFY_UUID, properties=list(self.notify_properties),
                                 max_write_without_response_size=self.max_write_size)
        chars = [notify]
        if self.alternate_present:
            chars.append(SimpleNamespace(uuid=ALTERNATE_WRITE_UUID,
                                         properties=list(self.alternate_properties),
                                         max_write_without_response_size=self.max_write_size))
        self.services = FakeServices([
            SimpleNamespace(uuid="0000180f-0000-1000-8000-00805f9b34fb", characteristics=[]),
        ] + ([] if self.no_service else [SimpleNamespace(uuid=SERVICE_UUID, characteristics=chars)]))
        self.instances.append(self)

    async def connect(self):
        self.connected = True
        if self.fail_connect:
            raise ConnectionError("connect failed")

    async def disconnect(self):
        self.connected = False
        self.callback(self)

    async def start_notify(self, char, callback):
        if self.fail_notify:
            raise ConnectionError("subscribe failed")
        self.notify_char = char
        self.notify = callback

    async def write_gatt_char(self, char, data, response):
        self.chunks.append((char.uuid, bytes(data), response))
        required_property = "write" if response else "write-without-response"
        if required_property not in char.properties:
            raise ConnectionError("unsupported GATT write mode")
        if char.uuid != self.uart_write_uuid:
            return  # This GATT characteristic is writable, but is not the UART channel.
        self.data.extend(data)
        if self.data.endswith(b"\n"):
            command = bytes(self.data).decode("ascii").strip()
            self.data.clear()
            if self.mode == "disconnect":
                self.callback(self)
                return
            if self.mode == "timeout":
                raise asyncio.TimeoutError("late reply")
            if self.mode == "silent":
                return
            if self.mode == "overflow":
                self.notify(None, b"X" * 161)
                return
            if self.mode == "extra":
                self.notify(None, b"OK\nOK\n")
                return
            if self.mode == "nonascii":
                self.notify(None, b"\xff\n")
                return
            if self.mode == "v1":
                self.notify(None, b"PONG 1\n")
                return
            payload = b"PONG 2\r\n" if command == "PING" else b"OK\r\n"
            for offset in range(0, len(payload), 2):
                self.notify(None, payload[offset:offset+2])


class FakeScanner:
    device_name = "BT24"
    local_name = "BT24"
    not_found = False

    @staticmethod
    async def find_device_by_filter(predicate, timeout):
        dev = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name=FakeScanner.device_name)
        adv = SimpleNamespace(local_name=FakeScanner.local_name)
        return dev if not FakeScanner.not_found and predicate(dev, adv) else None


class BleTests(unittest.TestCase):
    def setUp(self):
        FakeClient.instances.clear()
        FakeClient.fail_connect = FakeClient.fail_notify = FakeClient.no_service = False
        FakeClient.alternate_present = True
        FakeClient.notify_properties = ["notify", "write", "write-without-response"]
        FakeClient.alternate_properties = ["write-without-response"]
        FakeClient.uart_write_uuid = NOTIFY_UUID
        FakeClient.max_write_size = 20
        FakeScanner.device_name = FakeScanner.local_name = "BT24"
        FakeScanner.not_found = False
        self.backend = patch.dict("sys.modules", {"bleak": SimpleNamespace(BleakClient=FakeClient, BleakScanner=FakeScanner)})
        self.backend.start()
        self.links = []

    def tearDown(self):
        for link in self.links:
            link.close()
            self.assertFalse(link._thread.is_alive())
        self.backend.stop()

    def link(self, target="BT24", **kwargs):
        link = BleLink(target, **kwargs)
        self.links.append(link)
        return link

    def test_handshake_fragments_and_write_chunking(self):
        link = self.link("aa:bb:cc:dd:ee:ff")
        client = CarClient(link)
        client.set_pid("differential_gain", .35)
        fake = FakeClient.instances[-1]
        self.assertTrue(all(uuid == WRITE_UUID and len(data) <= 20 and not response
                            for uuid, data, response in fake.chunks))
        self.assertGreater(len(fake.chunks), 2)
        self.assertEqual(SERVICE_UUID[4:8], "ffe0")

    def test_bt24_uses_ffe1_when_both_characteristics_are_writable(self):
        link = self.link()
        CarClient(link)
        fake = FakeClient.instances[-1]
        self.assertEqual(WRITE_UUID, NOTIFY_UUID)
        self.assertEqual(NOTIFY_UUID[4:8], "ffe1")
        self.assertEqual(ALTERNATE_WRITE_UUID[4:8], "ffe2")
        self.assertEqual(fake.chunks, [(NOTIFY_UUID, b"PING\n", False)])

    def test_dual_write_properties_prefer_without_response_and_respect_size(self):
        FakeClient.max_write_size = 7
        link = self.link()
        self.assertEqual(link.request("PID SET differential_gain 0.35"), "OK")
        chunks = FakeClient.instances[-1].chunks
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(data) <= 7 and not response for _, data, response in chunks))
        self.assertEqual(b"".join(data for _, data, _ in chunks), b"PID SET differential_gain 0.35\n")

    def test_notify_only_ffe1_falls_back_to_writable_ffe2(self):
        FakeClient.notify_properties = ["notify"]
        FakeClient.uart_write_uuid = ALTERNATE_WRITE_UUID
        link = self.link()
        self.assertEqual(link.request("PING"), "PONG 2")
        fake = FakeClient.instances[-1]
        self.assertEqual(fake.chunks, [(ALTERNATE_WRITE_UUID, b"PING\n", False)])
        self.assertEqual(fake.notify_char.uuid, NOTIFY_UUID)
        self.assertEqual(link.connection_details["write"], ALTERNATE_WRITE_UUID)

    def test_write_only_property_uses_with_response(self):
        FakeClient.notify_properties = ["notify", "write"]
        FakeClient.alternate_present = False
        self.assertEqual(self.link().request("PING"), "PONG 2")
        self.assertEqual(FakeClient.instances[-1].chunks, [(NOTIFY_UUID, b"PING\n", True)])

    def test_explicit_ffe2_selects_requested_channel(self):
        FakeClient.uart_write_uuid = ALTERNATE_WRITE_UUID
        link = self.link(write_uuid=ALTERNATE_WRITE_UUID)
        self.assertEqual(link.request("PING"), "PONG 2")
        self.assertEqual(FakeClient.instances[-1].chunks, [(ALTERNATE_WRITE_UUID, b"PING\n", False)])

    def test_progress_and_connection_details_identify_selected_transport(self):
        progress = []
        link = self.link(on_progress=progress.append)
        self.assertEqual([entry.split("\n", 1)[0] for entry in progress], [
            "扫描 BT24", "连接 BT24 GATT", "检查透传服务", "订阅 BT24 接收通知", "BLE 透传已连接",
        ])
        details = link.connection_details
        self.assertEqual(details["name"], "BT24")
        self.assertEqual(details["address"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual((details["service"], details["notify"], details["write"]),
                         (SERVICE_UUID, NOTIFY_UUID, WRITE_UUID))
        self.assertFalse(details["write_response"])
        self.assertEqual(len(details["services"]), 2)
        self.assertEqual(details["services"][1]["characteristics"][0]["properties"],
                         ["notify", "write", "write-without-response"])
        fake = FakeClient.instances[-1]
        self.assertEqual(fake.timeout, 30.0)
        self.assertEqual(fake.winrt, {"use_cached_services": False})

    def test_device_name_matches_even_when_advertised_name_differs(self):
        FakeScanner.local_name = "DX-BT24"
        self.assertEqual(self.link("bt24").request("PING"), "PONG 2")

    def test_advertised_name_matches_even_when_device_name_differs(self):
        FakeScanner.device_name = "Windows Bluetooth Device"
        self.assertEqual(self.link("bt24").request("PING"), "PONG 2")

    def test_missing_writable_channel_reports_properties(self):
        FakeClient.notify_properties = ["notify"]
        FakeClient.alternate_properties = ["read"]
        with self.assertRaisesRegex(ConnectionError, "检查透传服务失败：.*未找到可写透传特征") as error:
            self.link()
        self.assertIn(ALTERNATE_WRITE_UUID, str(error.exception))
        self.assertIn("read", str(error.exception))
        self.assertFalse(FakeClient.instances[-1].connected)

    def test_explicit_missing_ffe2_does_not_silently_switch_to_ffe1(self):
        FakeClient.alternate_present = False
        with self.assertRaisesRegex(ConnectionError, "未找到可写透传特征"):
            self.link(write_uuid=ALTERNATE_WRITE_UUID)
        self.assertFalse(FakeClient.instances[-1].connected)

    def test_bad_reply_poisoned_connection(self):
        for mode in ("overflow", "extra", "nonascii", "timeout", "disconnect"):
            with self.subTest(mode=mode):
                link = self.link()
                FakeClient.instances[-1].mode = mode
                with self.assertRaises((ValueError, ConnectionError, TimeoutError)):
                    link.request("PING")
                with self.assertRaises(ConnectionError):
                    link.request("STOP")

    def test_v1_handshake_closes_transport(self):
        link = self.link()
        FakeClient.instances[-1].mode = "v1"
        with self.assertRaises(ConnectionError):
            CarClient(link)
        self.assertFalse(link._thread.is_alive())

    def test_failed_setup_disconnects(self):
        for flag, expected in (
            ("fail_connect", "连接 BT24 GATT失败：connect failed"),
            ("no_service", "检查透传服务失败：未找到服务"),
            ("fail_notify", "订阅 BT24 接收通知失败：subscribe failed"),
        ):
            with self.subTest(flag=flag):
                setattr(FakeClient, flag, True)
                with self.assertRaisesRegex(ConnectionError, expected):
                    self.link()
                self.assertFalse(FakeClient.instances[-1].connected)
                setattr(FakeClient, flag, False)

    def test_missing_device_reports_scan_stage_without_creating_client(self):
        FakeScanner.not_found = True
        progress = []
        with self.assertRaisesRegex(ConnectionError, "扫描 BT24失败：未发现目标广播"):
            self.link(on_progress=progress.append)
        self.assertEqual(progress, ["扫描 BT24"])
        self.assertEqual(FakeClient.instances, [])

    def test_input_and_close_guards(self):
        link = self.link()
        with self.assertRaises(ValueError):
            link.request("PING\nDRIVE 100 100 1500")
        link.close()
        link.close()
        with self.assertRaises(ConnectionError):
            link.request("PING")

    def test_response_timeout_rejects_late_ack(self):
        link = self.link()
        fake = FakeClient.instances[-1]
        fake.mode = "silent"
        with self.assertRaisesRegex(TimeoutError, "BLE 已连接.*未收到完整行响应") as error:
            link.request("DRIVE 100 100 1500")
        self.assertIn(WRITE_UUID, str(error.exception))
        self.assertIn("9600 8N1", str(error.exception))
        link._loop.call_soon_threadsafe(link._notification, None, b"OK\n")
        fake.mode = "normal"
        before = len(fake.chunks)
        with self.assertRaises(ConnectionError):
            link.request("DRIVE 0 0 1500")
        self.assertEqual(len(fake.chunks), before)


if __name__ == "__main__":
    unittest.main()
