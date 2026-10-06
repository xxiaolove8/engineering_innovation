# 板载 CH340 / COM5 与 Tk 下拉框修复（2026-09-30）

后续实测发现板子停留系统 Bootloader；2026-10-01 正常复位后 COM6 的 100 次 PING、5 次重连与真实 GUI 均通过。现场证据、启动向量补强与限制以 [串口深查记录](SERIAL_AUDIT_2026-10-01.md)为准，下面保留首次修改时的记录与固件哈希。

## 用户反馈与定位

共地后 DS3218MG 上电已有反应。用户直接连接核心板板载 CH340 的 USB，Windows 显示 COM5；ASCII 工具能打开端口，但发送 PING 没有收到 PONG。附件共包含 36 次相同的 `KeyError: 'popdown'`，调用路径为 `App._check_focus → root.focus_displayof → _nametowidget`。

本次只读枚举确认电脑存在 USB-SERIAL CH340 (COM5)，VID:PID=1A86:7523；COM3/COM4 为蓝牙串口。没有打开实际 COM、发送实车控制、复位或烧录。

确认两处软件问题：

1. 原固件仅初始化 USART3 / PB10、PB11。**板载 CH340 使用 USART1 / PA9、PA10，原先没有实现这一路车控通信。**COM 能打开只说明电脑与 CH340 之间可访问，不代表 MCU 已接收命令。
2. ttk 下拉框的弹窗是原生 Tcl 窗口，没有对应的 Python widget 对象。`focus_displayof()` 尝试转换该路径时抛出 `KeyError: 'popdown'`，导致焦点回调反复报错。

## 板载接口证据

已完整查看 [核心板原理图](f407_data/STM32F407_CORE_BOARD_V1.4.pdf) 相关第 1、3 页：

- 第 3 页的 USB1 / **USB_TTL** → U5 CH340C → TXD/RXD。
- 第 1 页右下角 JP3：**1=PA10 / USART1_RX，2=CH340 TXD；3=PA9 / USART1_TX，4=CH340 RXD**。两组分别用跳帽连接 1–2、3–4。
- 第 3 页 USB2 / **USB_OTG** 是另一只接口，连接 MCU 原生 USB 数据线。
- CH340 RTS#/DTR#经三极管连接 RESET/BOOT0 的自动下载电路，正常调试串口不应主动操作下载控制线。

历史现场曾记录 MCU 运行 Bootloader。这与本板存在自动下载电路是相关线索，但本次没有测量控制线或启动过程，不能证明之前的 Bootloader 状态就是 DTR/RTS 引起。

## 已完成的修改

固件新增 USART1，PA9 TX / PA10 RX、AF7、9600 8N1，同时保留 USART3。时钟、GPIO、中断处理、声明、IOC 与两份 CSV 已同步；载板原来的 24 根信号保持一致，额外启用核心板已有的 2 根 CH340 信号。

两路分别维护接收字节、环形缓冲、分片、非法帧和发送队列。主循环轮询两路，命令从哪一路进入，响应就只回该通道，不广播、不混合半条命令。任一路接收初始化失败，另一条仍可工作；全车执行器初始化失败时仍可读取 PING / HW? 诊断。

上位机通过 `Serial(None, ...)` 创建尚未打开的对象，先设置 **DTR=False、RTS=False**，再指定 COM 并打开；关闭输入缓冲清理或打开失败时释放连接并保留原始错误。`rtscts=False / dsrdtr=False` 仅关闭流控，不能替代这两个电平设置。实现与 [pySerial 官方 API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html) 的开口前设置方式一致；驱动仍可能产生瞬态，软件设置不能作为实际控制线无毛刺的保证。

GUI 焦点检查直接读取 Tcl 路径，正常识别本窗口的下拉弹窗；真正切出主窗口仍停止按住的遥控。键盘操作也能处理原生控件路径，输入框、下拉列表和已销毁控件不会触发遥控。连接提示区已标明板载 CH340=USART1、JDY-31 / 外置 TTL=USART3。

## 实机复测步骤

1. 关闭占用 COM5 的 ASCII 助手、旧 GUI 或其他串口程序。
2. 通过现有下载方式烧录 [Release HEX](../build/Release/if_car.hex)，应用起始地址为 0x08000000。这次必须使用含 USART1 的新固件，仅重启上位机不能让旧固件回应板载 COM。保留 PID 参数时不做全片擦除；参数位于 0x080E0000 的 sector 11。
3. 确认 JP3 的 1–2、3–4 跳帽连接，BOOT0=0，运行小车应用。串口线连接核心板 USB_TTL / CH340 插座。
4. 用工程 [start_gui.cmd](../start_gui.cmd) 重启 GUI，连接方式选“串口（USB / JDY-31）”、串口选 COM5。预期通信日志显示 `TX: PING`、`RX: PONG 2`，随后读取 `HW 1 READY` 或具体硬件失败阶段。
5. 若用 ASCII 助手，设置 **9600、8 数据位、无校验、1 停止位、无流控、DTR/RTS 关闭**；发送 `PING` 时附加 **LF 或 CRLF**。固件按换行处理命令，单独发送四个字母而无换行不会立即回复。不要同时让两个软件打开 COM5。

也可关闭 GUI 后做只读诊断：

```powershell
.\.venv\Scripts\python.exe -m host.serial_check --port COM5
```

该工具仅握手并读取硬件、状态和灰度，保存 JSON；不会进入 DEBUG 或启动车辆。板载 USART1 与蓝牙 USART3 可独立读取状态，同一辆车的运动与参数修改由一个控制端执行。

## 验证与固件识别

- 6 个本地 C 测试程序通过，双串口回归覆盖同时分片、命令轮询、回复来源、两路发送同时在途、非法帧/错误/溢出隔离、单路失败回退与硬件故障可诊断。
- 108 项 Python 回归通过，其中 GUI 26 项、协议 37 项、引脚一致性 3 项；新增真实 Tcl popdown、外部窗口焦点和开口前控制线状态测试。
- Debug 与 Release 均交叉编译通过，HEX/BIN 已更新；Release ELF 中确认存在 USART1 中断和 huart1。
- Debug Flash=66192 B / RAM=5000 B；Release Flash=48472 B / RAM=4960 B。
- Release HEX SHA256：`3293c9f87a0f634f31bfc8c053237aa3972c70f8d32969b3e775e52bc180fd76`。
- Release BIN SHA256：`954c849d216c1c728fda4fb218c56b6f174f0825c46d9192951a1992b4b1ca3b`。

回归使用假 HAL、仿真链路和真实 Tk 事件循环，没有实际访问 COM5；板上烧录版本、跳帽状态、共地后波形和新固件的实机握手仍待复测。`PONG 2` 是协议版本，不能区分所有历史 v2 构建，请按本次 HEX 文件与哈希确认烧录来源。
