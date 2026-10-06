# 旧 BT24 BLE 支持

当前车辆使用 JDY-31 经典蓝牙 SPP / USB-TTL；BT24 的 GATT 实现移入本目录，保留旧硬件调试能力。它不属于固件编译输入。

```powershell
.\.venv\Scripts\python.exe -m pip install -r host/requirements-ble.txt
.\.venv\Scripts\python.exe -m host.legacy.ble_check --target BT24
```

GUI 的连接方式“旧 BT24 BLE”和 `host.range_check --ble BT24` 仍可用。Python 导入路径为 `host.legacy.ble_link`；原 `host.ble_link` / `host.ble_check` 入口已移除。JDY-31 使用系统生成的出站 COM，不走这里的 FFE0/FFE1/FFE2 服务。

历史模块与当时实物联调情况见 [BT24 联调记录](../../docs/BT24_DEBUG_2026-09-30.md)，当前工程维护见 [维护记录](../../docs/MAINTENANCE_2026-09-30.md)。
