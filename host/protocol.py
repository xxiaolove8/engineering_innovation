"""USART3/Bluetooth command protocol, also used by the GUI simulator."""

from dataclasses import dataclass
import math
import re
import threading
import time
from typing import Callable


STATES = {"IDLE", "ARMED", "FOLLOW", "AVOID_OUT", "AVOID_PASS", "AVOID_IN",
          "RECOVER", "FINISHED", "DEBUG", "FAULT"}
PID_NAMES = ("line_kp", "line_ki", "line_kd", "speed_kp", "speed_ki", "speed_kd",
             "target_ticks", "feedforward_pwm", "differential_gain", "curve_slowdown")
PID_LIMITS = (200, 100, 10, 50, 50, 10, 500, 500, 1, 1)
PID_DEFAULT_VALUES = (27.0, 0.0, 0.09, 3.0, 1.0, 0.0, 20.0, 250.0, 0.35, 0.35)
DEBUG_PWM_DEFAULT = 300
DEBUG_PWM_MAX = 1000
SERVO_HARD_MIN_US = 500
SERVO_HARD_MAX_US = 2500
SERVO_DEFAULT_CENTER_US = 1500
SERVO_DEFAULT_SPAN_US = 200
RANGE_STATES = {"NEVER", "WAIT_RISE", "WAIT_FALL", "OK", "NO_RISE", "NO_FALL",
                "ECHO_HIGH", "START_ERROR", "BAD_PULSE", "OVERCAPTURE",
                "CLOCK_ERROR", "LATE_ECHO", "IRQ_MISSED"}
HARDWARE_STAGES = {"NEVER", "RANGE_L", "RANGE_C", "RANGE_R", "CLOCK", "SERVO_PWM",
                   "MOTOR_L_PWM", "MOTOR_R_PWM", "ENCODER_L", "ENCODER_R", "READY"}


def _validate_command(command: str) -> None:
    if (not isinstance(command, str) or not command or len(command) > 90 or
            any(not " " <= char <= "~" for char in command)):
        raise ValueError("串口命令必须是非空可打印 ASCII，最多 90 字符")


def _default_pid_values() -> dict[str, float]:
    return dict(zip(PID_NAMES, PID_DEFAULT_VALUES))


def parse_debug_limit(response: str) -> int:
    """Parse the firmware-confirmed DEBUG duty limit, in permille."""
    fields = response.split() if isinstance(response, str) else []
    if (len(fields) != 2 or fields[0] != "LIMIT" or
            re.fullmatch(r"[0-9]+", fields[1]) is None):
        raise ValueError(f"无效调试 PWM 上限响应: {response}")
    limit = int(fields[1])
    if not 1 <= limit <= DEBUG_PWM_MAX:
        raise ValueError(f"调试 PWM 上限越界: {response}")
    return limit


@dataclass(frozen=True)
class LineDiagnostics:
    raw_bits: int
    line_bits: int
    black_level: int
    settle_us: int
    age_ms: int

    @classmethod
    def parse(cls, response: str) -> "LineDiagnostics":
        fields = response.split()
        if len(fields) != 6 or fields[0] != "LINE":
            raise ValueError(f"无效灰度诊断响应: {response}")
        raw, line, level, settle, age = map(int, fields[1:])
        if (not 0 <= raw <= 255 or not 0 <= line <= 255 or level not in (0, 1) or
                not 1 <= settle <= 65535 or not 0 <= age <= 0xffffffff or
                line != (raw if level else raw ^ 255)):
            raise ValueError(f"无效灰度诊断响应: {response}")
        return cls(raw, line, level, settle, age)


@dataclass(frozen=True)
class HardwareStatus:
    ready: bool
    stage: str

    @classmethod
    def parse(cls, response: str) -> "HardwareStatus":
        fields = response.split()
        if (len(fields) != 3 or fields[0] != "HW" or fields[1] not in ("0", "1") or
                fields[2] not in HARDWARE_STAGES or (fields[1] == "1") != (fields[2] == "READY")):
            raise ValueError(f"无效硬件状态响应: {response}")
        return cls(fields[1] == "1", fields[2])


