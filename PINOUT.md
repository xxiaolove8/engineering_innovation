# 小车引脚与 CubeMX 配置（V3.1 信号 + JDY-31 模块更新）

本工程按 [2026-09-29 接线基线](docs/2026929PINOUT.md) 的 24 根信号实现，目标芯片 STM32F407ZGT6。H1/H2 是载板排针数字脚号，分别对应核心板 JP1/JP2；芯片 LQFP144 封装脚号单列，不代表开发板插接面方向。

2026-09-30 蓝牙改为四针 JDY-31 SPP，八路灰度按新官方资料核对。下表 J3 数字仍为原载板接口编号，JDY-31 四针排针按丝印转接；模块针序和电源不能由旧六针定义推断。详见 [模块更新说明](docs/MODULE_UPDATE_2026-09-30.md)。

| 功能 / 网络 | GPIO | 载板脚号 | 外设端点 | 外设配置 | 芯片封装脚号 |
| --- | --- | --- | --- | --- | --- |
| DRV_PWMA | PA2 | H1-8 | J7-4 / PWMA | TIM5_CH3 / AF2 | 36 |
| DRV_PWMB | PA3 | H1-9 | J7-3 / PWMB | TIM5_CH4 / AF2 | 37 |
| DRV_AIN1 | PC0 | H2-15 | J7-8 / AIN1 | GPIO Output | 26 |
| DRV_AIN2 | PC1 | H2-16 | J7-6 / AIN2 | GPIO Output | 27 |
| DRV_BIN1 | PC2 | H1-10 | J7-7 / BIN1 | GPIO Output | 28 |
| DRV_BIN2 | PC3 | H1-7 | J7-5 / BIN2 | GPIO Output | 29 |
| DRV_STBY | PC4 | H1-13 | J7-2 / STBY | GPIO Output，初始化低 | 44 |
| ENC_L_A | PC6 | H2-50 | J7-10 / E1A | TIM3_CH1 / AF2 | 96 |
| ENC_L_B | PC7 | H2-49 | J7-12 / E1B | TIM3_CH2 / AF2 | 97 |
| ENC_R_A | PB6 | H2-32 | J7-9 / E2A | TIM4_CH1 / AF2 | 136 |
| ENC_R_B | PB7 | H2-19 | J7-11 / E2B | TIM4_CH2 / AF2 | 137 |
| SERVO_PWM | PE9 | H1-36 | J1-3 / PWM | TIM1_CH1 / AF1 | 60 |
| UART3_TX | PB10 | H2-28 | J3-2 / 模块RX | USART3_TX / AF7 | 69 |
| UART3_RX | PB11 | H2-29 | J3-3 / 模块TX | USART3_RX / AF7 | 70 |
| GRAY_AD0 | PF0 | H1-47 | J2-3 / AD0 | GPIO Output | 10 |
| GRAY_AD1 | PF1 | H1-48 | J2-4 / AD1 | GPIO Output | 11 |
| GRAY_AD2 | PF2 | H1-45 | J2-5 / AD2 | GPIO Output | 12 |
| GRAY_OUT | PC5 | H1-16 | J2-2 / OUT，直连 | GPIO Input / No Pull，不用ADC | 45 |
| US_L_TRIG | PA1 | H1-5 | J4-2 / TRIG | GPIO Output，初始化低 | 35 |
| US_L_ECHO | PF6 | H1-21 | J4-3 / ECHO，直连 | TIM10_CH1 / AF3 / No Pull | 18 |
| US_C_TRIG | PA5 | H1-11 | J5-2 / TRIG | GPIO Output，初始化低 | 41 |
| US_C_ECHO | PF7 | H1-22 | J5-3 / ECHO，直连 | TIM11_CH1 / AF3 / No Pull | 19 |
| US_R_TRIG | PA7 | H1-14 | J6-2 / TRIG | GPIO Output，初始化低 | 43 |
| US_R_ECHO | PF8 | H1-19 | J6-3 / ECHO，直连 | TIM13_CH1 / AF9 / No Pull | 20 |

PG10（H2-20，封装脚 125）额外配置为 `SRAM_CS` 推挽输出、上拉、初始高，先于 PF0/PF1/PF2 与 PE9 配置，保持板载 SRAM 未选中。不开启 FSMC、DCMI 或 ADC，不插 LCD/摄像头。PA0、PF3、旧 PD0–PD6 控制脚和 PE5/PE6 Echo 不再使用。PA13/PA14 保留 SWD。

## 板载 CH340 / USB 串口

核心板 USB_TTL 口的 CH340C 使用 **USART1**，新增这一路通信不改变上述 24 根载板信号。依据核心板原理图第 1、3 页：

| 网络 | GPIO | 核心板端点 | 外设配置 | 芯片脚号 |
| --- | --- | --- | --- | --- |
| UART1_TX | PA9 / H2-36 | JP3-3，经 3–4 跳帽连接 CH340 RXD | USART1_TX / AF7 | 101 |
| UART1_RX | PA10 / H2-35 | JP3-1，经 1–2 跳帽连接 CH340 TXD | USART1_RX / AF7 | 102 |

USB_TTL / CH340 和 USB_OTG 是两只不同的 USB 接口。板载串口选 CH340 的 COM（用户本机为 COM5），9600 8N1。CH340 的 RTS#/DTR#连接自动下载电路，正常车控不使用它们操作 RESET/BOOT0；上位机在打开前设 DTR=False、RTS=False。两路 UART 独立收发，命令在哪一路进入，响应就在哪一路返回。需要本次新增 USART1 的固件，旧的仅 USART3 固件不会回复板载 COM。

## 定时器与驱动

