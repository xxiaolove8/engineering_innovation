# JDY-31 与八路灰度模块更新

2026-09-30 按 `D:\projects\docs` 中新增资料调整工程。蓝牙实物改为四针 JDY-31，电脑连接改用经典蓝牙 SPP 虚拟 COM；STM32 继续使用 USART3 PB10/PB11、9600 8N1。八路灰度 GPIO、CD4051 地址对应关系和低电平黑线默认值已与官方资料核对，切换等待调整为 500 µs，并增加原始电平查询。

随后完成的全工程维护与新版 UI 见 [MAINTENANCE_2026-09-30.md](MAINTENANCE_2026-09-30.md)。当前连接按钮为“连接设备”，灰度查询位于“实时监测 → 读取原始 OUT”；旧 BT24 工具入口已移到 `python -m host.legacy.ble_check`，依赖见 `host/requirements-ble.txt`。下方验证数量记录本次模块适配阶段结果，最新数量以维护记录为准。

## 采用的原始资料

| 工程内归档 | 原始来源 / 采用内容 |
| --- | --- |
| [JDY-31 手册](modules/jdy31/manual.pdf) | `蓝牙串口模块JDY-31（4针）/JDY-31-V1.3蓝牙SPP串口透传模块手册.pdf`；SPP、9600、设备名、配对密码、AT 指令、裸模块供电。 |
| [八路灰度简介](modules/line_sensor/intro.pdf) | `八路灰度模块/1.8路灰度模块简介/用户入门手册.pdf`；5 V 供电、CD4051 地址真值表、EN 下拉、约 18 mm 最佳离地高度。 |
| [STM32 数据读取](modules/line_sensor/stm32_read.pdf) | `八路灰度模块/2.单片机数据读取/3.STM32F103C8T6/数据读取.pdf`；推挽地址线、浮空数字输入、原始 OUT 与指示灯对应关系。 |
| [STM32 小车巡线](modules/line_sensor/stm32_follow.pdf) | `八路灰度模块/3.小车灰度巡线/2.STM32开发板小车/小车巡线.pdf`；可配置线电平、通道权重和速度闭环。 |
| [识别不良处理](modules/line_sensor/troubleshooting.pdf) | `八路灰度模块/0.使用注意事项/识别不良解决方案.pdf`；探头位置和不同发光款式的识别问题。 |
| [F103 灰度源码](modules/line_sensor/reference/f103_grayscale_sensor.c)、[头文件](modules/line_sensor/reference/f103_grayscale_sensor.h) | 从 `4、程序源码.rar` 的 `1.单片机数据读取/2.STM32F103C8T6/Grayscale_Read/BSP/Grayscale_Sensor` 提取；实际源码采用 **500 µs**。 |
| [小车灰度源码](modules/line_sensor/reference/car_grayscale_sensor.c)、[头文件](modules/line_sensor/reference/car_grayscale_sensor.h)、[巡线逻辑](modules/line_sensor/reference/car_trace_task.c)、[头文件](modules/line_sensor/reference/car_trace_task.h) | 同一 RAR 中官方 STM32 小车例程；灰度仍采用 **50 µs**，巡线使用独立轮速控制。 |

原件按字节保留，校验值及 RAR 内完整路径记录在 [archive_manifest.json](archive_manifest.json)。`reference` 仅用于核对，不参加本工程编译。原 DX-BT24 手册及联调记录保留为历史资料。

## JDY-31 接线与电脑连接

MCU **PB10 / H2-28 → JDY-31 RXD**，**JDY-31 TXD → PB11 / H2-29**，GND 共地。四针实物按 VCC/GND/TXD/RXD 丝印连接。原载板 J3-2、J3-3 分别是 MCU TX、RX，J3-4 为地，J3-5 为 +5 V；这些数字是载板端点，不是新模块排针编号。原 J3-6 的 3V3 原方案未接，不能直接作为已布线电源使用。完整关系见 [PINOUT.md](../PINOUT.md)。

