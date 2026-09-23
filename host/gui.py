"""Small desktop bench GUI. Run with: python -m host.gui"""

import tkinter as tk
from tkinter import messagebox, ttk

from .protocol import CarClient, SerialLink, SimLink


STATE_LABELS = {
    "IDLE": "待机", "ARMED": "自动预备", "FOLLOW": "循迹", "AVOID_OUT": "绕障离线",
    "AVOID_PASS": "绕障通过", "AVOID_IN": "绕障回转", "RECOVER": "搜线回归",
    "FINISHED": "已完成", "DEBUG": "调试", "FAULT": "故障",
}
FAULT_LABELS = ["无", "丢线", "测距异常", "回线超时", "比赛超时", "前方受阻"]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("循迹避障小车 · 上位机")
        self.root.geometry("760x650")
        self.root.minsize(700, 590)
        self.client: CarClient | None = None
        self.sim: SimLink | None = None
        self.last_state = ""
        self.drive_timer: str | None = None
        self.poll_timer: str | None = None
        self.port = tk.StringVar(value="COM3")
        self.connection = tk.StringVar(value="未连接")
        self.state = tk.StringVar(value="—")
        self.fault = tk.StringVar(value="—")
        self.line = tk.StringVar(value="—")
        self.range_left = tk.StringVar(value="—")
        self.range_right = tk.StringVar(value="—")
        self.encoders = tk.StringVar(value="—")
        self.obstacles = tk.StringVar(value="—")
        self.motors = tk.StringVar(value="—")
        self.steer = tk.StringVar(value="—")
        self.left_demand = tk.IntVar(value=0)
        self.right_demand = tk.IntVar(value=0)
        self.steer_demand = tk.IntVar(value=1500)
        self.sim_line = tk.StringVar(value="001100")
        self.sim_left = tk.IntVar(value=500)
        self.sim_right = tk.IntVar(value=500)
        self._build()
        root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Section.TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", padding=(9, 6))
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="循迹避障小车", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="自动运行在车载 STM32；电脑用于赛前调试与只读监测。", foreground="#5b6470").pack(anchor="w", pady=(2, 14))

        connection = ttk.LabelFrame(outer, text="连接", style="Section.TLabelframe", padding=10)
        connection.pack(fill="x", pady=(0, 10))
        ttk.Label(connection, text="串口").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(connection, textvariable=self.port, width=12).grid(row=0, column=1)
        ttk.Button(connection, text="连接实物", command=self._connect_serial).grid(row=0, column=2, padx=6)
        ttk.Button(connection, text="界面仿真", command=self._connect_sim).grid(row=0, column=3)
        ttk.Button(connection, text="断开", command=self._disconnect).grid(row=0, column=4, padx=6)
        ttk.Label(connection, textvariable=self.connection).grid(row=0, column=5, sticky="e")
        connection.columnconfigure(5, weight=1)

        panel = ttk.LabelFrame(outer, text="车载状态", style="Section.TLabelframe", padding=10)
        panel.pack(fill="x", pady=(0, 10))
        items = [("模式", self.state), ("故障", self.fault), ("灰度 0→5", self.line),
                 ("左测距", self.range_left), ("右测距", self.range_right),
                 ("编码器增量 L/R", self.encoders), ("已绕障", self.obstacles),
                 ("电机命令 L/R", self.motors), ("舵机脉宽", self.steer)]
        for index, (label, value) in enumerate(items):
            row, column = divmod(index, 3)
            cell = ttk.Frame(panel)
            cell.grid(row=row, column=column, sticky="ew", padx=8, pady=5)
            ttk.Label(cell, text=label, foreground="#667085").pack(anchor="w")
            ttk.Label(cell, textvariable=value, font=("Consolas", 11, "bold")).pack(anchor="w")
        for column in range(3):
            panel.columnconfigure(column, weight=1)

        modes = ttk.LabelFrame(outer, text="模式控制", style="Section.TLabelframe", padding=10)
        modes.pack(fill="x", pady=(0, 10))
        ttk.Button(modes, text="自动预备（3 秒后自启）", command=lambda: self._command("arm")).pack(side="left", padx=(0, 8))
        ttk.Button(modes, text="进入调试", command=lambda: self._command("debug")).pack(side="left", padx=(0, 8))
        ttk.Button(modes, text="停止 / 待机", command=self._stop).pack(side="left")
        ttk.Label(outer, text="正式比赛开始后不得用电脑遥控；自动模式只显示遥测。", foreground="#ae5f00").pack(anchor="w", pady=(0, 10))

        manual = ttk.LabelFrame(outer, text="调试：按住按钮才会驱动，松手即停", style="Section.TLabelframe", padding=10)
        manual.pack(fill="x", pady=(0, 10))
        for column, (label, variable, low, high) in enumerate([
            ("左电机 ‰", self.left_demand, -300, 300),
            ("右电机 ‰", self.right_demand, -300, 300),
            ("舵机 µs", self.steer_demand, 1300, 1700),
        ]):
            cell = ttk.Frame(manual)
            cell.grid(row=0, column=column, sticky="w", padx=8)
            ttk.Label(cell, text=label).pack(anchor="w")
            ttk.Spinbox(cell, from_=low, to=high, increment=10, textvariable=variable, width=12).pack(anchor="w", pady=5)
        hold = ttk.Button(manual, text="按住驱动")
        hold.grid(row=0, column=3, padx=10)
        hold.bind("<ButtonPress-1>", self._drive_press)
        hold.bind("<ButtonRelease-1>", self._drive_release)
        ttk.Label(manual, text="失联 500 ms 后车载调试驱动自动归零。", foreground="#667085").grid(row=1, column=0, columnspan=4, sticky="w", padx=8)

        simulator = ttk.LabelFrame(outer, text="仿真输入（仅界面仿真时可用）", style="Section.TLabelframe", padding=10)
        simulator.pack(fill="x")
        ttk.Label(simulator, text="灰度 6 位二进制").grid(row=0, column=0, padx=5)
        ttk.Entry(simulator, textvariable=self.sim_line, width=9).grid(row=0, column=1)
        ttk.Label(simulator, text="左 / 右距离 mm").grid(row=0, column=2, padx=(16, 5))
        ttk.Spinbox(simulator, from_=0, to=6000, textvariable=self.sim_left, width=7).grid(row=0, column=3)
        ttk.Spinbox(simulator, from_=0, to=6000, textvariable=self.sim_right, width=7).grid(row=0, column=4, padx=5)
        ttk.Button(simulator, text="应用仿真输入", command=self._apply_sim).grid(row=0, column=5, padx=8)

    def _connect_serial(self) -> None:
        self._disconnect()
        try:
            self.client = CarClient(SerialLink(self.port.get().strip()))
            self.connection.set(f"已连接 {self.port.get().strip().upper()}")
            self._refresh()
        except Exception as exc:
            self.client = None
            messagebox.showerror("连接失败", str(exc))

    def _connect_sim(self) -> None:
        self._disconnect()
        self.sim = SimLink()
        self.client = CarClient(self.sim)
        self.connection.set("界面仿真")
        self._refresh()

    def _disconnect(self) -> None:
        if self.drive_timer is not None:
            self.root.after_cancel(self.drive_timer)
            self.drive_timer = None
        if self.poll_timer is not None:
            self.root.after_cancel(self.poll_timer)
            self.poll_timer = None
        if self.client is not None:
            try:
                if self.last_state == "DEBUG":
                    self.client.stop()
                self.client.close()
            except Exception:
                pass
        self.client = None
        self.sim = None
        self.last_state = ""
        self.connection.set("未连接")

    def _refresh(self) -> None:
        if self.client is None:
            return
        try:
            status = self.client.status()
            self.last_state = status.state
            self.state.set(f"{STATE_LABELS[status.state]}  ({status.state})")
            self.fault.set(FAULT_LABELS[status.fault])
            self.line.set(" ".join("●" if status.line_bits & (1 << i) else "○" for i in range(6)))
            self.range_left.set("无回波" if status.left_mm is None else f"{status.left_mm} mm")
            self.range_right.set("无回波" if status.right_mm is None else f"{status.right_mm} mm")
            self.encoders.set(f"{status.encoder_left_delta} / {status.encoder_right_delta}")
            self.obstacles.set(str(status.obstacles))
            self.motors.set(f"{status.motor_left} / {status.motor_right} ‰")
            self.steer.set(f"{status.steer_us} µs")
        except Exception as exc:
            self.connection.set(f"通信异常：{exc}")
            self._disconnect()
            return
        self.poll_timer = self.root.after(500, self._refresh)

    def _command(self, name: str) -> None:
        if self.client is None:
            messagebox.showinfo("未连接", "请先连接实物或界面仿真。")
            return
        try:
            getattr(self.client, name)()
            if self.poll_timer is not None:
                self.root.after_cancel(self.poll_timer)
            self._refresh()
        except Exception as exc:
            messagebox.showerror("命令失败", str(exc))

    def _stop(self) -> None:
        self._drive_release()
        self._command("stop")

    def _drive_press(self, _event=None) -> None:
        if self.client is None or self.last_state != "DEBUG":
            return
        try:
            self.client.drive(self.left_demand.get(), self.right_demand.get(), self.steer_demand.get())
        except Exception as exc:
            messagebox.showerror("调试失败", str(exc))
            return
        self.drive_timer = self.root.after(200, self._drive_press)

    def _drive_release(self, _event=None) -> None:
        if self.drive_timer is not None:
            self.root.after_cancel(self.drive_timer)
            self.drive_timer = None
        if self.client is not None and self.last_state == "DEBUG":
            try:
                self.client.drive(0, 0, 1500)
            except Exception:
                pass  # The on-board deadman stops drive after 500 ms.

    def _apply_sim(self) -> None:
        if self.sim is None:
            return
        try:
            bits = self.sim_line.get().strip()
            if len(bits) != 6 or any(char not in "01" for char in bits):
                raise ValueError("灰度必须是 6 位 0/1，例如 001100")
            left, right = self.sim_left.get(), self.sim_right.get()
            if not 0 <= left <= 6000 or not 0 <= right <= 6000:
                raise ValueError("距离范围是 0–6000 mm")
            self.sim.line_bits = int(bits[::-1], 2)
            self.sim.left_mm, self.sim.right_mm = left, right
            if self.poll_timer is not None:
                self.root.after_cancel(self.poll_timer)
            self._refresh()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("仿真输入错误", str(exc))

    def _close(self) -> None:
        self._disconnect()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
