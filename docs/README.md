# 工程资料归档

全工程代码维护、界面优化、历史代码归档与新增回归覆盖见 [MAINTENANCE_2026-09-30.md](MAINTENANCE_2026-09-30.md)。

新增“遥控回车”以及 PID 同页轮速监看/闭环测试的操作、固件协议与验证见 [REMOTE_SPEED_2026-09-30.md](REMOTE_SPEED_2026-09-30.md)。

新增单舵机与多路舵机控制器例程的交叉核对见 [SERVO_EXAMPLE_REVIEW_2026-09-30.md](SERVO_EXAMPLE_REVIEW_2026-09-30.md)。晚间已确认实际 DS3218MG 的 5 V 电源负极未与 STM32 共地；先修正接线，再确认烧录程序与实际 PWM。关键例程按原字节归档在 [modules/servo/reference](modules/servo/reference/README.md)，不参与小车编译。

用户随后反馈共地后舵机上电已有动作，但板载 CH340 / COM5 能打开却收不到 PONG。原理图确认该 USB 串口使用 USART1；此前固件只实现 USART3。本次双串口支持、DTR/RTS 设置与 Tk `popdown` 修复见 [USB_SERIAL_FIX_2026-09-30.md](USB_SERIAL_FIX_2026-09-30.md)。

2026-10-01 深查发现板子实际停留系统 Bootloader；正常复位后，当前 CH340 / COM6 连续 100 次 PING、5 次重连和真实 GUI 连接均通过。Windows DCB、固件身份比对、现场状态与 VTOR 启动补强见 [SERIAL_AUDIT_2026-10-01.md](SERIAL_AUDIT_2026-10-01.md)。这次没有改写板上固件，新的 VTOR 构建尚未烧录。

2026-09-30 首次将 `D:\projects\docs` 中 6 个源文件复制到本工程，加上原有比赛 PDF 共 7 个资料文件；随后补充四针 JDY-31 与八路灰度官方资料。原件内容未重写或转存，大小、SHA256 及源码 RAR 内路径记录在 [archive_manifest.json](archive_manifest.json)。本次模块适配与实物核对步骤见 [MODULE_UPDATE_2026-09-30.md](MODULE_UPDATE_2026-09-30.md)。

| 资料 | 用途 / 采用范围 |
| --- | --- |
| [2026929PINOUT.md](2026929PINOUT.md) | **24 根 MCU 信号基线 V3.1**。采用第 2 节信号、第 3/6 节共用资源与初始化约束；新 JDY-31 的模块端转接与供电以更新说明和当前 PINOUT 为准。 |
| [DS3218 datasheet.pdf](DS3218%20datasheet.pdf) | 舵机电源范围、堵转电流、1500 µs 中位及 50–330 Hz 控制范围。固件暂选 50 Hz。 |
| [DX-BT24 技术手册](蓝牙模块DX-BT24技术手册-24dc986a6ba9b0512dcff32f34df2488.pdf) | **旧模块历史资料**：BLE 5.1/GATT、裸模块电源与 UART 接口。 |
| [BT24 AT 指令手册](蓝牙模块AT指令手册-67f1d39f55087ac97890e922766ba4bb.pdf) | **旧模块历史资料**：FFE0/FFE1/FFE2；不用于 JDY-31 SPP。 |
| [JDY-31 手册](modules/jdy31/manual.pdf) | 当前蓝牙：Bluetooth 3.0 SPP、默认 9600、JDY-31-SPP / 1234、CRLF AT 命令与裸模块电源边界。 |
| [八路灰度简介](modules/line_sensor/intro.pdf)、[STM32 读取](modules/line_sensor/stm32_read.pdf)、[STM32 巡线](modules/line_sensor/stm32_follow.pdf)、[识别问题](modules/line_sensor/troubleshooting.pdf) | 数字扫描、EN 下拉、线电平配置、安装高度与识别问题。 |
| [灰度官方源码参考](modules/line_sensor/reference/f103_grayscale_sensor.c) | RAR 内 F103 与小车相关 6 个 C/头文件按原字节提取；500/50 µs 差异已记录，源码仅供参考不参与编译。 |
| [核心板原理图](f407_data/STM32F407_CORE_BOARD_V1.4.pdf) | 核对相关 GPIO 复用、JP1/JP2 排针、SRAM CE/共用地址数据总线。图内标题为 2021-07-27、V1.0，文件名含 V1.4；保留该版本差别。 |
| [核心板 IO 资源分配表](f407_data/STM32F407最小系统板IO分配表.xlsx) | 只读核对引出情况、SRAM 共用资源及 Camera 连接。没有改写源表格。 |
| [比赛规则 PDF](2026年循迹小车分散实训PPT.pdf) | 自动运行、四个随机侧置障碍、黑线/终点、5 分钟单轮上限和停止要求。 |

软件接线摘要见 [../PINOUT.md](../PINOUT.md)，完整本次审查见 [REVIEW_2026-09-30.md](REVIEW_2026-09-30.md)。`archive/legacy_*` 保存本次修改前 Git 基线的引脚资料，仅供追溯。

“超声波没有信号”的后续修正、诊断命令和下午测试步骤见 [ULTRASONIC_CHECK_2026-09-30.md](ULTRASONIC_CHECK_2026-09-30.md)。后续驱动已取消无回波时上报有效 6000 mm 的旧行为，以这份联调记录为准。

旧 BT24 与网页助手的通道对照、当时实物 GATT/握手检查及启动失败时保留通信的修改见 [BT24_DEBUG_2026-09-30.md](BT24_DEBUG_2026-09-30.md)。当前 JDY-31 使用出站 SPP COM，与旧模块的实测结果无关。

V3.1 引用的灰度资料现已以更新 PDF/RAR 形式收到并核对。ATK-DNM144Z-M4 原 PDF、HC-SR04-P 手册、D24A 商品/电路资料及 `.epro2` 工程仍未出现在此次上级 `docs` 中，未将这些缺失附件标为已独立审核。
