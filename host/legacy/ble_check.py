"""Check BT24 GATT and the read-only PING handshake separately."""

import argparse
from datetime import datetime
from importlib.metadata import version
import json
from pathlib import Path
import sys
import time

from .ble_link import ALTERNATE_WRITE_UUID, BleLink, WRITE_UUID
from ..protocol import CarClient


def main(argv=None):
    parser = argparse.ArgumentParser(description="BT24 连接诊断；仅发送只读 PING")
    parser.add_argument("--target", default="BT24", help="广播名称或蓝牙地址")
    parser.add_argument("--write", choices=("FFE1", "FFE2"), default="FFE1", help="默认与网页通用Ⅰ型一致")
    parser.add_argument("--transport-only", action="store_true", help="只检查 GATT/通知，不发送 PING")
    parser.add_argument("--output", type=Path, help="诊断 JSON 文件，默认写入 tmp")
    args = parser.parse_args(argv)
    output = args.output or Path("tmp") / f"bt24_{datetime.now():%Y%m%d_%H%M%S}.json"
    started = time.monotonic()
    report = {"target": args.target, "write_requested": args.write,
              "python": sys.executable, "phases": [], "connection": None,
              "gatt_connected": False, "protocol_ready": False}
    try:
        report["bleak_version"] = version("bleak")
    except Exception:
        report["bleak_version"] = None

    def progress(message):
        report["phases"].append({"elapsed_s": round(time.monotonic() - started, 3), "message": message})
        print(message, flush=True)

    link = None
    result = 1
    try:
        link = BleLink(args.target, write_uuid=ALTERNATE_WRITE_UUID if args.write == "FFE2" else WRITE_UUID,
                       on_progress=progress)
        report["gatt_connected"] = True
        report["connection"] = link.connection_details
        if not args.transport_only:
            progress("验证小车固件 PING 握手")
            CarClient(link, lambda direction, text: progress(f"{direction}: {text}"))
            report["protocol_ready"] = True
            progress("小车固件握手通过：PONG 2")
        else:
            progress("GATT/接收通知检查通过；未验证小车固件")
        result = 0
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        progress(f"检查失败：{exc}")
    finally:
        if link is not None:
            report["receive"] = link.receive_diagnostics()
            try:
                link.close()
            except Exception as exc:
                report["close_error"] = str(exc)
                print(f"关闭连接失败：{exc}", flush=True)
                result = 1
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(f"诊断记录：{output.resolve()}", flush=True)
        except OSError as exc:
            print(f"无法保存诊断记录：{exc}", flush=True)
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
