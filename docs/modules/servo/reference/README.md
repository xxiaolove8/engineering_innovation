# 舵机官方代码参考

从 `D:\projects\docs` 选取 16 个与本次舵机排查直接相关的源文件，按原始字节复制；没有修改父目录原件。原路径、大小和 SHA256 见 [归档清单](../../../archive_manifest.json)。这是用于追溯的源码节选，不是可以独立编译或烧录的完整例程。

| 文件前缀 | 来源与用途 |
| --- | --- |
| `single_f103_*` | “32 单个舵机控制源码”：F103 的 8 路 TIM2 中断软件 PWM、自动 1000/2000 µs 往返。 |
| `single_stc15_*` | 51 单舵机源码：8 路定时中断软件 PWM，含该 STC 时钟专用校准值。 |
| `single_arduino*` | Arduino 单舵机及蓝牙/PS2 控制参考；脉宽单位为 µs，扫描下限存在与注释不一致的问题。 |
| `controller_f103_*` | 多路控制器的启动、舵机计时、引脚和默认值；依赖 W25Q64，不能直接移植到当前板子。 |
| `controller_stc15_*` | 51 控制器：`timer.c` 是舵机时序，`pwm.c` 是电机 PWM。 |
| `controller_arduino*` | Arduino 控制器的 attach、插值和 detach 行为。 |
| `jdy31_f103_*` | JDY-31 配套程序与附带 PWM 文件；实际 main 只运行串口控制 LED，没有启动舵机 PWM。 |

本目录不加入小车的 CMake 源文件列表。完整对照、已确认的未共地问题及测试步骤见 [舵机例程核对](../../../SERVO_EXAMPLE_REVIEW_2026-09-30.md)。
