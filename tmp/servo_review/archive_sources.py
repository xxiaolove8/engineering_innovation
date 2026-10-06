"""Preserve selected vendor references without modifying parent originals."""
from pathlib import Path
import hashlib
import json
import shutil

root = Path(r"D:\projects\if_car")
parent = Path(r"D:\projects\docs")
destination = root / "docs/modules/servo/reference"
destination.mkdir(parents=True, exist_ok=True)
sources = {
    "single_f103_main.c": "单个舵机驱动代码/32单个舵机控制源码/USER/main.c",
    "single_stc15_main.c": "单个舵机驱动代码/51单个舵机控制源码/src/main.c",
    "single_arduino.ino": "单个舵机驱动代码/arduino单个舵机控制源码/singleServo/singleServo.ino",
    "single_arduino_ps2.ino": "单个舵机驱动代码/arduino单个舵机控制源码/bluetoothPS2ControlServo/bluetoothPS2ControlServo.ino",
    "controller_f103_main.c": "舵机控制器代码源码/32控制器源码/USER/main.c",
    "controller_f103_timer.c": "舵机控制器代码源码/32控制器源码/TB_LIB/TIMER/tb_timer.c",
    "controller_f103_gpio.c": "舵机控制器代码源码/32控制器源码/TB_LIB/GPIO/tb_gpio.c",
    "controller_f103_global.c": "舵机控制器代码源码/32控制器源码/TB_LIB/GLOBAL/tb_global.c",
    "controller_stc15_main.c": "舵机控制器代码源码/51控制器源码/src/main.c",
    "controller_stc15_pwm.c": "舵机控制器代码源码/51控制器源码/src/pwm.c",
    "controller_stc15_timer.c": "舵机控制器代码源码/51控制器源码/src/timer.c",
    "controller_arduino.ino": "舵机控制器代码源码/arduino控制器源码/L_JXB/L_JXB.ino",
    "controller_arduino_servo.ino": "舵机控制器代码源码/arduino控制器源码/L_JXB/handle_duoji.ino",
    "jdy31_f103_main.c": "蓝牙串口模块JDY-31（4针）/STM32_LY/User/main.c",
    "jdy31_f103_pwm.c": "蓝牙串口模块JDY-31（4针）/STM32_LY/Hardware/PWM.c",
    "jdy31_f103_servo.c": "蓝牙串口模块JDY-31（4针）/STM32_LY/Hardware/servo.c",
}
manifest_path = root / "docs/archive_manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
entries = {entry["path"]: entry for entry in manifest["files"]}
for name, relative in sources.items():
    original = parent / relative
    target = destination / name
    original_bytes = original.read_bytes()
    if target.exists() and target.read_bytes() != original_bytes:
        raise RuntimeError(f"Different archive already exists: {target}")
    if not target.exists():
        shutil.copyfile(original, target)
    assert target.read_bytes() == original.read_bytes() == original_bytes
    archive_path = target.relative_to(root / "docs").as_posix()
    entries[archive_path] = {
        "path": archive_path,
        "bytes": len(original_bytes),
        "sha256": hashlib.sha256(original_bytes).hexdigest(),
        "original": original.as_posix(),
    }
manifest["files"] = list(entries.values())
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
for entry in manifest["files"]:
    data = (root / "docs" / entry["path"]).read_bytes()
    assert len(data) == entry["bytes"], entry["path"]
    assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
print(f"Preserved {len(sources)} servo references; verified all {len(manifest['files'])} manifest entries.")