| 用途 | 时钟 / PSC / ARR | 固件行为 |
| --- | --- | --- |
| 舵机 TIM1 CH1 / PE9 | 168 MHz / 167 / 19999 | 50 Hz，1500 µs 中位；初始机械限位 1300–1700 µs。DS3218 支持 50–330 Hz、500–2500 µs；不可把额定全行程直接用于转向机构。 |
| 电机 TIM5 CH3/CH4 / PA2/PA3 | 84 MHz / 0 / 4199 | 两路 20 kHz、初始零；PC4 STBY 初始低，更新方向前关闭 STBY 并提交零 PWM。 |
| 左 / 右编码器 TIM3 / TIM4 | PSC=0 / ARR=65535 | 两路均为 **16 位**，TI12 x4，输入滤波 4、上拉；按有符号 16 位差值处理回绕。 |
| 左 / 中 Echo TIM10 / TIM11 | 168 MHz / 167 / 65535 | CH1 单通道上/下降沿配对，1 µs 计数。 |
| 右 Echo TIM13 | 84 MHz / 83 / 65535 | CH1 单通道配对，1 µs 计数。不能照抄 TIM10 的 PSC。 |
| USART3 PB10/PB11 | 9600 8N1，无流控 | MCU TX 接 JDY-31 RXD、MCU RX 接 JDY-31 TXD。JDY-31 默认波特率，对应 AT+BAUD4。 |
| USART1 PA9/PA10 | 9600 8N1，无流控 | 核心板 CH340 / USB_TTL；JP3 的 1–2、3–4 跳帽连接。 |

三路超声波以左、中、右顺序，每 60 ms 触发一只，每只约 180 ms 更新一次；12 µs TRIG、30 ms 超时。中途新测量尚未完成时保留上一有效结果；超过 600 ms 判过期。无上升沿、高电平卡死、无下降沿或不合格脉宽均上报无效（距离 `-1`）。无回波无法区分开阔场地与传感器未连接，因此不再上报伪造的 6000 mm。通过 `RANGE? L` / `RANGE? C` / `RANGE? R` 可读取触发/捕获计数、原始脉宽、计数器与错误原因。

共享中断：`TIM1_UP_TIM10` 处理 TIM1/TIM10，`TIM1_TRG_COM_TIM11` 处理 TIM1/TIM11，`TIM8_UP_TIM13` 处理 TIM13（本工程未启用 TIM8）。

灰度按 8 路模块数字扫描：PF0/PF1/PF2 为 AD0/AD1/AD2，PC5 为无上下拉数字输入；AD2 AD1 AD0 的 000→CH1，…，111→CH8。EN 在模块上已有 10 kΩ 下拉，无须新增控制脚。更新 F103 源码每次切换等待 500 µs，本工程采用该值；PDF 和官方小车源码仍是 50 µs。整组等待约 4 ms，控制周期维持 10 ms。默认 CH1→CH8 对应左→右、低电平为黑，实际安装方向和赛道极性须用 `LINE?` 核对。标定项集中在 [car_config.h](Core/Inc/car_config.h)。

## JDY-31 四针转接

| 实物 JDY-31 端点 | 本工程端点 | 说明 |
| --- | --- | --- |
| RXD | PB10 / H2-28 / 原载板 J3-2 | MCU TX → 模块 RX。 |
| TXD | PB11 / H2-29 / 原载板 J3-3 | 模块 TX → MCU RX。 |
| GND | 公共地 / 原载板 J3-4 | 必须与 MCU 共地。 |
| VCC | 按实际底板供电规格接电源 | 裸模块 1.8–3.6 V，推荐 3.3 V；四针底板的 5 V 兼容性待核对。 |

原载板 J3-1 为 STATE 不接、J3-5 为 +5 V、J3-6 为原 3V3 不接。JDY-31 不需要 KEY/STATE/CTS/RTS 软件控制；原 J3-6 不能当成已接好的 3.3 V 电源。按丝印确认四针顺序，用转接线连接；不能把四针模块直接套用原六针针序。

## 接线边界

- 三路 Echo 及灰度 OUT 按 V3.1 保持直连和无上下拉。该接线的电平条件、上电顺序及待测项目见基线第 5 节；不沿用旧版强制分压建议。
- JDY-31 **裸模块** VCC 为 1.8–3.6 V、建议 3.3 V。J3 的 +5 V 只有在确认四针底板支持 5 V 输入后才可使用；官方裸模块手册没有给出这块四针底板的稳压保证。旧 DX-BT24 资料仅供历史对照。
- DS3218 电源范围 4.8–6.8 V；5 V 堵转电流 1.8 A。舵机与电机的峰值供电预算尚须实测。不得从 MCU 3.3 V 输出给舵机供电。
- 默认 D24A A/B 驱动，J7 没有 GND，仍需按原接线通过 J8 共地。备用 TB6612 的使用条件、USB/外部 5 V 互斥要求均保留，详见归档基线。
- 固件异常入口会立即拉低 STBY、清零电机 PWM；复位/下载期间的硬件默认低电平仍取决于实际驱动板电路。

[if_car.ioc](if_car.ioc) 保存外设配置；[pinout.csv](pinout.csv) 保存完整 **144 个芯片封装脚**；[board_pinout.csv](board_pinout.csv) 保存 **24 根载板信号及新增 2 根板载 CH340 信号**的排针与外设端点。CSV 已按本次配置同步，由一致性测试核对，未声称由本次 CubeMX 界面重新导出。

资料清单及完整审查结果见 [docs/README.md](docs/README.md) 和 [审查记录](docs/REVIEW_2026-09-30.md)。旧版引脚资料在 `docs/archive` 中，仅用于追溯。
