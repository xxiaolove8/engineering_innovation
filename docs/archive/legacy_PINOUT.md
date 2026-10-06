# 小车引脚与 CubeMX 配置

目标芯片：STM32F407ZGT6，LQFP144。下表的序号是**芯片封装脚号**，不是开发板排针号；焊接前须对照实际主控板原理图核实引出情况。

| 模块 | 信号 / 接法 | MCU 引脚（封装脚号） | CubeMX 配置 |
| --- | --- | --- | --- |
| 前轮舵机 | 信号线 | PE9（60） | TIM1_CH1，50 Hz PWM |
| TB6612 A 路＝左后电机 | PWMA | PC6（96） | TIM3_CH1，20 kHz PWM |
|  | AIN1 / AIN2 | PD0（114）/ PD1（115） | 推挽输出 |
| TB6612 B 路＝右后电机 | PWMB | PC7（97） | TIM3_CH2，20 kHz PWM |
|  | BIN1 / BIN2 | PD2（116）/ PD3（117） | 推挽输出 |
| TB6612 共用 | STBY | PD4（118） | 推挽输出，上电初始为低 |
| 左电机编码器 | A / B | PA0（34）/ PA1（35） | TIM2_CH1/CH2，编码器 x4，内部上拉 |
| 右电机编码器 | A / B | PB6（136）/ PB7（137） | TIM4_CH1/CH2，编码器 x4，内部上拉 |
| 左侧超声波 | TRIG / ECHO | PD5（119）/ PE5（4） | GPIO 输出 / TIM9_CH1 输入捕获 |
| 右侧超声波 | TRIG / ECHO | PD6（122）/ PE6（5） | GPIO 输出 / TIM9_CH2 输入捕获 |
| 串口蓝牙 | MCU TX → 模块 RX | PB10（69） | USART3_TX，9600 8N1 |
|  | MCU RX ← 模块 TX | PB11（70） | USART3_RX，9600 8N1 |
| 灰度模块 | S0 / S1 / S2 | PF0（10）/ PF1（11）/ PF2（12） | 三路推挽输出，初始 000 |
| 灰度模块 | OUT | PF3（13） | 数字输入，无内部上下拉 |
| 调试下载 | SWDIO / SWCLK | PA13（105）/ PA14（109） | Serial Wire，保留 |

## 定时器参数

- TIM1：定时器时钟 168 MHz，PSC=167、ARR=19999，计数单位 1 µs，周期 20 ms；CH1 初始 CCR=1500。实际舵机的中位和左右极限需上车标定。
- TIM3：定时器时钟 84 MHz，PSC=0、ARR=4199，两路 20 kHz PWM；CH1/CH2 初始占空比均为 0。左/右电机分别独立调速。
- TIM2：32 位编码器计数；TIM4：16 位编码器计数。均使用 TI1+TI2 的 x4 模式，输入滤波值 4。软件需启动编码器并周期性读取差分计数。
- TIM9：定时器时钟 168 MHz，PSC=167、ARR=65535，1 µs 输入捕获计数单位。CH1/CH2 初始捕获上升沿；软件需在回波上升沿后切换为下降沿并处理超时。两个超声波轮流触发，避免互相串音。TIM9 与 TIM1 的 BRK 中断共用 `TIM1_BRK_TIM9_IRQn`。
- USART3：9600、8N1，已打开串口中断。若实际蓝牙模块默认波特率不同，应同步修改两端。

## 接线和供电

1. 普通三线位置舵机的控制信号可由 PE9 的 PWM 直接提供，通常不需要额外舵机驱动板。舵机电源应使用符合其规格的独立稳压供电，按堵转电流留余量，**不能从 MCU 的 3.3 V 引脚取电**；舵机地与 MCU 地共地。若所购舵机不识别 3.3 V 高电平，给信号线加电平转换。
2. TB6612 的 `VCC` 接 3.3 V 逻辑电源，`VM` 接符合电机与驱动板规格的电机电源，所有地共地。确认每个电机的堵转电流没有超过驱动板额定值。`STBY` 上电保持低，控制程序准备好后再拉高。
3. 超声波型号未定。若选择常见的 5 V HC-SR04 类模块，ECHO 可能是 5 V 输出，应在 PE5/PE6 前做电平转换；例如上臂 10 kΩ、下臂 20 kΩ 分压约为 3.33 V。选定型号后再核实供电、触发脉宽与电平。
4. 灰度模块按你说明的“三根寻址线 + 一个数字 OUT”连接。软件将 S0/S1/S2 作为地址位逐路读取 OUT；实际地址顺序、黑白对应电平、切换后稳定时间须按模块实测确认。六路模块只扫描有效的六个地址。
5. 蓝牙模块电源与信号电平要以所购模块为准。MCU 的所有输入（蓝牙 TX、灰度 OUT、编码器及超声波 ECHO）接线前都要确认不会超出芯片输入范围。

CubeMX 工程在 [if_car.ioc](if_car.ioc)；[pinout.csv](pinout.csv) 是 CubeMX 导出的完整封装引脚表。当前生成的是外设初始化框架，电机控制、舵机角度控制、编码器测速、巡线采样和测距逻辑需要在后续应用代码中实现。

参考：[ST STM32F407ZG](https://www.st.com/en/microcontrollers-microprocessors/stm32f407zg.html)、[TB6612FNG 数据手册](https://toshiba.semicon-storage.com/info/datasheet_en_20141001.pdf?did=10660)、[HC-SR04 模块资料](https://www.elecfreaks.com/download/HC-SR04.pdf)、[舵机供电与接线](https://learn.adafruit.com/using-servos-with-circuitpython/hardware)。