@dataclass(frozen=True)
class RangeDiagnostics:
    side: str
    state: str
    valid: bool
    echo_high: bool
    pulse_us: int
    distance_mm: int | None
    age_ms: int | None
    triggers: int
    rises: int
    falls: int
    timeouts: int
    errors: int
    counter: int
    prescaler: int
    flags: int
    timer_running: bool

    @classmethod
    def parse(cls, response: str) -> "RangeDiagnostics":
        fields = response.split()
        if (len(fields) != 17 or fields[0] != "RANGE" or fields[1] not in ("L", "C", "R")
                or fields[2] not in RANGE_STATES):
            raise ValueError(f"无效测距诊断响应: {response}")
        try:
            valid, echo, pulse, distance, age, triggers, rises, falls, timeouts, errors, counter, psc, flags, running = map(int, fields[3:])
        except ValueError as exc:
            raise ValueError(f"无效测距诊断响应: {response}") from exc
        if (any(value not in (0, 1) for value in (valid, echo, running)) or
                not 0 <= pulse <= 65535 or not -1 <= distance <= 6000 or
                any(not 0 <= value <= 0xffffffff for value in (age, triggers, rises, falls, timeouts, errors, flags)) or
                not 0 <= counter <= 65535 or not 0 <= psc <= 65535 or
                bool(valid) != (distance >= 0)):
            raise ValueError(f"测距诊断数值越界: {response}")
        return cls(fields[1], fields[2], bool(valid), bool(echo), pulse,
                   None if distance < 0 else distance, None if age == 0xffffffff else age,
                   triggers, rises, falls, timeouts, errors, counter, psc, flags, bool(running))


@dataclass(frozen=True)
class ServoSettings:
    center_us: int = SERVO_DEFAULT_CENTER_US
    span_us: int = SERVO_DEFAULT_SPAN_US

    def __post_init__(self):
        if (type(self.center_us) is not int or type(self.span_us) is not int or
                not 0 <= self.span_us <= 1000 or
                self.minimum_us < SERVO_HARD_MIN_US or
                self.maximum_us > SERVO_HARD_MAX_US):
            raise ValueError("舵机中位、半摆幅必须是整数 µs；半摆幅 0–1000，中位 ± 半摆幅须在 500–2500 µs")

    @property
    def minimum_us(self) -> int:
        return self.center_us - self.span_us

    @property
    def maximum_us(self) -> int:
        return self.center_us + self.span_us

    @classmethod
    def parse(cls, response: str) -> "ServoSettings":
        parts = response.split() if isinstance(response, str) else []
        if (len(parts) != 3 or parts[0] != "SERVO" or
                any(re.fullmatch(r"[0-9]+", part) is None for part in parts[1:])):
            raise ValueError(f"无效舵机校准响应: {response}")
        return cls(*map(int, parts[1:]))


@dataclass(frozen=True)
class PidSettings:
    values: dict[str, float]

    @classmethod
    def parse(cls, response: str) -> "PidSettings":
        parts = response.split()
        if len(parts) != 11 or parts[0] != "PID":
            raise ValueError(f"无效 PID 响应: {response}")
        try:
            values = [float(item) for item in parts[1:]]
        except ValueError as exc:
            raise ValueError(f"无效 PID 响应: {response}") from exc
        if any(not math.isfinite(value) or value < 0 or value > limit
               for value, limit in zip(values, PID_LIMITS)) or values[6] == 0:
            raise ValueError(f"PID 数值越界: {response}")
        return cls(dict(zip(PID_NAMES, values)))


@dataclass(frozen=True)
class ControlStatus:
    line_error: float
    left_measured: float
    right_measured: float
    left_target: float
    right_target: float
    left_pwm: int
    right_pwm: int
    steer_us: int

    @classmethod
    def parse(cls, response: str) -> "ControlStatus":
        parts = response.split()
        if len(parts) != 9 or parts[0] != "CTRL":
            raise ValueError(f"无效控制响应: {response}")
        try:
            numbers = [float(item) for item in parts[1:6]]
            integers = [int(item) for item in parts[6:]]
        except ValueError as exc:
            raise ValueError(f"无效控制响应: {response}") from exc
        if (not all(math.isfinite(value) for value in numbers) or
                any(not -1000 <= value <= 1000 for value in integers[:2]) or
                not SERVO_HARD_MIN_US <= integers[2] <= SERVO_HARD_MAX_US):
            raise ValueError(f"无效控制响应: {response}")
        return cls(*numbers, *integers)


