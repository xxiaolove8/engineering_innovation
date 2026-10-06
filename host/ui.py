"""Tk views and visual widgets; communication lives in gui/session, never here."""

from collections import deque
import tkinter as tk
from tkinter import ttk

from .protocol import PID_NAMES

BG = "#eef3f8"
CARD = "#ffffff"
INK = "#172b43"
MUTED = "#718096"
ACCENT = "#0d9488"
BLUE = "#4285ed"
RED = "#d44b55"
FONT = "Microsoft YaHei UI"

PID_FIELDS = (
    ("比例 Kp", ""), ("积分 Ki", ""), ("微分 Kd", ""),
    ("比例 Kp", ""), ("积分 Ki", ""), ("微分 Kd", ""),
    ("基准目标速度", "计数 / 10 ms"), ("前馈 PWM", "‰"),
    ("转弯差速", "0–1"), ("弯道减速", "0–1"),
)


class ScrollPage(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, height=420)
        scroll = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, padding=(3, 14, 12, 10))
        item = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(item, width=e.width))


class SensorStrip(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, height=110, bg=CARD, highlightthickness=0)
        self.bits = None
        self.bind("<Configure>", lambda _e: self.redraw())

    def redraw(self, bits=None, *, clear=False):
        if bits is not None or clear:
            self.bits = bits
        self.delete("all")
        width = max(self.winfo_width(), 400)
        step = (width - 40) / 8
        self.create_line(20, 43, width - 20, 43, fill="#e7eef5", width=8)
        for i in range(8):
            x = 20 + step * (i + .5)
            active = self.bits is not None and self.bits & (1 << i)
            self.create_oval(x-18, 25, x+18, 61, fill=ACCENT if active else "#e7eef5", outline="")
            self.create_text(x, 44, text="1" if active else "0" if self.bits is not None else "·",
                             fill="white" if active else MUTED, font=("Consolas", 12, "bold"))
            self.create_text(x, 82, text=f"CH{i+1}", fill=MUTED, font=(FONT, 9))


class SpeedChart(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, height=130, bg=CARD, highlightthickness=0)
        self.samples = deque(maxlen=80)
        self.bind("<Configure>", lambda _e: self.redraw())

    def add(self, control):
        self.samples.append((control.left_measured, control.right_measured, control.left_target, control.right_target))
        self.redraw()

    def clear(self):
        self.samples.clear()
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 400), max(self.winfo_height(), 130)
        for y in (20, 60, 100):
            self.create_line(34, y, w-12, y, fill="#e8eef5")
        if not self.samples:
            self.create_text(w/2, h/2, text="连接后显示轮速趋势", fill=MUTED, font=(FONT, 10))
            return
        maximum = max(1., *(max(sample) for sample in self.samples)) * 1.15
        self.create_text(16, 18, text=f"{maximum:.0f}", fill=MUTED, font=("Consolas", 8))
        self.create_text(18, h-18, text="0", fill=MUTED, font=("Consolas", 8))
        for series, color in ((2, "#afdcd6"), (3, "#c1d5fa"), (0, ACCENT), (1, BLUE)):
            points = []
            for i, sample in enumerate(self.samples):
                points.extend((34+i*(w-48)/79, h-20-max(0, sample[series])*(h-40)/maximum))
            if len(points) >= 4:
                self.create_line(*points, fill=color, width=2, dash=(4, 3) if series>1 else ())