JDY-31 裸模块手册给出的电源范围是 1.8–3.6 V，推荐 3.3 V。供应资料中的四针封面图带底板，但缺少该底板的输入电压规格或电路图；是否能接原 J3 的 5 V 尚须按实物稳压规格核对。软件没有改变或证明电源接线。

1. 在 Windows 蓝牙设置中配对 `JDY-31-SPP`；出厂密码 `1234`。如实物已改名或密码，按其当前配置操作。
2. 在系统蓝牙串口设置中找到该设备的**出站 SPP COM 口**；GUI 同时列出入站和出站 COM 时，按系统中的方向信息选择。刷新列表优先选蓝牙端口，但自动选择不能区分方向。
3. 退出占用此模块的 Android APP / 其他串口助手。在上位机选择出站 COM，点击“连接 JDY-31 / USB-TTL”。收到 `PONG 2` 并读到状态才算 MCU 链路连通。
4. 连接失败时可退出 GUI 连接后运行：

   ```powershell
   .\.venv\Scripts\python.exe -m host.serial_check --port COM3
   ```

   工具只发送 `PING`、`HW?`、`STATUS?`、`LINE?`，输出 JSON；COM3 替换为实际端口。`--simulate` 只验证工具流程。它不启动电机、不修改 PID，也不配置蓝牙模块。

JDY-31 是 Bluetooth 3.0 SPP，从机模式；原 BT24 的 BLE GATT/FFE0/FFE1/FFE2 流程不适用于它。GUI 的“旧 BT24 BLE”入口及原 BLE 工具保留供旧硬件使用。USB-TTL 备用连接使用同一串口按钮，先断开 JDY-31 TX/RX，避免两个 TX 驱动 MCU RX。

### 赛前单独配置模块

将模块与 MCU 的 TX/RX 断开，通过 USB-TTL 以 3.3 V 逻辑连接模块并共地，关闭其蓝牙会话。模块 AT 指令务必发送实际 CRLF 字节 `\r\n`，不要把它作为 GUI 的小车命令发送。

| AT 指令 | 目的 |
| --- | --- |
| `AT+VERSION` | 查询固件版本。V1.3 手册说明 V1.2 的电脑连接问题在 V1.3 修复，须确认实际固件版本；表中的示例字符串仍写 V1.2。 |
| `AT+BAUD` / `AT+BAUD4` | 查询 / 设置 9600。参数直接接命令，无 `=`；若模块当前不是 9600，应先以其当前速率通信。 |
| `AT+NAME` | 查询当前设备名称；默认 `JDY-31-SPP`。 |
| `AT+PIN` | 查询当前配对密码；默认 `1234`。 |
| `AT+ENLOG` / `AT+ENLOG0` | 查询 / 关闭开机、连接和断开时输出到 UART 的模块日志；默认开启。 |

固件会忽略 `+` 开头的模块状态/AT 响应行，避免产生额外 `ERR COMMAND` 干扰下一次小车握手。仍建议单独关闭 ENLOG，减少异步日志与透传数据混杂。配置完成后重新查询并核对参数，再恢复 MCU 接线。固件不会在启动或自动行驶中向 JDY-31 发送 AT 指令。

普通车控命令使用 ASCII，以 LF `\n` 结束，继续兼容协议 v2。COM 链路等待响应 2 秒，`PID SAVE` 为 5 秒；超时或不完整行后会废弃会话并要求重连。GUI 初始连接在后台线程执行，取消、换连接或关闭窗口后到达的结果会释放连接。

## 八路灰度适配与校准

模块用 5 V 供电，地址采用 **AD0=PF0、AD1=PF1、AD2=PF2**；**OUT=PC5**，保持数字输入、无上下拉、无 ADC。官方源码也使用推挽地址输出和浮空数字输入。模块 EN 已有 10 kΩ 下拉，保持选通，无须增加 MCU 控制脚。