@dataclass(frozen=True)
class Status:
    state: str
    fault: int
    line_bits: int
    left_mm: int | None
    center_mm: int | None
    right_mm: int | None
    encoder_left_delta: int
    encoder_right_delta: int
    obstacles: int
    motor_left: int
    motor_right: int
    steer_us: int

    @classmethod
    def parse(cls, response: str) -> "Status":
        fields = response.split()
        if len(fields) != 13 or fields[0] != "STAT" or fields[1] not in STATES:
            raise ValueError(f"无效状态响应: {response}")
        try:
            fault, bits, left, center, right, enc_l, enc_r, obstacles, motor_l, motor_r, steer = map(int, fields[2:])
        except ValueError as exc:
            raise ValueError(f"无效状态响应: {response}") from exc
        if not (0 <= fault <= 6 and 0 <= bits <= 255 and -1 <= left <= 6000 and
                -1 <= center <= 6000 and
                -1 <= right <= 6000 and 0 <= obstacles <= 255 and
                all(-0x80000000 <= value <= 0x7fffffff for value in (enc_l, enc_r)) and
                -1000 <= motor_l <= 1000 and -1000 <= motor_r <= 1000 and
                SERVO_HARD_MIN_US <= steer <= SERVO_HARD_MAX_US):
            raise ValueError(f"状态数值越界: {response}")
        return cls(fields[1], fault, bits, None if left < 0 else left,
                   None if center < 0 else center,
                   None if right < 0 else right, enc_l, enc_r, obstacles,
                   motor_l, motor_r, steer)


class SerialLink:
    """JDY-31 SPP, onboard CH340 or external USB-TTL COM port, 9600 8N1."""

    def __init__(self, port: str):
        if not isinstance(port, str) or not re.fullmatch(r"COM[0-9]{1,3}", port.upper()):
            raise ValueError("串口名称应为 COM3 这类格式")
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("请使用 start_gui.cmd，或给运行上位机的 Python 安装 host/requirements.txt") from exc
        self._name = port.upper()
        self._port = serial.Serial(None, 9600, timeout=2.0, write_timeout=2.0,
                                   bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                                   stopbits=serial.STOPBITS_ONE, xonxoff=False,
                                   rtscts=False, dsrdtr=False)
        try:
            # The core board wires CH340 DTR/RTS to its automatic download
            # circuit. Configure inactive levels before open(), rather than
            # briefly asserting pySerial's defaults on an already-open port.
            self._port.dtr = False
            self._port.rts = False
            self._port.port = self._name
            self._port.open()
            self._port.reset_input_buffer()  # Discard responses from a previous connection.
        except BaseException:
            try:
                self._port.close()
            except Exception:
                pass  # Keep the original connection failure visible.
            raise
        self._failed = False
        self._closed = False
        self._lock = threading.Lock()
        self._last_tx = b""
        self._last_tx_written = 0
        self._last_rx = b""
        self._receive_status = "not_started"

    def receive_diagnostics(self) -> dict:
        """Return settings and the last exchange without reading the device.

        TX is the requested payload; written bytes is the count accepted by the
        serial driver. RX contains exactly the bytes returned for that request.
        """
        with self._lock:
            return {
                "port": self._name,
                "baudrate": getattr(self._port, "baudrate", 9600),
                "bytesize": getattr(self._port, "bytesize", 8),
                "parity": getattr(self._port, "parity", "N"),
                "stopbits": getattr(self._port, "stopbits", 1),
                "timeout": self._port.timeout,
                "write_timeout": getattr(self._port, "write_timeout", 2.0),
                "dtr": self._port.dtr,
                "rts": self._port.rts,
                "last_tx_hex": self._last_tx.hex(" ").upper(),
                "last_tx_bytes": len(self._last_tx),
                "last_tx_written_bytes": self._last_tx_written,
                "last_rx_hex": self._last_rx.hex(" ").upper(),
                "last_rx_bytes": len(self._last_rx),
                "receive_status": self._receive_status,
            }

    def request(self, command: str) -> str:
        _validate_command(command)
        with self._lock:
            if self._closed:
                raise ConnectionError("串口连接已关闭")
            if self._failed:
                raise ConnectionError("串口会话失效，请重新连接")
            previous_timeout = self._port.timeout
            try:
                self._last_tx = (command + "\n").encode("ascii")
                self._last_tx_written = 0
                self._last_rx = b""
                self._receive_status = "waiting"
                self._last_tx_written = self._port.write(self._last_tx)
                if self._last_tx_written != len(self._last_tx):
                    self._receive_status = "write_incomplete"
                    raise ConnectionError("串口命令未完整写入，请重新连接")
                # IOBase.readline restarts the serial timeout for every byte.
                # Bound the whole response, including a slow stream without LF.
                receive_timeout = 5.0 if command in ("PID SAVE", "SERVO SAVE") else 2.0
                deadline = time.monotonic() + receive_timeout
                response_buffer = bytearray()
                while len(response_buffer) < 161:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    if self._port.timeout != remaining:
                        self._port.timeout = remaining
                    chunk = self._port.read(1)
                    if not chunk:
                        break
                    response_buffer.extend(chunk)
                    self._last_rx = bytes(response_buffer)
                    if chunk == b"\n":
                        break
                response = bytes(response_buffer)
                rx_detail = (f"收到 {len(response)} 字节，HEX="
                             f"{response.hex(' ').upper() or '(空)'}")
                if len(response) > 160:
                    self._receive_status = "oversize"
                    raise ValueError("串口响应超过 160 字节")
                if not response or not response.endswith(b"\n"):
                    if not response:
                        self._receive_status = "zero_bytes"
                        reason = "零字节，未收到任何响应"
                    elif any(byte > 127 for byte in response):
                        self._receive_status = "non_ascii"
                        reason = "收到非 ASCII 数据（乱码），且没有完整换行响应"
                    else:
                        self._receive_status = "incomplete"
                        reason = "收到不完整响应，缺少结尾换行"
                    raise TimeoutError(f"{self._name} 已打开，但 {command!r} {reason}；{rx_detail}。"
                                       "请确认 9600 8N1、发送换行和小车固件。"
                                       "板载 CH340 使用 USART1/PA9/PA10，检查 JP3 的 1–2、3–4 跳帽；"
                                       "JDY-31 或外置 USB-TTL 使用 USART3/PB10/PB11，需共地")
                if getattr(self._port, "in_waiting", 0):
                    self._receive_status = "unexpected_tail"
                    raise ConnectionError("收到未匹配的串口响应，请重新连接")
                try:
                    decoded = response.decode("ascii", errors="strict")
                except UnicodeDecodeError as exc:
                    self._receive_status = "non_ascii"
                    raise UnicodeDecodeError(exc.encoding, exc.object, exc.start, exc.end,
                                             f"{exc.reason}；收到非 ASCII 数据（乱码）；{rx_detail}") from exc
                self._receive_status = "complete"
                return decoded.rstrip("\r\n")
            except BaseException:
                self._failed = True
                raise
            finally:
                try:
                    if self._port.timeout != previous_timeout:
                        self._port.timeout = previous_timeout
                except Exception:
                    if not self._failed:
                        self._failed = True
                        raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._port.close()