class DashboardView:
    def __init__(self, app):
        self.app = app
        self.buttons = {}
        self.speed_charts = []
        self.scroll_pages = []
        self._style(app.root)
        self._build(app)

    @staticmethod
    def _style(root):
        root.configure(bg=BG)
        root.option_add("*Font", (FONT, 10))
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=(FONT, 10), background=BG, foreground=INK)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Card.TLabel", background=CARD)
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
        style.configure("Heading.TLabel", background=CARD, font=(FONT, 12, "bold"))
        style.configure("Metric.TLabel", background=CARD, foreground=INK, font=("Consolas", 23, "bold"))
        style.configure("TButton", background="#e7eef5", borderwidth=0, padding=(13, 8))
        style.map("TButton", background=[("active", "#dae5ef"), ("disabled", "#eff3f7")],
                  foreground=[("disabled", "#a6b3c1")])
        for name, color in (("Accent", ACCENT), ("Danger", RED)):
            style.configure(f"{name}.TButton", background=color, foreground="white", font=(FONT, 10, "bold"))
            style.map(f"{name}.TButton", background=[("disabled", "#d7e0e9"), ("active", color)],
                      foreground=[("disabled", "#8d9dac")])
        style.configure("TEntry", fieldbackground="#f7f9fc", padding=7, borderwidth=1)
        style.configure("TSpinbox", fieldbackground="#f7f9fc", padding=6)
        style.configure("TCombobox", fieldbackground="#f7f9fc", padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", "#f7f9fc")])
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 8, 0, 0))
        style.configure("TNotebook.Tab", padding=(22, 10), background=BG, foreground=MUTED)
        style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", ACCENT)])
        style.configure("TCheckbutton", background=CARD)

    def card(self, parent, title, subtitle=None):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=18)
        ttk.Label(frame, text=title, style="Heading.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(frame, text=subtitle, style="Muted.TLabel", wraplength=650).pack(anchor="w", pady=(4, 12))
        return frame

    def button(self, parent, text, command, key=None, style="TButton", **kw):
        button = ttk.Button(parent, text=text, command=command, style=style, **kw)
        if key:
            self.buttons[key] = button
        return button

    def metric(self, parent, title, variable, note, column):
        frame = self.card(parent, title)
        frame.grid(row=0, column=column, sticky="nsew", padx=(0, 10) if column<3 else 0)
        ttk.Label(frame, textvariable=variable, style="Metric.TLabel").pack(anchor="w", pady=(8, 4))
        ttk.Label(frame, text=note, style="Muted.TLabel").pack(anchor="w")
        parent.columnconfigure(column, weight=1, uniform="metrics")

    def _build(self, a):
        header = tk.Frame(a.root, bg=INK, padx=24, pady=18)
        header.pack(fill="x")
        brand = tk.Frame(header, bg=INK)
        brand.pack(side="left")
        tk.Label(brand, text="循迹控制台", bg=INK, fg="white", font=(FONT, 20, "bold")).pack(anchor="w")
        tk.Label(brand, text="STM32 F407  /  赛前调试与车辆监测", bg=INK, fg="#a7b9cf", font=(FONT, 9)).pack(anchor="w", pady=(4, 0))
        self.button(header, "停止 / 待机  Esc", a._stop, "stop", "Danger.TButton").pack(side="right", padx=(14, 0))
        self.badge = tk.Label(header, textvariable=a.connection, bg="#28405b", fg="#d8e8f6", padx=14, pady=8,
                              font=(FONT, 9), wraplength=320)
        self.badge.pack(side="right")
        outer = ttk.Frame(a.root, padding=(22, 14, 22, 8))
        outer.pack(fill="both", expand=True)
        connection = ttk.Frame(outer, style="Card.TFrame", padding=(16, 12))
        connection.pack(fill="x")
        ttk.Label(connection, text="连接方式", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.transport_picker = ttk.Combobox(connection, textvariable=a.transport,
            values=("串口（USB / JDY-31）", "旧 BT24 BLE"), width=20, state="readonly")
        self.transport_picker.grid(row=1, column=0, padx=(0, 10), pady=(4, 0))
        self.transport_picker.bind("<<ComboboxSelected>>", lambda _e: self.show_transport())
        self.serial_fields = ttk.Frame(connection, style="Card.TFrame")
        self.serial_fields.grid(row=0, column=1, rowspan=2, sticky="w")
        ttk.Label(self.serial_fields, text="出站 SPP / USB 串口", style="Muted.TLabel").pack(anchor="w")
        ports = ttk.Frame(self.serial_fields, style="Card.TFrame")
        ports.pack(pady=(4, 0))
        self.port_picker = ttk.Combobox(ports, textvariable=a.port, width=11, postcommand=a._refresh_ports)
        self.port_picker.pack(side="left")
        self.button(ports, "刷新", a._refresh_ports).pack(side="left", padx=7)
        self.ble_fields = ttk.Frame(connection, style="Card.TFrame")
        ttk.Label(self.ble_fields, text="设备名称 / 地址", style="Muted.TLabel").pack(anchor="w")
        ble_row = ttk.Frame(self.ble_fields, style="Card.TFrame")
        ble_row.pack(pady=(4, 0))
        ttk.Entry(ble_row, textvariable=a.ble_target, width=18).pack(side="left")
        ttk.Combobox(ble_row, textvariable=a.ble_channel, values=("FFE1", "FFE2"), state="readonly", width=6).pack(side="left", padx=7)
        controls = ttk.Frame(connection, style="Card.TFrame")
        controls.grid(row=0, column=2, rowspan=2, sticky="e")
        self.button(controls, "连接设备", a._connect_selected, "connect", "Accent.TButton").pack(side="left", padx=(0, 7))
        self.button(controls, "界面仿真", a._connect_sim, "simulate").pack(side="left", padx=(0, 7))
        self.button(controls, "断开", a._disconnect, "disconnect").pack(side="left")
        connection.columnconfigure(2, weight=1)
        ttk.Label(connection, textvariable=a.port_hint, style="Muted.TLabel", wraplength=900).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        pages = []
        for name in ("实时监测", "遥控回车", "调试控制", "PID 调参"):
            page = ScrollPage(self.tabs)
            self.tabs.add(page, text=name)
            self.scroll_pages.append(page)
            pages.append(page.body)
        self._overview(pages[0], a)
        self.remote_page, self.debug_page, self.pid_page = self.scroll_pages[1:4]
        self._remote(pages[1], a)
        self._debug(pages[2], a)
        self._pid(pages[3], a)
        self._logs(a)
        ttk.Label(outer, textvariable=a.notice, foreground=MUTED, wraplength=1050).pack(anchor="w", pady=(7, 0))
        a.root.bind("<MouseWheel>", self._wheel, add="+")

    def show_transport(self):
        old_ble = self.app.transport.get() == "旧 BT24 BLE"
        self.serial_fields.grid_remove() if old_ble else self.ble_fields.grid_remove()
        if old_ble:
            self.ble_fields.grid(row=0, column=1, rowspan=2, sticky="w")
        else:
            self.serial_fields.grid(row=0, column=1, rowspan=2, sticky="w")
        self.app.port_hint.set("旧 BT24 需安装可选 BLE 依赖；JDY-31 使用 SPP COM 口。" if old_ble else
                               "板载 CH340 选择 USB 串口；JDY-31 先配对（密码 1234），选择出站 COM。两路均为 9600。")

    def _overview(self, page, a):
        metrics = ttk.Frame(page)
        metrics.pack(fill="x", pady=(0, 12))
        for col, entry in enumerate((("当前模式", a.state, "自动流程在车端执行"),
                                     ("左侧距离", a.ranges[0], "毫米 · 无回波显示无效"),
                                     ("正前方距离", a.ranges[1], "毫米 · 正前方障碍"),
                                     ("右侧距离", a.ranges[2], "毫米 · 右侧探头"))):
            self.metric(metrics, *entry, col)
        row = ttk.Frame(page)
        row.pack(fill="x")
        row.columnconfigure(0, weight=3, uniform="body")
        row.columnconfigure(1, weight=2, uniform="body")
        sensors = self.card(row, "八路巡线阵列", "从左到右 CH1–CH8，亮起表示识别到线")
        sensors.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.sensor_strip = SensorStrip(sensors)
        self.sensor_strip.pack(fill="x")
        ttk.Label(sensors, textvariable=a.line_info, style="Muted.TLabel", wraplength=530).pack(anchor="w", pady=6)
        self.button(sensors, "读取原始 OUT", a._read_line, "line").pack(anchor="w", pady=(6, 0))
        health = self.card(row, "车辆状态", "连接后持续读取车端反馈")
        health.grid(row=0, column=1, sticky="nsew")
        for title, variable in (("故障", a.fault), ("硬件", a.hardware_info), ("绕障次数", a.obstacles),
                                ("电机 L / R", a.motors), ("舵机脉宽", a.steer)):
            line = ttk.Frame(health, style="Card.TFrame")
            line.pack(fill="x", pady=5)
            ttk.Label(line, text=title, style="Muted.TLabel", width=12).pack(side="left")
            ttk.Label(line, textvariable=variable, style="Card.TLabel", wraplength=240).pack(side="left")
        speed = self.card(page, "轮速反馈", "实线为实测，虚线为目标；绿色为左轮，蓝色为右轮 · 计数 / 10 ms")
        speed.pack(fill="x", pady=(12, 0))
        self.speed_chart = SpeedChart(speed)
        self.speed_charts.append(self.speed_chart)
        self.speed_chart.pack(fill="x")
        ttk.Label(speed, textvariable=a.control_info, style="Muted.TLabel", wraplength=980).pack(anchor="w", pady=(8, 0))

    def _speed_monitor(self, parent, a, title="轮速监看"):
        card = self.card(parent, title, "计数 / 10 ms · 实测为绝对值；未标定轮径与编码器比例前不换算 m/s")
        readings = ttk.Frame(card, style="Card.TFrame")
        readings.pack(fill="x")
        for col, label in enumerate(("车轮", "目标", "实测", "PWM / ‰")):
            ttk.Label(readings, text=label, style="Muted.TLabel").grid(row=0, column=col, sticky="w", pady=(0, 5))
            readings.columnconfigure(col, weight=1)
        for row, label in enumerate(("左轮", "右轮"), 1):
            ttk.Label(readings, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=4)
            for col, variable in enumerate((a.speed_targets[row-1], a.speed_measured[row-1], a.speed_pwm[row-1]), 1):
                ttk.Label(readings, textvariable=variable, style="Card.TLabel",
                          font=("Consolas", 15, "bold")).grid(row=row, column=col, sticky="w")
        chart = SpeedChart(card)
        chart.pack(fill="x", pady=(10, 0))
        self.speed_charts.append(chart)
        ttk.Label(card, text="绿：左轮  蓝：右轮 · 实线实测，虚线目标 · 最近 80 次采样",
                  style="Muted.TLabel", wraplength=410).pack(anchor="w", pady=(6, 0))
        return card

    def _remote(self, page, a):
        top = self.card(page, "测试后遥控回车", "进入遥控后按住方向按钮，松开即停车。自动运行中先点击顶部停止。")
        top.pack(fill="x", pady=(0, 12))
        bar = ttk.Frame(top, style="Card.TFrame")
        bar.pack(fill="x")
        self.button(bar, "进入遥控", a._enable_debug, "remote_enable", "Accent.TButton").pack(side="left")
        ttk.Label(bar, textvariable=a.state, style="Card.TLabel").pack(side="left", padx=16)
        ttk.Label(bar, text="W / ↑ 前进  S / ↓ 倒车  A / ←、D / → 转舵  空格停车",
                  style="Muted.TLabel", wraplength=640).pack(side="right")
        row = ttk.Frame(page)
        row.pack(fill="x")
        row.columnconfigure(0, weight=1, uniform="remote")
        row.columnconfigure(1, weight=1, uniform="remote")
        pad = self.card(row, "方向控制", "左右键可与前进 / 倒车组合；转向按前轮舵向。")
        pad.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        settings = ttk.Frame(pad, style="Card.TFrame")
        settings.pack(fill="x", pady=(0, 10))
        self.remote_inputs = []
        for text, variable, low, high in (("动力 / ‰", a.remote_pwm, 0, 300),
                                          ("转舵 / µs", a.remote_turn, 0, 200)):
            cell = ttk.Frame(settings, style="Card.TFrame")
            cell.pack(side="left", padx=(0, 18))
            ttk.Label(cell, text=text, style="Muted.TLabel").pack(anchor="w")
            field = ttk.Spinbox(cell, from_=low, to=high, increment=10, textvariable=variable, width=10)
            field.pack(pady=(6, 0))
            self.remote_inputs.append(field)
        arrows = ttk.Frame(pad, style="Card.TFrame")
        arrows.pack(fill="x")
        directions = (
            ("↖ 前进 · 左舵", (1, -1), 0, 0), ("↑ 前进", (1, 0), 0, 1),
            ("↗ 前进 · 右舵", (1, 1), 0, 2), ("↙ 倒车 · 左舵", (-1, -1), 2, 0),
            ("↓ 倒车", (-1, 0), 2, 1), ("↘ 倒车 · 右舵", (-1, 1), 2, 2),
        )
        for text, direction, r, c in directions:
            button = self.button(arrows, text, None, f"remote:{r}:{c}", "Accent.TButton")
            button.grid(row=r, column=c, sticky="nsew", padx=3, pady=5)
            button.bind("<ButtonPress-1>", lambda event, d=direction: a._remote_press(d, event))
            button.bind("<ButtonRelease-1>", a._drive_release)
            button.bind("<Leave>", a._drive_release)
        self.button(arrows, "归零停车", a._remote_brake, "remote_brake").grid(
            row=1, column=0, columnspan=3, sticky="ew", padx=3, pady=5)
        for c in range(3):
            arrows.columnconfigure(c, weight=1, uniform="arrows")
        ttk.Label(pad, text="动力为直接 PWM，范围 0–300‰。失焦或切换页面归零；车端另有 500 ms 看门狗。",
                  style="Muted.TLabel", wraplength=410).pack(anchor="w", pady=(10, 0))
        self._speed_monitor(row, a, "回车速度与输出").grid(row=0, column=1, sticky="nsew")

    def _debug(self, page, a):
        modes = self.card(page, "运行模式", "自动预备后 3 秒自启；正式运行由 STM32 完成。")
        modes.pack(fill="x", pady=(0, 12))
        row = ttk.Frame(modes, style="Card.TFrame")
        row.pack(fill="x")
        self.button(row, "自动预备", lambda: a._command("arm"), "arm", "Accent.TButton").pack(side="left", padx=(0, 10))
        self.button(row, "进入调试", lambda: a._command("debug"), "debug").pack(side="left")
        limits = self.card(page, "PWM 全范围测试入口", "默认最高 30%；可显式设置到 100%。仅改变本次调试上限，解锁不会启动电机。")
        limits.pack(fill="x", pady=(0, 12))
        row = ttk.Frame(limits, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="测试上限 / %", style="Card.TLabel").pack(side="left", padx=(0, 10))
        self.pwm_limit_input = ttk.Spinbox(row, from_=1, to=100, increment=1,
                                         textvariable=a.pwm_limit_percent, width=8)
        self.pwm_limit_input.pack(side="left", padx=(0, 12))
        self.button(row, "停车并解锁此上限", a._unlock_pwm, "pwm_unlock", "Accent.TButton").pack(side="left", padx=(0, 10))
        self.button(row, "停车并恢复 30%", a._stop, "pwm_lock").pack(side="left")
        ttk.Label(limits, textvariable=a.pwm_limit_info, style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Label(limits, text="适用于下方手动 PWM 和 PID 轮速测试；遥控回车最高 30%。停止、退出调试或运动中通信超时后恢复 30%。",
                  style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(6, 0))
        manual = self.card(page, "手动台架调试", "仅调舵：左右电机设为 0，在当前校准范围内试验；按住输出，松开回到校准中位。")
        manual.pack(fill="x", pady=(0, 12))
        row = ttk.Frame(manual, style="Card.TFrame")
        row.pack(fill="x")
        self.drive_inputs = []
        for col, (title, var, low, high) in enumerate((("左电机 / %", a.drive_left, -30, 30),
                 ("右电机 / %", a.drive_right, -30, 30), ("舵机 / µs", a.drive_steer, 1300, 1700))):
            cell = ttk.Frame(row, style="Card.TFrame")
            cell.grid(row=0, column=col, sticky="w", padx=(0, 24))
            ttk.Label(cell, text=title, style="Muted.TLabel").pack(anchor="w", pady=(0, 7))
            spin = ttk.Spinbox(cell, from_=low, to=high, increment=1 if col < 2 else 10, textvariable=var, width=12)
            spin.pack(anchor="w")
            self.drive_inputs.append(spin)
        self.hold = self.button(row, "按住驱动 / 调舵", None, "drive", "Accent.TButton")
        self.hold.grid(row=0, column=3, sticky="s")
        self.hold.bind("<ButtonPress-1>", a._drive_press)
        self.hold.bind("<ButtonRelease-1>", a._drive_release)
        self.hold.bind("<Leave>", a._drive_release)
        endpoints = ttk.Frame(manual, style="Card.TFrame")
        endpoints.pack(fill="x", pady=(12, 0))
        for label, position in (("填入左端", "left"), ("填入中位", "center"), ("填入右端", "right")):
            self.button(endpoints, label, lambda p=position: a._fill_servo_pulse(p),
                        f"servo_pulse:{position}").pack(side="left", padx=(0, 10))
        ttk.Label(manual, textvariable=a.servo_bounds_info, style="Muted.TLabel",
                  wraplength=900).pack(anchor="w", pady=(10, 0))
        ttk.Label(manual, text="PWM 正负号控制方向，0% 停转；先抬起驱动轮。500 ms 看门狗继续生效，自动模式下不能手动驱动。", style="Muted.TLabel").pack(anchor="w", pady=(15, 0))
        simulator = self.card(page, "仿真输入", "仅修改界面仿真数据，便于核对协议和显示。")
        simulator.pack(fill="x")
        row = ttk.Frame(simulator, style="Card.TFrame")
        row.pack(fill="x")
        self.sim_inputs = []
        for title, var, limits in (("CH1 → CH8", a.sim_line, None), ("左 / mm", a.sim_ranges[0], (0, 6000)),
                                  ("中 / mm", a.sim_ranges[1], (0, 6000)), ("右 / mm", a.sim_ranges[2], (0, 6000))):
            cell = ttk.Frame(row, style="Card.TFrame")
            cell.pack(side="left", padx=(0, 20))
            ttk.Label(cell, text=title, style="Muted.TLabel").pack(anchor="w", pady=(0, 7))
            widget = ttk.Entry(cell, textvariable=var, width=12) if limits is None else ttk.Spinbox(
                cell, from_=limits[0], to=limits[1], textvariable=var, width=9)
            widget.pack()
            self.sim_inputs.append(widget)
        self.button(row, "应用输入", a._apply_sim, "sim_input").pack(side="left", anchor="s")

    def _pid(self, page, a):
        row = ttk.Frame(page)
        row.pack(fill="x")
        self.pid_inputs = []
        self.motor_pid_inputs = []
        for c in range(2):
            row.columnconfigure(c, weight=1, uniform="pid")
        motor = self.card(row, "电机速度 PID", "正式自动行驶使用此组参数；本页试跑目标在右侧独立设置。")
        motor.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        table = ttk.Frame(motor, style="Card.TFrame")
        table.pack(fill="x")
        for r, i in enumerate((3, 4, 5, 6, 7)):
            title, unit = PID_FIELDS[i]
            if i == 6:
                title = "自动基准速度"
            ttk.Label(table, text=title, style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=8)
            entry = ttk.Entry(table, textvariable=a.pid_vars[i], width=10)
            entry.grid(row=r, column=1, padx=10)
            self.motor_pid_inputs.append(entry)
            # Preserve individual idle-only application alongside the batch action.
            self.button(table, "应用", lambda n=i: a._apply_pid(n), f"pid:{PID_NAMES[i]}").grid(row=r, column=2)
            ttk.Label(table, text=unit, style="Muted.TLabel").grid(row=r, column=3, padx=6, sticky="w")
        self.button(motor, "停车并应用电机参数", a._tune_motor_pid, "tune", "Accent.TButton").pack(anchor="w", pady=(12, 0))
        ttk.Label(motor, text="应用后保持待机，不会自动续跑。Flash 保存仍须停车。",
                  style="Muted.TLabel", wraplength=410).pack(anchor="w", pady=(10, 0))
        ttk.Label(motor, text="基准速度：自动直行想达到的速度。前馈 PWM：在该速度下预计需要的输出。"
                  "例如基准 5、前馈 215‰，先给 21.5%，再由 PID 根据实测速度纠偏。测试目标改变时前馈按比例缩放。",
                  style="Muted.TLabel", wraplength=390).pack(anchor="w", pady=(10, 0))
        monitor = self._speed_monitor(row, a, "轮速响应 · 同页监看")
        monitor.grid(row=0, column=1, sticky="nsew")
        tests = ttk.Frame(monitor, style="Card.TFrame")
        tests.pack(fill="x", pady=(12, 0))
        self.speed_inputs = []
        for label, variable in (("左目标", a.test_left), ("右目标", a.test_right)):
            cell = ttk.Frame(tests, style="Card.TFrame")
            cell.pack(side="left", padx=(0, 12))
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w")
            field = ttk.Spinbox(cell, from_=0, to=500, increment=1, textvariable=variable, width=8)
            field.pack(pady=(5, 0))
            self.speed_inputs.append(field)
        actions = ttk.Frame(monitor, style="Card.TFrame")
        actions.pack(fill="x", pady=(8, 0))
        self.button(actions, "进入调试", a._enable_debug, "speed_enable").pack(side="left", padx=(0, 8))
        self.speed_hold = self.button(actions, "按住轮速测试", None, "speed_hold", "Accent.TButton")
        self.speed_hold.pack(side="left")
        self.speed_hold.bind("<ButtonPress-1>", a._speed_press)
        self.speed_hold.bind("<ButtonRelease-1>", a._drive_release)
        self.speed_hold.bind("<Leave>", a._drive_release)
        ttk.Label(monitor, textvariable=a.pwm_limit_info,
                  style="Muted.TLabel", wraplength=410).pack(anchor="w", pady=(10, 0))
        ttk.Label(monitor, text="上限在“调试控制”页解锁；抬起驱动轮测试，松开、失焦或换页即归零。",
                  style="Muted.TLabel", wraplength=410).pack(anchor="w", pady=(8, 0))
        line = self.card(page, "巡线 / 舵机参数", "这些参数仍仅在待机时应用。")
        line.pack(fill="x", pady=(12, 0))
        fields = ttk.Frame(line, style="Card.TFrame")
        fields.pack(fill="x")
        for col, i in enumerate((0, 1, 2, 8, 9)):
            cell = ttk.Frame(fields, style="Card.TFrame")
            cell.grid(row=0, column=col, sticky="w", padx=(0, 18))
            ttk.Label(cell, text=PID_FIELDS[i][0], style="Muted.TLabel").pack(anchor="w")
            entry = ttk.Entry(cell, textvariable=a.pid_vars[i], width=10)
            entry.pack(pady=7)
            self.pid_inputs.append(entry)
            self.button(cell, "应用", lambda n=i: a._apply_pid(n), f"pid:{PID_NAMES[i]}").pack(anchor="w")
        servo = self.card(page, "舵机中位 / 对称限幅", "中位与半摆幅作为一组应用；仅待机且硬件正常时修改，Flash 保存独立于 PID。")
        servo.pack(fill="x", pady=(12, 0))
        fields = ttk.Frame(servo, style="Card.TFrame")
        fields.pack(fill="x")
        self.servo_inputs = []
        for title, variable, low, high in (("中位 / µs", a.servo_center, 500, 2500),
                                           ("半摆幅 / µs", a.servo_span, 0, 1000)):
            cell = ttk.Frame(fields, style="Card.TFrame")
            cell.pack(side="left", padx=(0, 24))
            ttk.Label(cell, text=title, style="Muted.TLabel").pack(anchor="w")
            spin = ttk.Spinbox(cell, from_=low, to=high, increment=10, textvariable=variable, width=12)
            spin.pack(pady=(7, 0))
            self.servo_inputs.append(spin)
        self.button(fields, "成组应用", a._apply_servo, "servo_apply", "Accent.TButton").pack(side="left", anchor="s")
        ttk.Label(servo, textvariable=a.servo_bounds_info, style="Card.TLabel",
                  wraplength=900).pack(anchor="w", pady=(12, 0))
        ttk.Label(servo, text="输入为 PWM 高电平脉宽：1000 µs = 1 ms = 0.001 秒。"
                  "范围为中位 ± 半摆幅，端点须在 500–2500 µs；半摆幅 0 表示只允许中位。"
                  "编辑输入不会改变限幅，成组应用后车端读回值才生效。",
                  style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(8, 0))
        controls = ttk.Frame(servo, style="Card.TFrame")
        controls.pack(fill="x", pady=(12, 0))
        for text, callback, key, style in (("读取校准", a._read_servo, "servo_read", "TButton"),
                ("保存到 Flash", a._save_servo, "servo_save", "Accent.TButton"),
                ("从 Flash 加载", a._restore_servo, "servo_load", "TButton"),
                ("恢复默认", a._reset_servo, "servo_reset", "TButton")):
            self.button(controls, text, callback, key, style).pack(side="left", padx=(0, 10))
        ttk.Label(servo, textvariable=a.servo_flash_status, style="Card.TLabel").pack(anchor="w", pady=(12, 0))
        flash = self.card(page, "参数保存", "应用写入运行内存，保存到 Flash 后下次上电加载。")
        flash.pack(fill="x", pady=12)
        controls = ttk.Frame(flash, style="Card.TFrame")
        controls.pack(fill="x")
        for text, callback, key, style in (("读取参数", a._load_pid, "pid_read", "TButton"),
                ("保存到 Flash", a._save_pid, "pid_save", "Accent.TButton"),
                ("从 Flash 加载", a._restore_pid, "pid_load", "TButton"),
                ("恢复默认", a._reset_pid, "pid_reset", "TButton")):
            self.button(controls, text, callback, key, style).pack(side="left", padx=(0, 10))
        ttk.Label(flash, textvariable=a.flash_status, style="Card.TLabel").pack(anchor="w", pady=(14, 0))

    def _logs(self, a):
        page = ttk.Frame(self.tabs, padding=(4, 14, 4, 4))
        self.tabs.add(page, text="通信日志")
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Label(toolbar, text="ASCII 收发记录", font=(FONT, 12, "bold")).pack(side="left")
        self.button(toolbar, "清空显示", a._clear_log).pack(side="right")
        self.button(toolbar, "导出日志", a._export_log).pack(side="right", padx=8)
        monitor = ttk.Frame(page)
        monitor.pack(fill="both", expand=True)
        self.serial_text = tk.Text(monitor, wrap="none", height=12, bg="#102033", fg="#d1deee",
                                  insertbackground="white", relief="flat", padx=14, pady=12,
                                  state="disabled", font=("Consolas", 10))
        vertical = ttk.Scrollbar(monitor, command=self.serial_text.yview)
        horizontal = ttk.Scrollbar(monitor, orient="horizontal", command=self.serial_text.xview)
        self.serial_text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.serial_text.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        monitor.columnconfigure(0, weight=1)
        monitor.rowconfigure(0, weight=1)
        for tag, color in (("TX", "#5ce2ca"), ("RX", "#bbd4f5"), ("ERROR", "#ff929b"), ("INFO", "#a3b7cf")):
            self.serial_text.tag_configure(tag, foreground=color)
        command_row = ttk.Frame(page)
        command_row.pack(fill="x", pady=(10, 0))
        self.command_entry = ttk.Entry(command_row, textvariable=a.serial_command)
        self.command_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.command_entry.bind("<Return>", a._send_serial_command)
        self.button(command_row, "发送", a._send_serial_command, "send", "Accent.TButton").pack(side="right")
        ttk.Label(page, text="快捷只读查询：", foreground=MUTED).pack(anchor="w", pady=(8, 4))
        queries = ttk.Frame(page)
        queries.pack(fill="x")
        for command in ("PING", "HW?", "LINE?", "RANGE? L", "RANGE? C", "RANGE? R"):
            self.button(queries, command, lambda c=command: a._send_raw(c), f"query:{command}").pack(side="left", padx=(0, 6))

    def _wheel(self, event):
        widget = event.widget
        while widget is not None:
            if widget in self.scroll_pages:
                first, last = widget.canvas.yview()
                if last-first < 1:
                    widget.canvas.yview_scroll(-int(event.delta/120), "units")
                return
            widget = getattr(widget, "master", None)

    def set_pwm_limit(self, limit):
        for widget in self.drive_inputs[:2]:
            widget.configure(from_=-limit / 10, to=limit / 10)

    def set_servo_limits(self, settings):
        self.drive_inputs[2].configure(from_=settings.minimum_us, to=settings.maximum_us)
        self.remote_inputs[1].configure(from_=0, to=settings.span_us)

    def set_enabled(self, *, connected, connecting, state, ready, simulated, busy, holding=False, source="", pwm_limit_supported=None, servo_supported=None):
        editable = connected and ready and state=="IDLE" and not busy
        debug = connected and ready and state=="DEBUG" and not busy
        motor_editable = connected and ready and state in ("IDLE", "DEBUG") and not busy and not holding
        for key, button in self.buttons.items():
            enabled = connected
            if key=="connect": enabled = not connecting
            elif key=="simulate": enabled = True
            elif key=="disconnect": enabled = connected or connecting
            elif key in ("arm", "debug") or key.startswith("pid:") or key in ("pid_save", "pid_load", "pid_reset"):
                enabled = editable
            elif key=="drive": enabled = connected and ready and state=="DEBUG" and not busy
            elif key in ("remote_enable", "speed_enable"):
                enabled = connected and ready and state in ("IDLE", "DEBUG", "FINISHED", "FAULT") and not busy and not holding
            elif key.startswith("remote:"):
                enabled = debug and (not holding or source=="remote")
            elif key=="remote_brake": enabled = connected and state=="DEBUG"
            elif key=="speed_hold": enabled = debug and (not holding or source=="speed")
            elif key=="tune": enabled = motor_editable
            elif key=="pwm_unlock": enabled = motor_editable and pwm_limit_supported is True
            elif key=="pwm_lock": enabled = connected and state=="DEBUG"
            elif key=="sim_input": enabled = connected and simulated
            elif key in ("servo_apply", "servo_save", "servo_load", "servo_reset"):
                enabled = editable and not holding and servo_supported is True
            elif key=="servo_read": enabled = connected and not busy and not holding
            elif key.startswith("servo_pulse:"): enabled = motor_editable
            button.configure(state="normal" if enabled else "disabled")
        for widget in self.pid_inputs:
            widget.configure(state="normal" if editable else "disabled")
        for widget in self.motor_pid_inputs:
            widget.configure(state="normal" if motor_editable else "disabled")
        for widget in self.servo_inputs:
            widget.configure(state="normal" if editable and not holding and servo_supported is True else "disabled")
        for widget in self.speed_inputs + self.remote_inputs:
            widget.configure(state="normal" if motor_editable else "disabled")
        for widget in self.drive_inputs:
            widget.configure(state="normal" if debug and not holding else "disabled")
        self.pwm_limit_input.configure(state="normal" if motor_editable and pwm_limit_supported is True else "disabled")
        for widget in self.sim_inputs:
            widget.configure(state="normal" if simulated and connected else "disabled")
        self.command_entry.configure(state="normal" if connected else "disabled")
        self.badge.configure(bg="#164e4b" if connected else "#28405b", fg="#98ebd9" if connected else "#d8e8f6")
