"""Read-only onboard CH340 / JDY-31 / USB-TTL handshake and diagnostics."""

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path

from .protocol import CarClient, SerialLink, SimLink


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="板载 CH340 / JDY-31 / USB-TTL 只读连接检查")
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--port", help="板载 CH340 / 外置 USB-TTL 的 USB COM，或 JDY-31 出站 SPP COM")
    transport.add_argument("--simulate", action="store_true", help="验证工具流程，结果为仿真数据")
    parser.add_argument("--ping-only", action="store_true", help="只验证 PING/PONG，不读取传感器或参数")
    parser.add_argument("--output", type=Path, help="JSON 路径，默认写入 tmp")
    args = parser.parse_args(argv)
    output = args.output or Path("tmp") / f"serial_{datetime.now():%Y%m%d_%H%M%S}.json"
    report = {"port": args.port, "simulated": args.simulate, "ok": False,
              "port_open": False, "handshake_ok": False, "exchanges": []}
    client = None
    link = None
    result = 1

    def log(direction, line):
        report["exchanges"].append({"direction": direction, "line": line})
        print(f"{direction}: {line}")

    try:
        link = SimLink() if args.simulate else SerialLink(args.port)
        report["port_open"] = True
        client = CarClient(link, log)
        report["handshake_ok"] = True
        if args.ping_only:
            report["ok"] = True
        else:
            report["hardware"] = asdict(client.hardware())
            report["status"] = asdict(client.status())
            report["line"] = asdict(client.line_diagnostics())
            report["ok"] = report["hardware"]["ready"]
        result = 0 if report["ok"] else 1
    except Exception as exc:
        report["error"] = str(exc)
        print(f"检查失败：{exc}")
    finally:
        if link is not None and hasattr(link, "receive_diagnostics"):
            report["serial"] = link.receive_diagnostics()
            received = report["serial"].get("last_rx_hex", "")
            print(f"串口原始 RX：{received or '（零字节）'}")
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                report["close_error"] = str(exc)
                result = 1
                print(f"关闭连接失败：{exc}")
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            print(f"诊断记录：{output.resolve()}")
        except OSError as exc:
            print(f"无法保存诊断记录：{exc}")
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