class CarClient:
    def __init__(self, link, on_line: Callable[[str, str], None] | None = None):
        self.link = link
        self.on_line = on_line
        self.servo_settings = ServoSettings()
        try:
            response = self.request("PING")
            if response != "PONG 2":
                raise ConnectionError(f"透传已返回数据，但固件握手失败：收到 {response!r}，预期 'PONG 2'；"
                                      "请确认小车固件为协议 v2")
        except BaseException:
            try:
                link.close()
            except Exception:
                pass
            raise

    def request(self, command: str) -> str:
        _validate_command(command)
        if self.on_line:
            self.on_line("TX", command)
        response = self.link.request(command)
        if self.on_line:
            self.on_line("RX", response)
        return response

    def status(self) -> Status:
        return Status.parse(self.request("STATUS?"))

    def _expect_ok(self, command: str) -> None:
        reply = self.request(command)
        if reply != "OK":
            raise RuntimeError(f"命令被拒绝：{reply}")

    def stop(self) -> None:
        self._expect_ok("STOP")

    def arm(self) -> None:
        self._expect_ok("AUTO ARM")

    def debug(self) -> None:
        self._expect_ok("DEBUG")

    def debug_limit(self) -> int:
        response = self.request("DEBUG LIMIT?")
        if response == "ERR COMMAND":
            raise RuntimeError("当前固件不支持调试 PWM 上限，需要更新为新版固件")
        return parse_debug_limit(response)

    def set_debug_limit(self, permille: int) -> None:
        if type(permille) is not int or not 1 <= permille <= DEBUG_PWM_MAX:
            raise ValueError("调试 PWM 上限必须是 1–1000‰ 的整数（最高 100%）")
        response = self.request(f"DEBUG LIMIT {permille}")
        if response == "ERR COMMAND":
            raise RuntimeError("当前固件不支持调试 PWM 上限，需要更新为新版固件")
        if response != "OK":
            raise RuntimeError(f"命令被拒绝：{response}")

    def drive(self, left: int, right: int, steer_us: int) -> None:
        if (type(left) is not int or type(right) is not int or type(steer_us) is not int or
                not -DEBUG_PWM_MAX <= left <= DEBUG_PWM_MAX or
                not -DEBUG_PWM_MAX <= right <= DEBUG_PWM_MAX or
                not self.servo_settings.minimum_us <= steer_us <= self.servo_settings.maximum_us):
            raise ValueError(f"调试驱动仅允许 ±1000‰（100%）、舵机 {self.servo_settings.minimum_us}–"
                             f"{self.servo_settings.maximum_us} µs；需先设置固件调试上限")
        self._expect_ok(f"DRIVE {left} {right} {steer_us}")

    def speed(self, left: float, right: float) -> None:
        """DEBUG forward speed targets, in encoder counts per 10 ms."""
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or
               not 0 <= value <= 500 or not math.isfinite(value)
               for value in (left, right)):
            raise ValueError("速度试跑目标仅允许 0–500 编码器计数/10 ms")
        self._expect_ok(f"SPEED {max(0.0, left):.3f} {max(0.0, right):.3f}")

    def pid(self) -> PidSettings:
        return PidSettings.parse(self.request("PID?"))

    def control(self) -> ControlStatus:
        return ControlStatus.parse(self.request("CTRL?"))

    def hardware(self) -> HardwareStatus:
        return HardwareStatus.parse(self.request("HW?"))

    def line_diagnostics(self) -> LineDiagnostics:
        return LineDiagnostics.parse(self.request("LINE?"))

    def range_diagnostics(self, side: str) -> RangeDiagnostics:
        if side not in ("L", "C", "R"):
            raise ValueError("测距通道必须是 L、C 或 R")
        result = RangeDiagnostics.parse(self.request(f"RANGE? {side}"))
        if result.side != side:
            raise ValueError("测距诊断返回了错误通道")
        return result

    def set_pid(self, name: str, value: float) -> None:
        if name not in PID_NAMES:
            raise ValueError("未知 PID 参数")
        index = PID_NAMES.index(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("PID 参数必须是数值")
        if not math.isfinite(value) or not 0 <= value <= PID_LIMITS[index] or (
                name == "target_ticks" and value == 0):
            raise ValueError("PID 参数超出允许范围")
        text = f"{value:.3f}"
        if name == "target_ticks" and float(text) == 0:
            raise ValueError("目标脉冲数保留三位小数后必须大于零")
        self._expect_ok(f"PID SET {name} {text}")

    def reset_pid(self) -> None:
        self._expect_ok("PID RESET")

    def save_pid(self) -> None:
        self._expect_ok("PID SAVE")

    def load_pid(self) -> None:
        self._expect_ok("PID LOAD")

    def pid_saved(self) -> bool:
        response = self.request("PID STORE?")
        if response not in ("STORE SAVED", "STORE UNSAVED"):
            raise ValueError(f"无效保存状态: {response}")
        return response == "STORE SAVED"

    def servo(self) -> ServoSettings:
        response = self.request("SERVO?")
        if response == "ERR COMMAND":
            raise RuntimeError("当前固件不支持舵机中位 / 对称限幅设置，请更新固件")
        self.servo_settings = ServoSettings.parse(response)
        return self.servo_settings

    def _servo_command(self, command: str) -> None:
        response = self.request(command)
        if response == "ERR COMMAND":
            raise RuntimeError("当前固件不支持舵机中位 / 对称限幅设置，请更新固件")
        if response != "OK":
            raise RuntimeError(f"命令被拒绝：{response}")

    def set_servo(self, center_us: int, span_us: int) -> None:
        settings = ServoSettings(center_us, span_us)
        self._servo_command(f"SERVO SET {settings.center_us} {settings.span_us}")
        self.servo()

    def save_servo(self) -> None:
        self._servo_command("SERVO SAVE")

    def load_servo(self) -> None:
        self._servo_command("SERVO LOAD")
        self.servo()

    def reset_servo(self) -> None:
        self._servo_command("SERVO RESET")
        self.servo()

    def servo_saved(self) -> bool:
        response = self.request("SERVO STORE?")
        if response == "ERR COMMAND":
            raise RuntimeError("当前固件不支持舵机中位 / 对称限幅设置，请更新固件")
        if response not in ("SERVO STORE SAVED", "SERVO STORE UNSAVED"):
            raise ValueError(f"无效舵机保存状态: {response}")
        return response == "SERVO STORE SAVED"

    def close(self) -> None:
        # Closing telemetry during AUTO must not stop the on-board race.
        self.link.close()


class SimLink:
    """Protocol simulator for PC GUI testing, not a physics or race simulator."""

    def __init__(self):
        self.state = "IDLE"
        self.fault = 0
        self.line_bits = 0b00011000
        self.left_mm = 500
        self.center_mm = 500
        self.right_mm = 500
        self.obstacles = 0
        self.motor_left = 0
        self.motor_right = 0
        self.servo_settings = ServoSettings()
        self.saved_servo_settings: ServoSettings | None = None
        self.steer_us = self.servo_settings.center_us
        self.arm_time = 0.0
        self.last_drive = 0.0
        self.hardware_ready = True
        self.left_measured = self.right_measured = 0.0
        self.left_target = self.right_target = 0.0
        self._speed_active = False
        self._debug_pwm_limit = DEBUG_PWM_DEFAULT
        self._speed_integrals = [0.0, 0.0]
        self._speed_previous = [None, None]
        self._speed_derivatives = [0.0, 0.0]
        self._last_tick = time.monotonic()
        self.pid_values = _default_pid_values()
        self.saved_pid_values: dict[str, float] | None = None
        self.range_queries = dict.fromkeys(("L", "C", "R"), 0)

    def _clear_debug_drive(self) -> None:
        self.motor_left = self.motor_right = 0
        self.steer_us = self.servo_settings.center_us
        self.left_target = self.right_target = 0.0
        self.left_measured = self.right_measured = 0.0
        self._speed_active = False
        self._debug_pwm_limit = DEBUG_PWM_DEFAULT
        self._reset_speed_pid()

    def _reset_speed_pid(self) -> None:
        self._speed_integrals = [0.0, 0.0]
        self._speed_previous = [None, None]
        self._speed_derivatives = [0.0, 0.0]

    def _sim_speed_pwm(self, index: int, target: float, measured: float,
                       dt: float) -> int:
        # Bounded GUI demonstration of the speed controller, not a hardware model.
        if target == 0:
            self._speed_integrals[index] = 0.0
            self._speed_previous[index] = None
            self._speed_derivatives[index] = 0.0
            return 0
        previous = self._speed_previous[index]
        derivative = (0.0 if previous is None else
                      .2 * (measured - previous) / dt + .8 * self._speed_derivatives[index])
        self._speed_previous[index] = measured
        self._speed_derivatives[index] = derivative
        error = target - measured
        candidate = max(-100.0, min(100.0, self._speed_integrals[index] + error * dt))
        params = self.pid_values
        base = (params["feedforward_pwm"] * target / params["target_ticks"] +
                params["speed_kp"] * error - params["speed_kd"] * derivative)
        raw = base + params["speed_ki"] * candidate
        if not (raw > self._debug_pwm_limit and error > 0 or raw < 0 and error < 0):
            self._speed_integrals[index] = candidate
        return round(max(0.0, min(self._debug_pwm_limit,
                                 base + params["speed_ki"] * self._speed_integrals[index])))

    def _simulate_debug(self, elapsed: float) -> None:
        # Use small steps so the preview behaves consistently at different poll rates.
        while elapsed > 0:
            dt = min(.01, elapsed)
            if self._speed_active:
                self.motor_left = self._sim_speed_pwm(0, self.left_target, self.left_measured, dt)
                self.motor_right = self._sim_speed_pwm(1, self.right_target, self.right_measured, dt)
            response = 1.0 - math.exp(-dt / .15)
            self.left_measured += (abs(self.motor_left) * .08 - self.left_measured) * response
            self.right_measured += (abs(self.motor_right) * .08 - self.right_measured) * response
            elapsed -= dt

    def _tick(self, now: float) -> None:
        # Advance time on every exchange, so CTRL? sees the same watchdog as STATUS?.
        elapsed = max(0.0, min(.5, now - self._last_tick))
        self._last_tick = now
        if not self.hardware_ready:
            self.state, self.fault = "FAULT", 6
            self._clear_debug_drive()
            return
        if self.state != "DEBUG":
            self._debug_pwm_limit = DEBUG_PWM_DEFAULT
        if self.state == "FAULT":
            self._clear_debug_drive()
            return
        if self.state == "ARMED" and now - self.arm_time >= 3:
            if any(distance is None or distance < 0
                   for distance in (self.left_mm, self.center_mm, self.right_mm)):
                self.state, self.fault = "FAULT", 2
            elif not self.line_bits:
                self.state, self.fault = "FAULT", 1
            else:
                self.state = "FOLLOW"
        if (self.state == "DEBUG" and
                (self.motor_left != 0 or self.motor_right != 0 or self._speed_active or
                 self.steer_us != self.servo_settings.center_us) and
                now - self.last_drive >= 0.5):
            self._clear_debug_drive()
        elif self.state == "DEBUG":
            self._simulate_debug(elapsed)

    def request(self, command: str) -> str:
        now = time.monotonic()
        self._tick(now)
        if command == "PING":
            return "PONG 2"
        if command == "HW?":
            return "HW 1 READY" if self.hardware_ready else "HW 0 CLOCK"
        if command == "DEBUG LIMIT?":
            return f"LIMIT {self._debug_pwm_limit}"
        if command == "SERVO?":
            return f"SERVO {self.servo_settings.center_us} {self.servo_settings.span_us}"
        if command == "SERVO STORE?":
            saved = self.saved_servo_settings == self.servo_settings
            return f"SERVO STORE {'SAVED' if saved else 'UNSAVED'}"
        if command in ("SERVO SAVE", "SERVO LOAD", "SERVO RESET") or command.startswith("SERVO SET "):
            if not self.hardware_ready:
                return "ERR HARDWARE"
            if self.state != "IDLE":
                return "ERR STATE"
            if command == "SERVO SAVE":
                self.saved_servo_settings = self.servo_settings
                return "OK"
            if command == "SERVO LOAD":
                if self.saved_servo_settings is None:
                    return "ERR EMPTY"
                settings = self.saved_servo_settings
            elif command == "SERVO RESET":
                settings = ServoSettings()
            else:
                fields = command[10:].split()
                if (len(fields) != 2 or
                        any(re.fullmatch(r"[-+]?[0-9]+", field) is None for field in fields)):
                    return "ERR PARAM"
                try:
                    settings = ServoSettings(*map(int, fields))
                except ValueError:
                    return "ERR PARAM"
            self.servo_settings = settings
            self.steer_us = settings.center_us
            return "OK"
        if not self.hardware_ready and (command in ("DEBUG", "AUTO ARM") or
                                       command.startswith(("DRIVE ", "SPEED ", "DEBUG LIMIT "))):
            return "ERR HARDWARE"
        if command.startswith("DEBUG LIMIT "):
            fields = command[12:].split()
            if (len(fields) != 1 or re.fullmatch(r"[-+]?[0-9]+", fields[0]) is None or
                    not 1 <= int(fields[0]) <= DEBUG_PWM_MAX):
                return "ERR STATE_OR_RANGE"
            if (self.state != "DEBUG" or self.motor_left != 0 or self.motor_right != 0 or
                    self._speed_active):
                return "ERR STATE_OR_RANGE"
            self._debug_pwm_limit = int(fields[0])
            return "OK"
        if command == "LINE?":
            return f"LINE {self.line_bits ^ 255} {self.line_bits} 0 500 0"
        if command.startswith("RANGE? "):
            side = command[7:]
            if side not in ("L", "C", "R"):
                return "ERR PARAM"
            self.range_queries[side] += 1
            distance = {"L": self.left_mm, "C": self.center_mm, "R": self.right_mm}[side]
            count = self.range_queries[side]
            valid = distance is not None and distance >= 0
            pulse = round(distance * 2000 / 343) if valid else 0
            return (f"RANGE {side} {'OK' if valid else 'NO_RISE'} {int(valid)} 0 {pulse} "
                    f"{distance if valid else -1} 0 {count} {count if valid else 0} "
                    f"{count if valid else 0} {0 if valid else count} 0 12345 "
                    f"{83 if side == 'R' else 167} 0 1")
        if command == "PID?":
            return "PID " + " ".join(f"{self.pid_values[name]:.3f}" for name in PID_NAMES)
        if command == "PID STORE?":
            return "STORE SAVED" if self.saved_pid_values == self.pid_values else "STORE UNSAVED"
        if command == "PID SAVE":
            if self.state != "IDLE":
                return "ERR STATE"
            self.saved_pid_values = self.pid_values.copy()
            return "OK"
        if command == "PID LOAD":
            if self.state != "IDLE":
                return "ERR STATE"
            if self.saved_pid_values is None:
                return "ERR EMPTY"
            self.pid_values = self.saved_pid_values.copy()
            return "OK"
        if command == "CTRL?":
            return (f"CTRL 0.00 {self.left_measured:.2f} {self.right_measured:.2f} "
                    f"{self.left_target:.2f} {self.right_target:.2f} "
                    f"{self.motor_left} {self.motor_right} {self.steer_us}")
        if command == "PID RESET":
            if self.state != "IDLE":
                return "ERR STATE"
            self.pid_values = _default_pid_values()
            return "OK"
        if command.startswith("PID SET "):
            if self.state != "IDLE":
                return "ERR STATE"
            fields = command[8:].split()
            if len(fields) != 2:
                return "ERR PARAM"
            name, text = fields
            try:
                value = float(text)
                index = PID_NAMES.index(name)
            except ValueError:
                return "ERR PARAM"
            if not math.isfinite(value) or not 0 <= value <= PID_LIMITS[index] or (
                    name == "target_ticks" and value == 0):
                return "ERR PARAM"
            self.pid_values[name] = value
            return "OK"
        if command == "STATUS?":
            distances = " ".join(str(distance if distance is not None and distance >= 0 else -1)
                                 for distance in (self.left_mm, self.center_mm, self.right_mm))
            return (f"STAT {self.state} {self.fault} {self.line_bits} "
                    f"{distances} 0 0 {self.obstacles} "
                    f"{self.motor_left} {self.motor_right} {self.steer_us}")
        if command in ("STOP", "IDLE"):
            self.state = "IDLE" if self.hardware_ready else "FAULT"
            self.fault = 0 if self.hardware_ready else 6
            self._clear_debug_drive()
            return "OK"
        if command == "AUTO ARM":
            if self.state != "IDLE":
                return "ERR STATE"
            self.state = "ARMED"
            self.fault = 0
            self.obstacles = 0
            self.arm_time = now
            return "OK"
        if command == "DEBUG":
            if self.state != "IDLE":
                return "ERR STATE"
            self.state = "DEBUG"
            self._clear_debug_drive()
            self.last_drive = now
            return "OK"
        if command.startswith("SPEED "):
            fields = command[6:].split()
            token = r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"
            if (self.state != "DEBUG" or len(fields) != 2 or
                    any(re.fullmatch(token, field) is None for field in fields)):
                return "ERR STATE_OR_RANGE"
            left, right = map(float, fields)
            if not all(math.isfinite(value) and 0 <= value <= 500 for value in (left, right)):
                return "ERR STATE_OR_RANGE"
            # strtof reports ERANGE for nonzero decimal targets below float32's
            # normal range, including values which Python float rounds to zero.
            if any(value < 2 ** -126 and
                   any(char in "123456789" for char in field.lower().split("e")[0])
                   for field, value in zip(fields, (left, right))):
                return "ERR STATE_OR_RANGE"
            if (not self._speed_active or self.left_target != left or
                    self.right_target != right):
                self._reset_speed_pid()
            self._speed_active = left > 0 or right > 0
            self.left_target, self.right_target = left, right
            self.steer_us = self.servo_settings.center_us
            self.last_drive = now
            # A zero target always releases that motor immediately.
            if left == 0:
                self.motor_left = 0
            if right == 0:
                self.motor_right = 0
            return "OK"
        if command.startswith("DRIVE "):
            match = re.fullmatch(r"DRIVE\s+([-+]?[0-9]+)\s+([-+]?[0-9]+)\s+([-+]?[0-9]+)\s*", command)
            if match and self.state == "DEBUG":
                left, right, steer = map(int, match.groups())
                if (-self._debug_pwm_limit <= left <= self._debug_pwm_limit and
                        -self._debug_pwm_limit <= right <= self._debug_pwm_limit and
                        self.servo_settings.minimum_us <= steer <= self.servo_settings.maximum_us):
                    self._speed_active = False
                    self.left_target = self.right_target = 0.0
                    self._reset_speed_pid()
                    self.motor_left, self.motor_right, self.steer_us = left, right, steer
                    self.last_drive = now
                    return "OK"
            return "ERR STATE_OR_RANGE"
        return "ERR COMMAND"

    def close(self) -> None:
        pass

    def reboot(self) -> None:
        self.state = "IDLE"
        self.fault = 0
        self.obstacles = 0
        self.servo_settings = self.saved_servo_settings or ServoSettings()
        self._clear_debug_drive()
        self.last_drive = 0.0
        self._last_tick = time.monotonic()
        self.pid_values = (self.saved_pid_values.copy() if self.saved_pid_values is not None
                           else _default_pid_values())
        self.range_queries = dict.fromkeys(("L", "C", "R"), 0)
