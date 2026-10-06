"""Desktop controller. Run with: python -m host.gui."""

from collections import deque
from datetime import datetime
import math
import tkinter as tk
from tkinter import filedialog

from .protocol import HardwareStatus, PID_LIMITS, PID_NAMES, SerialLink, ServoSettings, SimLink, parse_debug_limit
from .session import SessionWorker
from .ui import DashboardView

STATE_LABELS = {
    "IDLE": "待机", "ARMED": "自动预备", "FOLLOW": "循迹", "AVOID_OUT": "绕障离线",
    "AVOID_PASS": "绕障通过", "AVOID_IN": "绕障回转", "RECOVER": "搜线回归",
    "FINISHED": "已完成", "DEBUG": "调试", "FAULT": "故障",
}
FAULT_LABELS = ("无", "丢线", "测距异常", "回线超时", "比赛超时", "前方受阻",
                "硬件初始化 / 定时器异常")
HARDWARE_LABELS = {
    "NEVER": "尚未初始化", "RANGE_L": "左测距定时器", "RANGE_C": "中测距定时器",
    "RANGE_R": "右测距定时器", "CLOCK": "微秒定时器", "SERVO_PWM": "舵机 PWM",
    "MOTOR_L_PWM": "左电机 PWM", "MOTOR_R_PWM": "右电机 PWM",
    "ENCODER_L": "左编码器", "ENCODER_R": "右编码器", "READY": "正常",
}


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("循迹控制台 · IF CAR")
        root.geometry("1180x840")
        root.minsize(1000, 700)
        self.worker = SessionWorker()
        self.generation = 0
        self.connected = self.connecting = self.simulated = self.ready = self.closed = False
        self._initializing = False
        self.last_state = ""
        self._pending: set[str] = set()
        self._holding = False
        self._motion_source = ""
        self._remote_direction = (0, 0)
        self._remote_keys = set()
        self._blocked_keys = set()
        self._key_timers = {}
        self.drive_timer = self.poll_timer = self.event_timer = None
        self._logs = deque(maxlen=2000)
        self.port = tk.StringVar()
        self._ports = {}
        self.transport = tk.StringVar(value="串口（USB / JDY-31）")
        self.ble_target = tk.StringVar(value="BT24")
        self.ble_channel = tk.StringVar(value="FFE1")
        self.port_hint = tk.StringVar()
        self.connection = tk.StringVar(value="● 未连接")
        self.notice = tk.StringVar(value="选择串口连接小车，或打开仿真预览。急停可使用 Esc。")
        self.state = tk.StringVar(value="—")
        self.fault = tk.StringVar(value="—")
        self.hardware_info = tk.StringVar(value="未读取")
        self.line_info = tk.StringVar(value="CH1 → CH8 · 实心表示识别到线")
        self.ranges = [tk.StringVar(value="—") for _ in range(3)]
        self.obstacles = tk.StringVar(value="—")
        self.motors = tk.StringVar(value="—")
        self.steer = tk.StringVar(value="—")
        self.control_info = tk.StringVar(value="连接后显示目标和实测速度")
        self.flash_status = tk.StringVar(value="尚未读取参数")
        self.servo_settings = ServoSettings()
        self.servo_supported = None
        self.servo_center = tk.StringVar(value="1500")
        self.servo_span = tk.StringVar(value="200")
        self.servo_bounds_info = tk.StringVar(value="默认范围：1300 / 1500 / 1700 µs（1.300 / 1.500 / 1.700 ms）")
        self.servo_flash_status = tk.StringVar(value="尚未读取舵机校准")
        self.pid_vars = [tk.StringVar(value="—") for _ in PID_NAMES]
        self.serial_command = tk.StringVar()
        self.drive_left = tk.DoubleVar(value=12.0)
        self.drive_right = tk.DoubleVar(value=12.0)
        self.drive_steer = tk.IntVar(value=1500)
        self.debug_pwm_limit = 300
        self.pwm_limit_supported = None
        self.pwm_limit_percent = tk.StringVar(value="100")
        self.pwm_limit_info = tk.StringVar(value="默认测试上限 30% · 连接后读取车端限制")
        self.remote_pwm = tk.IntVar(value=120)
        self.remote_turn = tk.IntVar(value=120)
        self.test_left = tk.StringVar(value="20")
        self.test_right = tk.StringVar(value="20")
        self.speed_targets = [tk.StringVar(value="—") for _ in range(2)]
        self.speed_measured = [tk.StringVar(value="—") for _ in range(2)]
        self.speed_pwm = [tk.StringVar(value="—") for _ in range(2)]
        self.sim_line = tk.StringVar(value="00011000")
        self.sim_ranges = [tk.IntVar(value=500) for _ in range(3)]
        self.view = DashboardView(self)
        self.port.trace_add("write", lambda *_args: self._update_port_hint())
        self.view.transport_picker.bind("<<ComboboxSelected>>",
                                        lambda _event: self._update_port_hint(), add="+")
        self._refresh_ports()
        self._update_controls()
        self.event_timer = root.after(40, self._drain_events)
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.bind("<Escape>", lambda _e: self._stop())
        root.bind("<ButtonRelease-1>", lambda _e: self._drive_release(), add="+")
        root.bind("<FocusOut>", self._focus_out, add="+")
        root.bind("<KeyPress>", self._key_press, add="+")
        root.bind("<KeyRelease>", self._key_release, add="+")
        self.view.tabs.bind("<<NotebookTabChanged>>", self._tab_changed)

    def _busy(self):
        return bool(self._pending - {"telemetry", "hardware", "line", "pid_read", "pwm_limit_read", "servo_read"})

    def _cancel_timer(self, name):
        timer = getattr(self, name)
        if timer is not None:
            self.root.after_cancel(timer)
            setattr(self, name, None)

    def _update_controls(self):
        self.view.set_enabled(connected=self.connected, connecting=self.connecting,
                              state=self.last_state, ready=self.ready,
                              simulated=self.simulated, busy=self._busy(),
                              holding=self._holding, source=self._motion_source,
                              pwm_limit_supported=self.pwm_limit_supported,
                              servo_supported=self.servo_supported)

    def _queue(self, key, operation, **options):
        if not self.connected:
            self.notice.set("请先连接小车或仿真。")
            return False
        if key in self._pending and not options.get("coalesce") and key != "stop":
            return False
        accepted = self.worker.request(self.generation, key, operation, **options)
        if accepted and key != "drive":
            self._pending.add(key)
        self._update_controls()
        return accepted

    def _connect_selected(self):
        if self.transport.get() == "旧 BT24 BLE":
            self._connect_ble()
        else:
            self._connect_serial()

    def _connect_serial(self):
        port = self.port.get().strip().upper()
        if not port:
            self.notice.set("未选择串口；请确认板载 CH340 / USB-TTL 已连接，或 JDY-31 已配对生成 COM。")
            return
        def factory(progress):
            progress(f"正在打开串口 {port} · 9600 bps · 8N1 · DTR/RTS 关闭")
            link = SerialLink(port)
            progress(f"串口 {port} 已打开 · 等待小车 PONG 2 握手")
            return link
        self._start_connection(factory, port)

    def _connect_ble(self):
        target = self.ble_target.get().strip()
        if not target:
            self.notice.set("请输入旧 BT24 的设备名称或地址。")
            return
        channel = self.ble_channel.get()

        def factory(progress):
            from .legacy.ble_link import BleLink, WRITE_UUID, ALTERNATE_WRITE_UUID
            uuid = ALTERNATE_WRITE_UUID if channel == "FFE2" else WRITE_UUID
            return BleLink(target, write_uuid=uuid, on_progress=progress)

        self._start_connection(factory, f"BT24 · {target}")

    def _connect_sim(self):
        self._start_connection(lambda _progress: SimLink(), "界面仿真", simulated=True)

    def _start_connection(self, factory, label, simulated=False):
        self._reset_connection_view()
        self.connecting, self.simulated = True, simulated
        self.generation = self.worker.connect(factory, label)
        self.connection.set("● 连接中")
        self.notice.set(f"正在连接 {label}…")
        self._serial_log("INFO", f"连接请求：{label}")
        self._update_controls()

    def _reset_connection_view(self):
        self._clear_motion()
        self._cancel_timer("poll_timer")
        self.connected = self.connecting = self.simulated = self.ready = False
        self._initializing = False
        self.last_state = ""
        self.pwm_limit_supported = None
        self._render_pwm_limit(300)
        self.servo_supported = None
        self._render_servo(ServoSettings(), None, confirmed=False)
        self.servo_flash_status.set("尚未读取舵机校准")
        self._pending.clear()
        for variable in (self.state, self.fault, self.obstacles, self.motors, self.steer,
                         *self.ranges, *self.pid_vars, *self.speed_targets,
                         *self.speed_measured, *self.speed_pwm):
            variable.set("—")
        self.hardware_info.set("未读取")
        self.line_info.set("CH1 → CH8 · 实心表示识别到线")
        self.control_info.set("连接后显示目标和实测速度")
        self.flash_status.set("尚未读取参数")
        self.view.sensor_strip.redraw(clear=True)
        for chart in self.view.speed_charts:
            chart.clear()

    def _disconnect(self):
        self.generation = self.worker.disconnect()
        self._reset_connection_view()
        self.connection.set("● 未连接")
        self.notice.set("已断开。调试模式会尝试停车；自动模式按车端流程继续运行。")
        self._update_controls()

    def _drain_events(self):
        if self.closed:
            return
        for event in self.worker.drain():
            if event.generation != self.generation:
                continue
            if event.kind == "log":
                self._serial_log(event.direction, event.message)
            elif event.kind == "progress":
                self.notice.set(event.message)
                self._serial_log("INFO", event.message)
            elif event.kind == "connected":
                self.connected, self.connecting = True, False
                self._initializing = True
                self.connection.set(f"● {event.data}")
                self._serial_log("INFO", f"固件握手通过：PONG 2 · {event.data}")
                self.notice.set("连接成功，正在读取硬件状态与参数。")
                self._read_hardware()
                self._load_pid()
                self._read_servo()
                self._read_pwm_limit()
                self._refresh()
            elif event.kind == "result":
                self._pending.discard(event.key)
                self._handle_result(event.key, event.data)
            elif event.kind == "error":
                self._pending.discard(event.key)
                self._initializing = False
                self._serial_log("ERROR", str(event.error))
                self.notice.set(str(event.error))
                if event.fatal:
                    self._reset_connection_view()
                    self.connection.set("● 通信中断")
                elif event.key == "drive":
                    self._drive_release()
                elif event.key == "tune":
                    self._pending.clear()
                    self._load_pid()
                    self._refresh()
                elif event.key == "pwm_unlock":
                    self._pending.intersection_update({"stop"})
                    self._read_pwm_limit()
                    self._refresh()
                elif event.key == "servo":
                    self._read_servo()
                    self._refresh()
                elif event.key == "telemetry":
                    self._schedule_poll()
            if self._initializing and not self._pending:
                self._initializing = False
                if not self.ready:
                    self.notice.set("硬件未就绪，查看车辆状态中的失败阶段。")
                elif self.fault.get() == "无":
                    self.notice.set("连接正常 · 实时监测中。")
            self._update_controls()
        self.event_timer = self.root.after(40, self._drain_events)

    def _handle_result(self, key, data):
        if key == "telemetry":
            self._render_telemetry(*data[:2])
            if len(data) > 2 and data[2] is not None:
                self._render_pwm_limit(data[2], confirmed=True)
            self._schedule_poll()
        elif key == "pwm_limit_read":
            self._render_pwm_limit(data, confirmed=True)
        elif key in ("servo", "servo_read"):
            self._render_servo(*data)
            if key == "servo":
                self.notice.set("舵机校准操作完成，已读回车端中位与对称限幅。")
                self._refresh()
        elif key == "pwm_unlock":
            self._pending.intersection_update({"stop"})
            limit, status, control = data
            self._render_telemetry(status, control)
            self._render_pwm_limit(limit, confirmed=True)
            self.notice.set(f"测试上限已读回为 {limit / 10:g}%。当前电机停止，按住测试按钮才输出。")
            self._schedule_poll()
        elif key in ("pid", "pid_read", "tune"):
            settings, saved = data
            for name, variable in zip(PID_NAMES, self.pid_vars):
                variable.set(f"{settings.values[name]:.3f}")
            if self._initializing:
                self.test_left.set(f"{settings.values['target_ticks']:.3f}")
                self.test_right.set(f"{settings.values['target_ticks']:.3f}")
            self.flash_status.set("当前参数已保存到 Flash" if saved else "当前运行参数未保存到 Flash")
            if key == "pid":
                self.notice.set("参数操作完成，已读回车端当前值。")
            elif key == "tune":
                self._pending.clear()
                self.last_state = "IDLE"
                self.state.set(STATE_LABELS["IDLE"])
                self._render_pwm_limit(300)
                self.notice.set("已停车并应用电机参数。进入调试后按住轮速测试，观察响应。")
                self._refresh()
        elif key == "hardware":
            self.ready = bool(data and data.ready)
            self.hardware_info.set(HARDWARE_LABELS.get(data.stage, data.stage) if data
                                   else "旧固件不支持 HW?，请更新固件")
        elif key == "line":
            raw = "".join(str((data.raw_bits >> i) & 1) for i in range(8))
            self.line_info.set(f"OUT {raw} · 黑线电平 {data.black_level} · "
                               f"{data.settle_us} µs / 路 · 缓存 {data.age_ms} ms")
        elif key in ("mode", "stop"):
            if key == "mode" and data is not None:
                self._render_servo(*data)
            if key == "stop":
                self._pending.clear()
                self.last_state = "IDLE" if self.ready else "FAULT"
                self.state.set(STATE_LABELS[self.last_state])
                self._render_pwm_limit(300)
                self._read_hardware()
                self._load_pid()
                self._read_servo()
            self.notice.set("停车指令已确认。" if key == "stop" else "模式指令已确认。")
            self._read_pwm_limit()
            self._refresh()
        elif key == "raw":
            self.notice.set(f"车端响应：{data}")
            self._read_servo()
            self._refresh()
        elif key == "sim_input":
            self.notice.set("已更新仿真输入。")
            self._refresh()

    def _schedule_poll(self):
        self._cancel_timer("poll_timer")
        if self.connected:
            self.poll_timer = self.root.after(250 if self._holding else 500, self._refresh)

    def _refresh(self):
        self._cancel_timer("poll_timer")
        def read(client):
            status, control = client.status(), client.control()
            # Only new firmware needs the extra query. It detects a board-side
            # watchdog relock without trusting a stale GUI unlock checkbox.
            limit = client.debug_limit() if self.pwm_limit_supported else None
            return status, control, limit
        self._queue("telemetry", read, coalesce=True)

    def _render_pwm_limit(self, limit, *, confirmed=False):
        if limit is None:
            if self.pwm_limit_supported is None:
                self.pwm_limit_supported = False
            self.debug_pwm_limit = 300
            self.pwm_limit_info.set("当前上限 30% · 旧固件不支持解锁，请烧录新版固件")
        else:
            self.debug_pwm_limit = limit
            if confirmed:
                self.pwm_limit_supported = True
            if self.pwm_limit_supported is False:
                self.pwm_limit_info.set("当前上限 30% · 旧固件不支持解锁，请烧录新版固件")
            else:
                self.pwm_limit_info.set(f"当前测试上限 {limit / 10:g}% · " +
                                       ("已解锁" if limit > 300 else "默认范围"))
        self.view.set_pwm_limit(self.debug_pwm_limit)

    def _read_pwm_limit(self):
        def read(client):
            reply = client.request("DEBUG LIMIT?")
            return None if reply == "ERR COMMAND" else parse_debug_limit(reply)
        self._queue("pwm_limit_read", read, coalesce=True)

    def _render_servo(self, settings, saved, *, confirmed=True):
        if settings is None:
            self.servo_supported = False
            settings = ServoSettings()
            self.servo_flash_status.set("旧固件不支持舵机校准，请更新固件；沿用 1500 ± 200 µs")
        else:
            if confirmed:
                self.servo_supported = True
            self.servo_flash_status.set("当前舵机校准已保存到 Flash" if saved else "当前舵机校准未保存到 Flash")
        previous_center = self.servo_settings.center_us
        self.servo_settings = settings
        self.servo_center.set(str(settings.center_us))
        self.servo_span.set(str(settings.span_us))
        low, center, high = settings.minimum_us, settings.center_us, settings.maximum_us
        self.servo_bounds_info.set(f"车端当前：左端 / 中位 / 右端 = {low} / {center} / {high} µs"
                                  f"（{low / 1000:.3f} / {center / 1000:.3f} / {high / 1000:.3f} ms）")
        try:
            pulse = self.drive_steer.get()
            if pulse == previous_center or not low <= pulse <= high:
                self.drive_steer.set(center)
        except tk.TclError:
            self.drive_steer.set(center)
        try:
            turn = self.remote_turn.get()
            self.remote_turn.set(max(0, min(settings.span_us, turn)))
        except tk.TclError:
            self.remote_turn.set(min(120, settings.span_us))
        self.view.set_servo_limits(settings)

    @staticmethod
    def _servo_snapshot(client):
        response = client.request("SERVO?")
        if response == "ERR COMMAND":
            client.servo_settings = ServoSettings()
            return None, None
        settings = ServoSettings.parse(response)
        client.servo_settings = settings
        return settings, client.servo_saved()

    def _read_servo(self):
        self._queue("servo_read", self._servo_snapshot, coalesce=True)

    def _servo_action(self, action, *args):
        if (not self.connected or not self.ready or self.last_state != "IDLE" or
                self.servo_supported is not True or self._busy() or self._holding):
            self.notice.set("舵机校准需要连接支持此功能的固件，硬件正常且处于待机。")
            return
        def apply(client):
            getattr(client, action)(*args)
            return self._servo_snapshot(client)
        self._queue("servo", apply)

    def _apply_servo(self):
        try:
            settings = ServoSettings(int(self.servo_center.get()), int(self.servo_span.get()))
        except (ValueError, tk.TclError):
            self.notice.set("中位、半摆幅须填写整数 µs；半摆幅 0–1000，中位 ± 半摆幅须在 500–2500 µs。")
            return
        self._servo_action("set_servo", settings.center_us, settings.span_us)

    def _save_servo(self):
        self._servo_action("save_servo")

    def _restore_servo(self):
        self._servo_action("load_servo")

    def _reset_servo(self):
        self._servo_action("reset_servo")

    def _fill_servo_pulse(self, position):
        settings = self.servo_settings
        self.drive_steer.set({"left": settings.minimum_us, "center": settings.center_us,
                              "right": settings.maximum_us}[position])
        self.notice.set("已填入手动调舵目标；进入调试后按住驱动 / 调舵按钮才输出。")

    def _unlock_pwm(self):
        if (not self.connected or not self.ready or self._busy() or self._holding or
                self.last_state not in ("IDLE", "DEBUG") or self.pwm_limit_supported is not True):
            self.notice.set("请先连接新版固件并停车，再设置测试上限。")
            return
        try:
            percent = float(self.pwm_limit_percent.get())
            if not math.isfinite(percent) or not 1 <= percent <= 100:
                raise ValueError()
            limit = round(percent * 10)
        except (ValueError, tk.TclError):
            self.notice.set("PWM 测试上限请填写 1–100%；100% 是最大占空比。")
            return
        self._clear_motion()
        def unlock(client):
            client.stop()
            client.debug()
            client.set_debug_limit(limit)
            actual = client.debug_limit()
            if actual != limit:
                client.stop()
                raise RuntimeError("车端 PWM 上限读回不一致，已停车。")
            return actual, client.status(), client.control()
        self._queue("pwm_unlock", unlock, priority=True, cancel_drives=True)

    def _render_telemetry(self, status, control):
        previous_state = self.last_state
        self.last_state = status.state
        self.state.set(STATE_LABELS.get(status.state, status.state))
        self.fault.set(FAULT_LABELS[status.fault] if status.fault < len(FAULT_LABELS)
                       else str(status.fault))
        if status.state != "DEBUG":
            self._clear_motion()
            self._render_pwm_limit(300)
        if (self.servo_supported is True and status.state in ("IDLE", "FAULT", "FINISHED") and
                status.steer_us != self.servo_settings.center_us):
            # A board can reboot without closing its Bluetooth/USB session.
            self._read_servo()
        if status.fault == 6 and previous_state != "FAULT":
            self._read_hardware()
        for variable, value in zip(self.ranges, (status.left_mm, status.center_mm, status.right_mm)):
            variable.set("无效" if value is None else str(value))
        self.obstacles.set(str(status.obstacles))
        self.motors.set(f"左 {status.motor_left:+d}  /  右 {status.motor_right:+d} ‰")
        self.steer.set(f"{status.steer_us} µs")
        self.view.sensor_strip.redraw(status.line_bits)
        for variable, value in zip(self.speed_targets, (control.left_target, control.right_target)):
            variable.set(f"{value:.2f}")
        for variable, value in zip(self.speed_measured, (control.left_measured, control.right_measured)):
            variable.set(f"{value:.2f}")
        for variable, value in zip(self.speed_pwm, (control.left_pwm, control.right_pwm)):
            variable.set(f"{value:+d}")
        for chart in self.view.speed_charts:
            chart.add(control)
        self.control_info.set(f"目标 L {control.left_target:.1f} / R {control.right_target:.1f}"
                              f"   实测 L {control.left_measured} / R {control.right_measured}"
                              f"   编码器 {status.encoder_left_delta} / {status.encoder_right_delta}")
        if status.fault:
            self.notice.set(f"车端提示：{self.fault.get()}。停车后检查硬件与传感器。")

    def _read_hardware(self):
        def read(client):
            response = client.request("HW?")
            return None if response == "ERR COMMAND" else HardwareStatus.parse(response)
        self._queue("hardware", read)

    def _read_line(self):
        self._queue("line", lambda client: client.line_diagnostics())

    @staticmethod
    def _pid_snapshot(client):
        return client.pid(), client.pid_saved()

    def _load_pid(self):
        self._queue("pid_read", self._pid_snapshot)

    def _pid_action(self, action, *args):
        if not self.connected or self.last_state != "IDLE" or not self.ready:
            self.notice.set("PID 修改需要车端硬件正常且处于待机。")
            return
        def apply(client):
            getattr(client, action)(*args)
            return self._pid_snapshot(client)
        self._queue("pid", apply)

    def _apply_pid(self, index):
        try:
            value = float(self.pid_vars[index].get())
        except ValueError:
            self.notice.set("参数需要填写数字。")
            return
        self._pid_action("set_pid", PID_NAMES[index], value)

    def _tune_motor_pid(self):
        if not self.connected or not self.ready or self.last_state not in ("IDLE", "DEBUG") or self._busy():
            self.notice.set("请先停车或进入调试，并确认硬件正常。")
            return
        updates = []
        try:
            for index in (3, 4, 5, 6, 7):
                value = float(self.pid_vars[index].get())
                if (not math.isfinite(value) or not 0 <= value <= PID_LIMITS[index] or
                        (index == 6 and float(f"{value:.3f}") <= 0)):
                    raise ValueError()
                updates.append((PID_NAMES[index], value))
        except ValueError:
            self.notice.set("电机参数超出范围：Kp/Ki 0–50、Kd 0–10、基准目标 >0–500、前馈 PWM 0–500‰。")
            return
        self._clear_motion()
        def apply(client):
            client.stop()
            for name, value in updates:
                client.set_pid(name, value)
            return self._pid_snapshot(client)
        self._queue("tune", apply, priority=True, cancel_drives=True)

    def _enable_debug(self):
        if (not self.connected or not self.ready or self._busy() or
                self.last_state not in ("IDLE", "DEBUG", "FINISHED", "FAULT")):
            self.notice.set("自动运行中请先停车，再进入遥控 / 轮速测试。")
            return
        self._clear_motion()
        def enable(client):
            client.stop()
            calibration = self._servo_snapshot(client) if self.servo_supported is True else None
            client.debug()
            return calibration
        self._queue("mode", enable)

    def _save_pid(self):
        self._pid_action("save_pid")

    def _restore_pid(self):
        self._pid_action("load_pid")

    def _reset_pid(self):
        self._pid_action("reset_pid")

    def _command(self, name):
        if not self.ready or self.last_state != "IDLE":
            self.notice.set("请先停车至待机，并确认硬件初始化正常。")
            return
        if name == "debug":
            return self._enable_debug()
        self._queue("mode", lambda client: getattr(client, name)())

    def _stop(self):
        self._clear_motion()
        return self._queue("stop", lambda client: client.stop(), priority=True)

    def _drive_press(self, _event=None):
        self._start_hold("manual")

    def _start_hold(self, source):
        if not self.connected or not self.ready or self.last_state != "DEBUG" or self._busy():
            self.notice.set("请先进入调试；自动运行中不能遥控或试跑。")
            return
        self._motion_source = source
        self._holding = True
        self._update_controls()
        self._drive_tick()

    def _remote_press(self, direction, _event=None):
        self._remote_direction = direction
        self._start_hold("remote")

    def _speed_press(self, _event=None):
        self._start_hold("speed")

    def _drive_tick(self):
        if not self._holding or not self.connected or self.last_state != "DEBUG":
            return
        try:
            if self._motion_source == "speed":
                values = float(self.test_left.get()), float(self.test_right.get())
                if any(not math.isfinite(v) or not 0 <= v <= 500 for v in values):
                    raise ValueError()
                operation = lambda client: client.speed(*values)
            else:
                if self._motion_source == "remote":
                    pwm, turn = self.remote_pwm.get(), self.remote_turn.get()
                    if not 0 <= pwm <= 300 or not 0 <= turn <= 1000:
                        raise ValueError()
                    turn = min(turn, self.servo_settings.span_us)
                    throttle, steering = self._remote_direction
                    values = throttle * pwm, throttle * pwm, self.servo_settings.center_us + steering * turn
                else:
                    percentages = self.drive_left.get(), self.drive_right.get()
                    if not all(math.isfinite(v) and abs(v) <= self.debug_pwm_limit / 10
                               for v in percentages):
                        raise ValueError()
                    values = *(round(v * 10) for v in percentages), self.drive_steer.get()
                    if not self.servo_settings.minimum_us <= values[2] <= self.servo_settings.maximum_us:
                        raise ValueError()
                operation = lambda client: client.drive(*values)
        except (tk.TclError, ValueError):
            self.notice.set(f"手动 PWM 须在 ±{self.debug_pwm_limit / 10:g}% 内；遥控最高 30%；"
                            f"舵机 {self.servo_settings.minimum_us}–{self.servo_settings.maximum_us} µs；"
                            "轮速目标 0–500 计数 / 10 ms。")
            self._drive_release()
            return
        self._queue("drive", operation, coalesce=True, priority=True)
        self._cancel_timer("drive_timer")
        self.drive_timer = self.root.after(200, self._drive_tick)

    def _drive_release(self, _event=None):
        was_holding = self._holding
        self._clear_motion()
        if was_holding and self.connected and self.last_state == "DEBUG":
            self._queue("drive", lambda client: client.drive(0, 0, self.servo_settings.center_us),
                        coalesce=True, priority=True, cancel_drives=True)
        self._update_controls()

    def _clear_motion(self):
        self._holding = False
        self._motion_source = ""
        self._cancel_timer("drive_timer")
        self._blocked_keys.update(self._remote_keys)
        self._remote_keys.clear()
        for timer in self._key_timers.values():
            self.root.after_cancel(timer)
        self._key_timers.clear()

    def _remote_brake(self):
        self._clear_motion()
        if self.connected and self.last_state == "DEBUG":
            self._queue("drive", lambda client: client.drive(0, 0, self.servo_settings.center_us),
                        coalesce=True, priority=True, cancel_drives=True)
        self._update_controls()

    def _tab_changed(self, _event=None):
        allowed = {"remote": self.view.remote_page, "manual": self.view.debug_page,
                   "speed": self.view.pid_page}.get(self._motion_source)
        if self._holding and str(self.view.tabs.select()) != str(allowed):
            self._drive_release()

    def _key_press(self, event):
        key = event.keysym.lower()
        if key not in ("w", "a", "s", "d", "up", "left", "down", "right", "space"):
            return
        # Tcl-created widgets (notably a ttk.Combobox popdown) are delivered
        # by Tkinter as path strings because they have no Python wrapper.
        widget_class = self._widget_class(str(event.widget))
        if (str(self.view.tabs.select()) != str(self.view.remote_page) or
                not widget_class or widget_class in ("Entry", "TEntry", "Spinbox", "TSpinbox",
                                                      "TCombobox", "ComboboxPopdown", "Listbox", "Text") or
                event.state & 0x000C):
            return
        if key == "space":
            self._remote_brake()
            return "break"
        if key in self._blocked_keys or self._busy() or self.last_state != "DEBUG" or not self.ready:
            return
        timer = self._key_timers.pop(key, None)
        if timer:
            self.root.after_cancel(timer)
        self._remote_keys.add(key)
        self._update_key_direction()
        return "break"

    def _key_release(self, event):
        key = event.keysym.lower()
        if key not in self._remote_keys and key not in self._blocked_keys:
            return
        timer = self._key_timers.pop(key, None)
        if timer:
            self.root.after_cancel(timer)
        self._key_timers[key] = self.root.after(30, lambda: self._finish_key_release(key))

    def _finish_key_release(self, key):
        self._key_timers.pop(key, None)
        self._blocked_keys.discard(key)
        self._remote_keys.discard(key)
        self._update_key_direction()

    def _update_key_direction(self):
        if not self._remote_keys:
            if self._motion_source == "remote":
                self._drive_release()
            return
        keys = self._remote_keys
        direction = (int(bool(keys & {"w", "up"})) - int(bool(keys & {"s", "down"})),
                     int(bool(keys & {"d", "right"})) - int(bool(keys & {"a", "left"})))
        if self._holding and self._motion_source == "remote" and direction == self._remote_direction:
            return
        self._remote_direction = direction
        self._start_hold("remote")

    def _focus_out(self, _event=None):
        self.root.after_idle(self._check_focus)

    def _widget_class(self, path):
        if not path or not self.root.tk.call("winfo", "exists", path):
            return ""
        return str(self.root.tk.call("winfo", "class", path))

    def _focus_is_local(self, path):
        if not self._widget_class(path):
            return False
        top = str(self.root.tk.call("winfo", "toplevel", path))
        if top == str(self.root):
            return True
        # A native combobox popdown is a separate Tcl toplevel whose logical
        # parent is the combobox. A different application/dialog toplevel
        # counts as leaving the driving window and must stop held motion.
        if self._widget_class(top) == "ComboboxPopdown":
            owner = str(self.root.tk.call("winfo", "parent", top))
            return (self._widget_class(owner) == "TCombobox" and
                    str(self.root.tk.call("winfo", "toplevel", owner)) == str(self.root))
        return False

    def _check_focus(self):
        if self.closed:
            return
        # focus_displayof() calls _nametowidget(), which raises KeyError for
        # native Tcl popdowns. Query paths without converting them to widgets.
        path = str(self.root.tk.call("focus", "-displayof", str(self.root)))
        if not self._focus_is_local(path):
            self._drive_release()

    def _apply_sim(self):
        bits = self.sim_line.get().strip()
        try:
            ranges = tuple(variable.get() for variable in self.sim_ranges)
        except tk.TclError:
            self.notice.set("仿真距离需要填写整数。")
            return
        if len(bits) != 8 or set(bits) - {"0", "1"} or any(not 0 <= n <= 6000 for n in ranges):
            self.notice.set("仿真灰度需要 8 位 0/1；距离范围为 0–6000 mm。")
            return
        if not self.simulated:
            return
        def apply(client):
            client.link.line_bits = int(bits[::-1], 2)
            client.link.left_mm, client.link.center_mm, client.link.right_mm = ranges
        self._queue("sim_input", apply)

    def _send_raw(self, command):
        if command.strip().upper() in ("STOP", "IDLE"):
            return self._stop()
        return self._queue("raw", lambda client: client.request(command))

    def _send_serial_command(self, _event=None):
        command = self.serial_command.get().strip()
        if command and self._send_raw(command):
            self.serial_command.set("")

    def _refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports = list(list_ports.comports())
        except ImportError:
            self.port_hint.set("缺少 pyserial；安装 host/requirements.txt 后可连接串口")
            return
        def priority(port):
            details = " ".join(str(getattr(port, name, "") or "")
                               for name in ("description", "hwid", "manufacturer")).upper()
            if "CH340" in details or "CH341" in details or "1A86:7523" in details:
                rank = 0
            elif "BTHENUM" in details or "BLUETOOTH" in details or "蓝牙" in details:
                rank = 3
            elif "USB" in details:
                rank = 1
            else:
                rank = 2
            device = str(port.device).upper()
            number = int(device[3:]) if device.startswith("COM") and device[3:].isdigit() else 1000
            return rank, number, device
        ports.sort(key=priority)
        self._ports = {str(port.device).upper(): port for port in ports}
        self.view.port_picker.configure(values=[port.device for port in ports])
        selected = self.port.get().strip().upper()
        if selected in self._ports:
            self.port.set(self._ports[selected].device)
        else:
            self.port.set(ports[0].device if ports else "")
        self._update_port_hint()

    def _update_port_hint(self):
        if self.transport.get() == "旧 BT24 BLE":
            self.port_hint.set("旧 BT24 需安装可选 BLE 依赖；JDY-31 使用 SPP COM 口。")
            return
        selected = self.port.get().strip().upper()
        if not selected:
            self.port_hint.set("未检测到 COM 端口；连接板载 CH340 / USB-TTL，或使用仿真。")
            return
        info = self._ports.get(selected)
        description = (str(getattr(info, "description", "") or "串口设备") if info
                       else "未在当前列表中检测到")
        self.port_hint.set(f"{selected} · {description} · 9600 bps · 8N1 · "
                           "板载 CH340：USART1；JDY-31 / 外置 TTL：USART3")

    def _serial_log(self, direction, message):
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"{stamp}  {direction:<5}  {message}"
        self._logs.append(line)
        widget = self.view.serial_text
        at_bottom = widget.yview()[1] >= .99
        widget.configure(state="normal")
        widget.insert("end", line + "\n", direction)
        lines = int(widget.index("end-1c").split(".")[0])
        if lines > 500:
            widget.delete("1.0", f"{lines - 500}.0")
        widget.configure(state="disabled")
        if at_bottom:
            widget.see("end")

    def _clear_log(self):
        self._logs.clear()
        self.view.serial_text.configure(state="normal")
        self.view.serial_text.delete("1.0", "end")
        self.view.serial_text.configure(state="disabled")

    def _export_log(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="导出通信日志",
                                          defaultextension=".txt",
                                          initialfile=datetime.now().strftime("if_car_%Y%m%d_%H%M%S.txt"),
                                          filetypes=[("文本日志", "*.txt")])
        if path:
            try:
                with open(path, "w", encoding="utf-8") as output:
                    output.write("\n".join(self._logs) + "\n")
                self.notice.set("通信日志已导出。")
            except OSError as error:
                self.notice.set(f"导出失败：{error}")

    def _close(self):
        self.closed = True
        self._clear_motion()
        for name in ("drive_timer", "poll_timer", "event_timer"):
            self._cancel_timer(name)
        self.worker.shutdown()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
