"""Read-only bench logger for the three ultrasonic probes."""

import argparse
import csv
from dataclasses import asdict
from datetime import datetime
import math
from pathlib import Path
import time

from .protocol import CarClient, SerialLink, SimLink


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="三路超声波只读检查，保存原始诊断 CSV")
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--port", help="JDY-31 出站 SPP COM 口或 USB-TTL，例如 COM3")
    transport.add_argument("--ble", help="旧 BT24 BLE 广播名称或地址；JDY-31 请用 --port")
    transport.add_argument("--simulate", action="store_true", help="只验证日志工具流程")
    parser.add_argument("--duration", type=float, default=30.0, help="记录秒数，默认 30")
    parser.add_argument("--interval", type=float, default=1.0, help="每轮间隔秒数，至少 0.6")
    parser.add_argument("--output", type=Path, help="CSV 路径，默认写入 tmp 文件夹")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or not 0 < args.duration <= 3600:
        parser.error("duration 应在 0–3600 秒之间")
    if not math.isfinite(args.interval) or args.interval < 0.6:
        parser.error("interval 至少为 0.6 秒")
    output = args.output or Path("tmp") / f"range_{datetime.now():%Y%m%d_%H%M%S}.csv"
    client = None
    result = 1
    recorded = False
    try:
        if args.simulate:
            link = SimLink()
            print("界面仿真：这些记录不代表实物测量。")
        elif args.ble:
            from .legacy.ble_link import BleLink
            link = BleLink(args.ble)
        else:
            link = SerialLink(args.port)
        client = CarClient(link)
        if client.status().state != "IDLE":
            raise RuntimeError("请先在上位机停止车辆并退出连接，再运行待机测距检查")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8-sig", newline="") as stream:
            recorded = True
            writer = None
            started = time.monotonic()
            while time.monotonic() - started < args.duration:
                round_started = time.monotonic()
                if client.status().state != "IDLE":
                    raise RuntimeError("车辆已离开待机，结束测距检查")
                for side in ("L", "C", "R"):
                    diagnostic = client.range_diagnostics(side)
                    row = {"elapsed_s": round(time.monotonic() - started, 3), **asdict(diagnostic)}
                    if writer is None:
                        writer = csv.DictWriter(stream, fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    stream.flush()
                    print(f"{side} {diagnostic.state:12s} 距离={diagnostic.distance_mm} mm "
                          f"脉宽={diagnostic.pulse_us} us "
                          f"触发/上升/下降={diagnostic.triggers}/{diagnostic.rises}/{diagnostic.falls} "
                          f"超时={diagnostic.timeouts} 错误={diagnostic.errors} "
                          f"计数={diagnostic.counter} PSC={diagnostic.prescaler} "
                          f"运行={int(diagnostic.timer_running)} SR=0x{diagnostic.flags:x}")
                remaining = min(args.interval - (time.monotonic() - round_started),
                                args.duration - (time.monotonic() - started))
                if remaining > 0:
                    time.sleep(remaining)
        print(f"日志：{output.resolve()}")
        result = 0
    except KeyboardInterrupt:
        print(f"检查已结束，已有记录保存在：{output.resolve()}" if recorded else "检查已结束，尚未创建日志。")
        result = 0
    except Exception as exc:
        print(f"检查失败：{exc}")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                print(f"关闭连接失败：{exc}")
                result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
