"""USART3/Bluetooth command protocol, also used by the GUI simulator."""

from dataclasses import dataclass
import re
import time


STATES = {"IDLE", "ARMED", "FOLLOW", "AVOID_OUT", "AVOID_PASS", "AVOID_IN",
          "RECOVER", "FINISHED", "DEBUG", "FAULT"}


@dataclass(frozen=True)
class Status:
    state: str
    fault: int
    line_bits: int
    left_mm: int | None
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
        if len(fields) != 12 or fields[0] != "STAT" or fields[1] not in STATES:
            raise ValueError(f"无效状态响应: {response}")
        try:
            fault, bits, left, right, enc_l, enc_r, obstacles, motor_l, motor_r, steer = map(int, fields[2:])
        except ValueError as exc:
            raise ValueError(f"无效状态响应: {response}") from exc
        if not (0 <= fault <= 5 and 0 <= bits <= 63 and -1 <= left <= 6000 and
                -1 <= right <= 6000 and 0 <= obstacles <= 255 and
                -1000 <= motor_l <= 1000 and -1000 <= motor_r <= 1000 and
                1300 <= steer <= 1700):
            raise ValueError(f"状态数值越界: {response}")
        return cls(fields[1], fault, bits, None if left < 0 else left,
                   None if right < 0 else right, enc_l, enc_r, obstacles,
                   motor_l, motor_r, steer)


class SerialLink:
    def __init__(self, port: str):
        if not re.fullmatch(r"COM\d{1,3}", port.upper()):
            raise ValueError("串口名称应为 COM3 这类格式")
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("请先安装 pyserial：python -m pip install -r host/requirements.txt") from exc
        self._port = serial.Serial(port.upper(), 9600, timeout=0.4, write_timeout=0.4)

    def request(self, command: str) -> str:
        self._port.write((command + "\n").encode("ascii"))
        response = self._port.readline()
        if not response:
            raise TimeoutError("设备响应超时")
        return response.decode("ascii", errors="strict").strip()

    def close(self) -> None:
        self._port.close()


class CarClient:
    def __init__(self, link):
        self.link = link
        if self.link.request("PING") != "PONG 1":
            raise ConnectionError("协议版本不匹配")

    def status(self) -> Status:
        return Status.parse(self.link.request("STATUS?"))

    def _expect_ok(self, command: str) -> None:
        reply = self.link.request(command)
        if reply != "OK":
            raise RuntimeError(f"命令被拒绝：{reply}")

    def stop(self) -> None:
        self._expect_ok("STOP")

    def arm(self) -> None:
        self._expect_ok("AUTO ARM")

    def debug(self) -> None:
        self._expect_ok("DEBUG")

    def drive(self, left: int, right: int, steer_us: int) -> None:
        if (type(left) is not int or type(right) is not int or type(steer_us) is not int or
                not -300 <= left <= 300 or not -300 <= right <= 300 or
                not 1300 <= steer_us <= 1700):
            raise ValueError("调试驱动仅允许 ±300‰、舵机 1300–1700 µs")
        self._expect_ok(f"DRIVE {left} {right} {steer_us}")

    def close(self) -> None:
        # Closing telemetry during AUTO must not stop the on-board race.
        self.link.close()


class SimLink:
    """Protocol simulator for PC GUI testing, not a physics or race simulator."""

    def __init__(self):
        self.state = "IDLE"
        self.line_bits = 0b001100
        self.left_mm = 500
        self.right_mm = 500
        self.obstacles = 0
        self.motor_left = 0
        self.motor_right = 0
        self.steer_us = 1500
        self.arm_time = 0.0
        self.last_drive = 0.0

    def request(self, command: str) -> str:
        now = time.monotonic()
        if command == "PING":
            return "PONG 1"
        if command == "STATUS?":
            if self.state == "ARMED" and now - self.arm_time >= 3:
                self.state = "FOLLOW" if self.line_bits else "FAULT"
            if self.state == "DEBUG" and now - self.last_drive >= 0.5:
                self.motor_left = self.motor_right = 0
                self.steer_us = 1500
            return (f"STAT {self.state} {1 if self.state == 'FAULT' else 0} {self.line_bits} "
                    f"{self.left_mm} {self.right_mm} 0 0 {self.obstacles} "
                    f"{self.motor_left} {self.motor_right} {self.steer_us}")
        if command in ("STOP", "IDLE"):
            self.state = "IDLE"
            self.motor_left = self.motor_right = 0
            self.steer_us = 1500
            return "OK"
        if command == "AUTO ARM":
            if self.state != "IDLE":
                return "ERR STATE"
            self.state = "ARMED"
            self.arm_time = now
            return "OK"
        if command == "DEBUG":
            if self.state != "IDLE":
                return "ERR STATE"
            self.state = "DEBUG"
            return "OK"
        match = re.fullmatch(r"DRIVE (-?\d+) (-?\d+) (\d+)", command)
        if match and self.state == "DEBUG":
            left, right, steer = map(int, match.groups())
            if -300 <= left <= 300 and -300 <= right <= 300 and 1300 <= steer <= 1700:
                self.motor_left, self.motor_right, self.steer_us = left, right, steer
                self.last_drive = now
                return "OK"
        return "ERR STATE_OR_RANGE"

    def close(self) -> None:
        pass
