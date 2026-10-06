"""BT24 GATT transport; default channel matches BaudDance's generic type I."""

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import threading
from typing import Callable


SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
WRITE_UUID = NOTIFY_UUID
ALTERNATE_WRITE_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"


class BleLink:
    """Synchronous client interface backed by one persistent asyncio worker.

    Notifications can split or combine UART bytes. A timeout makes this connection
    unusable so a late response cannot acknowledge a subsequent motor command.
    """

    def __init__(self, target: str, *, service_uuid=SERVICE_UUID,
                 notify_uuid=NOTIFY_UUID, write_uuid=WRITE_UUID,
                 on_progress: Callable[[str], None] | None = None):
        if not target.strip():
            raise ValueError("请填写 BT24 的设备名称或蓝牙地址")
        self._target = target.strip()
        self._uuids = (service_uuid, notify_uuid, write_uuid)
        self._on_progress = on_progress
        self._stage = "加载蓝牙依赖"
        self.connection_details = {}
        self._client = None
        self._buffer = bytearray()
        self.received_byte_count = 0
        self._receive_preview = bytearray()
        self._pending = None
        self._error = None
        self._closed = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True, name="BT24")
        self._thread.start()
        try:
            self._submit(self._connect(), 55.0)
        except Exception as exc:
            self.close()
            raise ConnectionError(f"{self._stage}失败：{exc}") from exc
        except BaseException:
            self.close()
            raise

    def _report(self, stage, detail=""):
        self._stage = stage
        if self._on_progress:
            self._on_progress(stage + ("\n" + detail if detail else ""))

    def _run(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(self._loop)
            for task in tasks:
                task.cancel()
            if tasks:
                self._loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            self._loop.close()

    def _submit(self, coroutine, timeout):
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout)
        except FutureTimeout:
            # Built-in TimeoutError from the coroutine uses the same exception class.
            if future.done():
                raise
            future.cancel()
            raise TimeoutError("BLE 操作超时") from None

    async def _connect(self):
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as exc:
            raise RuntimeError("旧 BT24 BLE 工具需安装可选依赖：python -m pip install -r host/requirements-ble.txt") from exc
        self._report("扫描 BT24")
        target = self._target.casefold()
        device = await BleakScanner.find_device_by_filter(
            lambda dev, adv: dev.address.casefold() == target or
            (adv.local_name or "").casefold() == target or
            (dev.name or "").casefold() == target, timeout=12.0)
        if device is None:
            raise ConnectionError("未发现目标广播；请在网页助手/手机断开 BT24，并确认名称、地址和模块供电")
        self._report("连接 BT24 GATT", f"设备：{device.name or self._target}；地址：{device.address}")
        self._client = BleakClient(device, disconnected_callback=self._disconnected,
                                   timeout=30.0, winrt={"use_cached_services": False})
        await asyncio.wait_for(self._client.connect(), 30.0)
        self._report("检查透传服务")
        self.connection_details = {
            "name": device.name, "address": device.address,
            "services": [{"uuid": service.uuid,
                          "characteristics": [{"uuid": char.uuid, "properties": list(char.properties)}
                                              for char in service.characteristics]}
                         for service in self._client.services],
        }
        service = self._client.services.get_service(self._uuids[0])
        if service is None:
            available = ", ".join(item["uuid"] for item in self.connection_details["services"])
            raise ConnectionError(f"未找到服务 {self._uuids[0]}；实际服务：{available}")
        chars = {char.uuid.casefold(): char for char in service.characteristics}
        notify = chars.get(self._uuids[1].casefold())
        if notify is None or not {"notify", "indicate"}.intersection(notify.properties):
            raise ConnectionError(f"未找到可订阅的通知特征 {self._uuids[1]}；请核对网页助手的通知通道")
        self._write = chars.get(self._uuids[2].casefold())
        writable = {"write", "write-without-response"}
        if self._write is None or not writable.intersection(self._write.properties):
            # Older variants can have notify-only FFE1 and a separate writable FFE2.
            if self._uuids[2].casefold() == WRITE_UUID and self._uuids[1].casefold() == NOTIFY_UUID:
                self._write = chars.get(ALTERNATE_WRITE_UUID)
            if self._write is None or not writable.intersection(self._write.properties):
                available = "; ".join(f"{char.uuid}: {','.join(char.properties)}" for char in service.characteristics)
                raise ConnectionError(f"未找到可写透传特征 {self._uuids[2]}；实际特征：{available}")
        # Match the web assistant: prefer write without response when supported.
        self._write_response = "write-without-response" not in self._write.properties
        self._chunk_size = 20 if self._write_response else max(
            1, min(20, self._write.max_write_without_response_size))
        self._lock = asyncio.Lock()
        self._report("订阅 BT24 接收通知")
        await asyncio.wait_for(self._client.start_notify(notify, self._notification), 10.0)
        self.connection_details.update(service=service.uuid, notify=notify.uuid,
                                       write=self._write.uuid, write_response=self._write_response)
        self._report("BLE 透传已连接",
                     f"服务：{service.uuid}\n通知：{notify.uuid}\n写入：{self._write.uuid}；"
                     f"{'带响应' if self._write_response else '无响应'}写入")

    def _fail(self, error):
        self._error = error
        if self._pending is not None and not self._pending.done():
            self._pending.set_exception(error)

    def _disconnected(self, _client):
        self._fail(ConnectionError("BLE 连接已断开"))

    def _notification(self, _sender, data):
        self.received_byte_count += len(data)
        self._receive_preview.extend(data[:max(0, 96 - len(self._receive_preview))])
        for byte in data:
            if byte == 10:
                line = bytes(self._buffer).rstrip(b"\r")
                self._buffer.clear()
                if not line:
                    continue
                try:
                    response = line.decode("ascii", errors="strict")
                except UnicodeDecodeError:
                    self._fail(ValueError("BLE 响应必须是 ASCII"))
                    return
                if self._pending is None or self._pending.done():
                    self._fail(ConnectionError("收到未匹配的 BLE 响应，请重新连接"))
                    return
                self._pending.set_result(response)
            else:
                self._buffer.append(byte)
                if len(self._buffer) > 160:
                    self._buffer.clear()
                    self._fail(ValueError("BLE 响应超过 160 字节"))
                    return

    async def _request(self, command):
        async with self._lock:
            if self._error is not None:
                raise ConnectionError("BLE 会话失效，请重新连接") from self._error
            self._pending = self._loop.create_future()
            try:
                data = (command + "\n").encode("ascii")
                for offset in range(0, len(data), self._chunk_size):
                    await self._client.write_gatt_char(
                        self._write, data[offset:offset + self._chunk_size], response=self._write_response)
                try:
                    response = await asyncio.wait_for(self._pending,
                                                      5.0 if command in ("PID SAVE", "SERVO SAVE") else 2.0)
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(f"BLE 已连接，但 {command!r} 未收到完整行响应；"
                                       f"写入 {self._write.uuid}，接收 {self._uuids[1]}。"
                                       f"已收 {self.received_byte_count} 字节，未完成行 {bytes(self._buffer[:80])!r}。"
                                       "请检查固件、MCU 与模块 TX/RX、9600 8N1 和透传设置") from exc
                if self._error is not None or self._buffer:
                    raise ConnectionError("BLE 响应边界异常，请重新连接")
                return response
            except BaseException as exc:
                self._error = exc
                if not self._pending.done():
                    self._pending.cancel()
                raise
            finally:
                self._pending = None

    def request(self, command: str) -> str:
        if self._closed:
            raise ConnectionError("BLE 连接已关闭")
        if not command or not command.isascii() or any(c in command for c in "\r\n") or len(command) > 90:
            raise ValueError("BLE 命令必须是单行 ASCII，最多 90 字符")
        return self._submit(self._request(command), 7.0)

    def receive_diagnostics(self):
        return {"byte_count": self.received_byte_count,
                "preview_hex": self._receive_preview.hex(),
                "partial_line_hex": self._buffer.hex()}

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._client is not None:
                self._submit(self._client.disconnect(), 5.0)
        except Exception:
            pass
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=6.0)
