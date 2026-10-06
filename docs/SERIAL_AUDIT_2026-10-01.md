# 串口链路深查与启动向量修复（2026-10-01）

**最终实机结果：串口已恢复。**正常复位现有程序后，COM6 返回 PONG 2；5 次重新打开连接、连续 100 次 PING、真实 GUI 的握手与初始化均通过。此次没有改写板上 Flash，没有修改 PID 参数，没有发送运动命令。验收记录见 [COM6 实机与 GUI](../tmp/usb_com6_verified_20261001.json)。

## 本次现场证据

用户确认已用 ST-Link 烧录此前的 Release HEX，PA9→CH340 RX、PA10←CH340 TX 与 JP3 跳帽已接好。在线工具在 9600 8N1 下没有得到有效 `PONG 2`；截图中小写 `ping` 后收到 `BF BF FF`。截图显示 5 Bytes，不能由此判断最后一个字节是 LF 还是 CR。用户随后确认大写 PING 也没有有效回应。

直接使用工程串口后端打开真实 COM5，发送 `50 49 4E 47 0A`（大写 PING 加 LF），驱动完整接受 5 字节，2 秒收到 0 字节。原始记录：[第一次只读检查](../tmp/usb_ping_live_20260930.json)。绕过 GUI 再用 pySerial 做 3 次相同的只读检查，每次均完整写入 5 字节、约 2 秒收到 0 字节；打开后的空闲接收也为空。记录：[原始串口与 Windows DCB](../tmp/usb_raw_probe_20260930_235947.json)。这些请求只发送 PING，没有运动、复位或烧录操作。

实际 Windows DCB 是 9600、8 位、无校验、1 停止位；DTR/RTS 关闭，CTS/DSR/XON/XOFF 流控关闭，`fDsrSensitivity=0`、`fErrorChar=0`、`fNull=0`、`fAbortOnError=0`。DSR 输入虽为 false，但当前接收过滤已关闭，不能将 DSR 过滤认定为这次零字节的原因。原始 `serialwin32.py` 确实可能继承 fDsrSensitivity，该潜在状态与本次实测状态必须区分。[微软 DCB 说明](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-dcb)。

起初没有检测到 ST-Link。用户接回 ST-Link 后，以下现场测量确认了本次启动状态；此前的历史 ROM 记录与本次新测量分别保存。

## 板端实际状态与恢复

HOTPLUG 测量得到 Core running、`VTOR=0x1FFF0000`；零地址向量为 `20002D98 / 1FFF4BCD`，映射到系统 ROM。USART1 和 USART3 的 BRR/CR1/CR2/CR3 全为 0，前两组 NVIC ISER 全为 0，SysTick CTRL=4、未使能。这组读数表明当时仍处于系统 Bootloader 状态，应用的 UART 没有初始化。COM6 在此状态下完整写入 PING 后仍收到 0 字节，记录见 [COM6 启动前](../tmp/usb_com6_before_start_20261001.json)。

先备份应用 Flash 前 69632 字节和 sector 11 的 131072 字节 PID 区。用旧 SystemInit 对象在独立临时目录重建 Debug 镜像后，前 66192 字节与板上 Flash 完全相同，差异为 0；证明板上确实是此前支持 USART1 的 Debug 程序。用户使用 ST-Link 下载，板内实际镜像并非此前提问中提到的 Release。匹配时按 HEX 未加载填充洞保持 FF，而非将 BIN 的零填充当成程序不同。完整结果见 [固件身份比对](../tmp/serial_identity/full_flash_comparison.json)。

通过 ST-Link 执行一次正常软件复位，没有写 Flash。随后零地址映射到应用向量 `20020000 / 08006335`，VTOR=0（正常复位别名），USART1 BRR=`0x222E`、USART3 BRR=`0x1117`、两路 CR1=`0x202C`，UART NVIC 与 SysTick 均正常启用。COM6 立即返回 `PONG 2`，原始 HEX 为 `50 4F 4E 47 20 32 0A`，见 [复位后握手](../tmp/usb_com6_after_reset_20261001.json)。

当前可确定的直接问题是板子当时处于下载器状态，未正常进入应用；按当前启动配置正常复位可以恢复。没有直接测量物理 BOOT0 电平，也没有把原因归结为接线或某个下载工具设置。实际复位成功后不需要用户在未知位置尝试移动跳帽。

## 固件静态与链接核查

