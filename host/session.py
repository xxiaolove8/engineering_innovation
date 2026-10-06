"""Serialized, asynchronous car sessions for desktop front ends.

Only the worker thread owns links and CarClient instances. Front ends submit
operations and drain events; neither link callbacks nor this module touch Tk.
Generation tokens invalidate queued work and results when a connection changes.
"""

from collections import deque
from dataclasses import dataclass
import queue
import threading
from typing import Any, Callable

from .protocol import CarClient, Status


@dataclass(frozen=True)
class SessionEvent:
    kind: str
    generation: int
    key: str = ""
    data: Any = None
    error: Exception | None = None
    fatal: bool = False
    direction: str = ""
    message: str = ""


@dataclass
class _Job:
    kind: str
    generation: int
    key: str = ""
    operation: Callable | None = None
    label: str = ""


class SessionWorker:
    """Run connection, request, and close operations on one daemon thread.

    ``connect(factory, label)`` accepts a factory taking a progress callback and
    returning a protocol link. It returns the new generation immediately.
    ``request(generation, key, operation)`` invokes ``operation(client)`` and
    reports its return value in a result event. Telemetry and drive requests
    replace queued requests with the same key. STOP and motor-PID tuning cancel
    pending requests so an earlier queued AUTO/DEBUG/DRIVE/SPEED command cannot
    restart the car after the operation; neither can interrupt an active request.

    Disconnect/shutdown invalidate work immediately and close in the background.
    A cancelled connection factory may finish later; its link is then closed
    without a handshake. AUTO continues when a monitoring session is closed.
    """

    def __init__(self):
        self.events: queue.Queue[SessionEvent] = queue.Queue()
        self._condition = threading.Condition()
        self._jobs: deque[_Job] = deque()
        self._generation = 0
        self._closed = False
        self._client: CarClient | None = None
        self._client_generation = 0
        self._last_state = ""
        self._last_command = ""
        self._request_unanswered = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="CarSession")
        self._thread.start()

    def connect(self, factory: Callable, label: str) -> int:
        """Queue a link factory and PING handshake, replacing the old session."""
        with self._condition:
            if self._closed:
                raise RuntimeError("通信会话已关闭")
            self._generation += 1
            self._jobs.clear()
            generation = self._generation
            self._jobs.append(_Job("connect", generation, operation=factory, label=label))
            self._condition.notify()
            return generation

    def request(self, generation: int, key: str, operation: Callable[[CarClient], Any],
                *, coalesce: bool = False, priority: bool = False,
                cancel_drives: bool = False) -> bool:
        """Queue work; return False if the generation has already been cancelled.

        ``stop``, ``tune`` and ``pwm_unlock`` are priority transactions that discard queued
        requests for this session, while retaining a pending connection. Their
        operation must explicitly stop the car. ``cancel_drives`` alone only
        discards queued ``drive`` requests, for releasing a held motion control.
        DRIVE and SPEED operations share the ``drive`` key.
        """
        with self._condition:
            if self._closed or generation != self._generation:
                return False
            cancel_pending = key in ("stop", "tune", "pwm_unlock")
            coalesce = coalesce or key in ("telemetry", "drive", "stop", "tune", "pwm_unlock")
            priority = priority or cancel_pending
            cancel_drives = cancel_drives or cancel_pending
            self._jobs = deque(job for job in self._jobs
                               if not (job.kind == "request" and job.generation == generation and
                                       (cancel_pending or
                                        (coalesce and job.key == key) or
                                        (cancel_drives and job.key == "drive"))))
            job = _Job("request", generation, key, operation)
            if priority:
                # Never move a command in front of its connection/handshake.
                index = next((i for i, item in enumerate(self._jobs)
                              if item.kind == "request"), len(self._jobs))
                self._jobs.insert(index, job)
            else:
                self._jobs.append(job)
            self._condition.notify()
            return True

    def disconnect(self) -> int:
        """Invalidate work immediately; best effort STOP only when in DEBUG."""
        return self._end_session(shutdown=False)

    def shutdown(self) -> int:
        """Request background cleanup without joining or blocking the caller."""
        return self._end_session(shutdown=True)

    def _end_session(self, *, shutdown: bool) -> int:
        with self._condition:
            if self._closed:
                return self._generation
            self._generation += 1
            self._closed = shutdown
            self._jobs.clear()
            self._jobs.append(_Job("shutdown" if shutdown else "disconnect", self._generation))
            self._condition.notify()
            return self._generation

    def drain(self) -> list[SessionEvent]:
        """Return currently available events without waiting."""
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                return result

    def join(self, timeout: float | None = None) -> None:
        """Wait for cleanup in tests/CLI code; do not call from a UI handler."""
        self._thread.join(timeout)

    def _current(self, generation: int) -> bool:
        with self._condition:
            return not self._closed and generation == self._generation

    def _emit(self, event: SessionEvent) -> None:
        with self._condition:
            if not self._closed and event.generation == self._generation:
                self.events.put(event)

    def _line(self, generation: int, direction: str, message: str) -> None:
        # Record successful mode changes before a subsequent disconnect can run.
        if direction == "TX":
            self._last_command = message
            self._request_unanswered = True
        elif direction == "RX":
            self._request_unanswered = False
            fields = message.split()
            if len(fields) >= 2 and fields[0] == "STAT":
                try:
                    self._last_state = Status.parse(message).state
                except ValueError:
                    pass  # A malformed reply must not change disconnect behavior.
            elif message == "OK":
                state = {"DEBUG": "DEBUG", "STOP": "IDLE", "AUTO ARM": "ARMED"}.get(
                    self._last_command)
                if state:
                    self._last_state = state
        self._emit(SessionEvent("log", generation, direction=direction, message=message))

    def _close_active(self, generation: int, *, stop_debug: bool = True) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            if stop_debug and self._last_state == "DEBUG":
                try:
                    client.stop()
                except Exception:
                    pass  # Firmware also has a 500 ms debug-drive watchdog.
            client.close()
        except Exception as exc:
            self._emit(SessionEvent("log", generation, direction="ERROR",
                                    message=f"关闭连接失败：{exc}"))
        finally:
            self._last_state = ""
            self._last_command = ""
            self._request_unanswered = False

    def _connect(self, job: _Job) -> None:
        self._close_active(job.generation)
        if not self._current(job.generation):
            return
        try:
            progress = lambda message: self._emit(SessionEvent(
                "progress", job.generation, message=message))
            link = job.operation(progress)
            if not self._current(job.generation):
                link.close()
                return
            progress("正在验证小车固件 PING 握手")
            client = CarClient(link, lambda direction, message: self._line(
                job.generation, direction, message))
            self._client = client
            self._client_generation = job.generation
            if not self._current(job.generation):
                self._close_active(job.generation)
                return
            self._emit(SessionEvent("connected", job.generation, data=job.label))
        except Exception as exc:
            self._last_state = ""
            self._emit(SessionEvent("error", job.generation, key="connect", error=exc, fatal=True))

    def _request(self, job: _Job) -> None:
        if self._client is None or self._client_generation != job.generation:
            self._emit(SessionEvent("error", job.generation, job.key,
                                    error=ConnectionError("请先连接小车"), fatal=False))
            return
        self._request_unanswered = False
        try:
            result = job.operation(self._client)
            self._emit(SessionEvent("result", job.generation, job.key, data=result))
        except Exception as exc:
            # Validation and firmware ERR replies leave the transport usable.
            # A TX without RX indicates a link failure even when a backend raises
            # ValueError (invalid UART bytes) or a vendor-specific exception.
            fatal = isinstance(exc, (ConnectionError, TimeoutError, OSError)) or self._request_unanswered
            if fatal:
                with self._condition:
                    self._jobs = deque(item for item in self._jobs
                                       if item.kind != "request" or item.generation != job.generation)
                self._close_active(job.generation, stop_debug=False)
            self._emit(SessionEvent("error", job.generation, job.key, error=exc, fatal=fatal))

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: bool(self._jobs))
                job = self._jobs.popleft()
            if job.kind == "shutdown":
                self._close_active(job.generation)
                return
            if not self._current(job.generation):
                continue
            if job.kind == "connect":
                self._connect(job)
            elif job.kind == "disconnect":
                self._close_active(job.generation)
                self._emit(SessionEvent("disconnected", job.generation))
            else:
                self._request(job)