| AD2 AD1 AD0 | 官方通道 | 默认协议位 |
| --- | --- | --- |
| 000 | CH1 / X1 | bit 0 |
| 001 | CH2 / X2 | bit 1 |
| 010 | CH3 / X3 | bit 2 |
| 011 | CH4 / X4 | bit 3 |
| 100 | CH5 / X5 | bit 4 |
| 101 | CH6 / X6 | bit 5 |
| 110 | CH7 / X7 | bit 6 |
| 111 | CH8 / X8 | bit 7 |

官方数据读取 PDF 写每路等待 50 µs，但更新 RAR 中 F103 的 `Read_All` 和 `Read_Single` 实际都等待 500 µs；官方小车源码仍是 50 µs。本工程先采用 500 µs，八路总等待约 4 ms，10 ms 控制周期保持。等待使用原有 TIM10 微秒计时，保留时钟失效检测，不复制厂商 F103 引脚或延时初始化。

`CAR_LINE_ADDRESS_MAP` 默认 `{0,1,2,3,4,5,6,7}`，先假设 X1 在车的左侧、X8 在右侧。若安装方向相反，可改为 `{7,6,5,4,3,2,1,0}`；此后诊断位图和控制位图都按映射后的逻辑顺序输出。`CAR_LINE_BLACK_LEVEL` 默认 `GPIO_PIN_RESET`，表示低电平识别到线；赛道、发光款式和颜色可能改变识别效果，应实测后修改该值。厂商小车 PDF 的 `LINE_RAW_VALUE=1` 是配置示例，教程要求按实际线上指示灯设置，不是对所有黑线的固定高电平保证。

新只读命令：

```text
LINE? → LINE raw_bits line_bits black_level settle_us age_ms
例如：LINE 231 24 0 500 2
```

上述例子原始 OUT 在逻辑 CH4/CH5 为低，`line_bits=24` 即识别到 CH4/CH5 的线。`raw_bits` 的 1 为 OUT 高；`line_bits` 的 1 为识别到线；`black_level` 为当前配置 0/1；`age_ms` 为距最近完整扫描的毫秒数。诊断使用控制循环的缓存，不额外扫描或驱动电机。没有完整扫描或硬件故障时返回 `ERR NOT_READY`。原 `STATUS?` 中的 `line_bits` 语义保持为识别到线。

抬起驱动轮、保持 IDLE，逐路用赛道底色和线材覆盖 X1–X8，点击 GUI 概览“读取灰度原始电平”。核对单个探头对应位、线上与线外原始电平、指示灯状态和左右方向。整板放在背景上应读到 `line_bits=0`，覆盖整条线区域应读到 `255`；否则先检查高度、光源款式、地址接线和极性。探头到地面先以官方建议约 18 mm 调整，再用实际赛道复核。

巡线计算继续使用现有舵机转向 + 两后轮速度闭环。官方四轮差速例程的 PID 常数、速度单位、全亮/全灭启动锁和权重不能直接等同本车；本车保留显式 `AUTO ARM`、起点全黑区域处理及终点检测。PID 仍须实车调试，更新采样等待不代表已经完成机械或电平验收。

## 验证

- `tests/run_tests.py`：三组本机 C 测试、31 项 Python 测试通过；新增覆盖全部 256 种八路图样、原始/归一位图、固定 500 µs 等待、诊断年龄与故障不可用、模块状态行不生成额外响应、SPP 串口 9600 8N1/无流控、Flash 等待和不完整响应后重连。
- Debug / Release：交叉编译、链接和 HEX/BIN 生成通过，产物分别位于 `build/Debug`、`build/Release`。
- 上位机隐藏窗口仿真：连接、原始灰度读取、后台 SPP 连接、取消后释放迟到连接通过；概览增加滚动支持，窗口内容可完整访问。只读诊断工具的 `--simulate` 流程通过，资料 SHA256 和更新文档链接核对通过。
- 尚未烧录新固件或验证实物 JDY-31 配对、四针供电、灰度通道方向及赛道识别；使用前执行上述实物核对。