- USART1 是 PA9/PA10 AF7，USART3 是 PB10/PB11 AF7。两路均 9600 8N1，UART 与 GPIO 时钟及 IRQ 均已开启，后续代码没有重配 PA9/PA10。
- 当前 PLL 来源是 HSI 16 MHz，得到 SYSCLK 168 MHz、PCLK2 84 MHz、PCLK1 42 MHz。真实 HAL 对 USART1 使用 PCLK2，因此 BRR 应为 `0x222E`；USART3 使用 PCLK1，BRR 应为 `0x1117`。当前 HSE 默认 25 MHz 与板图外部 8 MHz 的潜在差异不参与这条 HSI 时钟路径，不能据此解释本次乱码。
- Release 向量表链接在 `0x08000000`，USART1/USART3 中断及 RX/TX/Error 回调均为强符号，向量项确实指向对应处理函数。
- 独立收发缓冲、来源回复、初始化顺序、真实 HAL RX 重装和 TXE/TC 回调均核对。主循环处理每次最多两个命令，灰度延时有有限上界，测距采用非阻塞状态，执行器初始化失败时仍能处理 PING/HW?。
- 大写 `PING\n` 应回复 `PONG 2\n`，HEX 是 `50 4F 4E 47 20 32 0A`。小写 `ping\n` 应回复 `ERR COMMAND\n`；只有 CR 没有 LF 时不执行。当前所有车控回复均为 ASCII，`BF BF FF` 不是本工程设计的回复。

## 确定的启动兼容性缺失

原 `SystemInit()` 中 `USER_VECT_TAB_ADDRESS` 未启用，默认分支没有设置 VTOR。原 Release 反汇编只有 FPU 设置后返回，证明实际固件也没有写 VTOR。

如果下载器/Bootloader 在 VTOR 仍指向系统 ROM 时跳转到应用，启动后的 UART/SysTick 中断仍会进入 ROM；`HAL_Delay(1)` 又依赖 SysTick，这条路径可能同时破坏串口与主循环。ST [AN3155 的 Go 命令说明](https://www.st.com/resource/en/application_note/an3155-how-to-use-usart-protocol-in-bootloader-on-stm32-mcus-stmicroelectronics.pdf)要求应用设置正确的向量表；[当前官方 F4 模板](https://github.com/STMicroelectronics/cmsis-device-f4/blob/master/Source/Templates/system_stm32f4xx.c)也会在默认路径设置 Flash VTOR。

修复在 `SystemInit()` 将 VTOR 指向链接的 `g_pfnVectors`，再执行 DSB/ISB，早于 HAL 初始化和开启 UART 中断。使用链接符号避免硬编码另一个应用地址，且不依赖尚未初始化的数据区；移除未使用的手填偏移模板，以实际链接向量为准。

这是一处有代码和反汇编证据的兼容性缺失。现场恢复依靠正常复位现有 Debug 程序；新的 VTOR 补强已编译并测试，尚未烧到板上，不能将这次恢复归功于新固件。没有改变 PRIMASK/BASEPRI，也没有把其他未知 Bootloader 状态当作已解决。

## 上位机改进

- 优先选择实际 CH340/USB 设备，保留仍存在的已选 COM，显示设备描述与 9600/8N1；不会把 COM5 写死为所有电脑的默认值。
- 日志分别记录打开串口、等待固件握手、收到 PONG 后连接成功。原始接收为空、没有结尾换行、乱码和不匹配响应会明确区分。
- `receive_diagnostics()` 保存实际配置、最后发送 HEX、驱动接受长度、最后接收 HEX/长度与结果状态，关闭后仍可读取。
- 整条响应使用总读取期限，普通命令 2 秒、PID SAVE 5 秒。慢速逐字节到达不能不断重置期限；失败后仍使会话失效，不自动重复运动命令。
- 只读工具支持 `--ping-only`，失败也保留原始接收与端口打开/握手状态。

关闭其他串口软件后，可运行：

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m host.serial_check --port COM6 --ping-only
```

## 验收与当前操作

- 当前板上仍为恢复前已烧录的 Debug 程序，实机 COM6/9600/8N1 通信已正常。
- 5 次重新打开连接，每次 20 次 PING，全部收到精确 PONG 2；最大响应延迟约 47 ms，HW? 均返回 HW 1 READY、STATUS? 均为 IDLE。
- 真实 GUI 使用 COM6 完成握手，读取 HW?、PID?、PID STORE?、STATUS?、CTRL?，显示硬件正常、实时监测中。随后 GUI worker 正常释放串口。验证只读取参数，没有改 PID 或控制电机/舵机。
- 7 个 C 测试程序与 124 项 Python 测试通过。新增启动回归实际编译并调用生产 SystemInit，模拟 ROM/零地址/RAM 向量初值；串口测试覆盖整条响应总期限、失败后失效与原始接收记录。
- Debug/Release 均编译成功；新 Debug Flash=66208 B / RAM=5000 B，新 Release Flash=48488 B / RAM=4960 B。新固件尚未实机烧录，实际通过的是上述旧 Debug 程序复位后的通信。
- 新 Release HEX SHA256：`f08dfb9981188cf92eb7fda80c7f91ffa39f4d6648fd5dca4e05160a1d90b04f`。

当前操作：下载成功后按一次板上的 RESET，启动应用；重启 start_gui.cmd，选择实际 CH340 端口 COM6，9600 8N1。握手成功的标志是收到 PONG 2。串口工具与 GUI 分别使用 COM6，先断开前一个软件以释放端口。BOOT0 的物理位置用户仍不确定，但本次正常复位已成功，不需要为了测试随意改跳帽。车辆其他功能按用户要求暂不继续调试。
