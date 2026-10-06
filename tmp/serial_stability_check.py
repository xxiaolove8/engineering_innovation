"""Read-only checks of real COM6 and the GUI connection pipeline."""
import json
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from host.protocol import SerialLink, CarClient
from host.gui import App

report = {"time": datetime.now().isoformat(), "port": "COM6", "sessions": [], "ok": False}
try:
    for session in range(1, 6):
        client = CarClient(SerialLink("COM6"))
        try:
            timings = []
            for _ in range(20):
                began = time.monotonic()
                reply = client.request("PING")
                assert reply == "PONG 2", reply
                timings.append(time.monotonic() - began)
            hardware = client.request("HW?")
            status = client.request("STATUS?")
            report["sessions"].append({"session": session, "ping_count": 20,
                "max_response_ms": round(max(timings) * 1000, 2),
                "hardware": hardware, "status": status,
                "serial": client.link.receive_diagnostics()})
        finally:
            client.close()
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    app.port.set("COM6")
    app._connect_serial()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        root.update()
        if app.connected and app.last_state and not app._initializing and not app._pending:
            break
        time.sleep(.01)
    report["gui"] = {"connected": app.connected, "state": app.last_state,
        "ready": app.ready, "notice": app.notice.get(),
        "hardware": app.hardware_info.get(), "logs": list(app._logs)}
    assert app.connected and app.ready and app.last_state == "IDLE", report["gui"]
    assert any("RX" in line and "PONG 2" in line for line in app._logs)
    app._close()
    app.worker.join(3)
    assert not app.worker._thread.is_alive(), "GUI worker did not close the serial port"
    report["ok"] = True
except Exception as exc:
    report["error"] = repr(exc)
finally:
    output = Path("tmp/usb_com6_verified_20261001.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "sessions"}, ensure_ascii=False, indent=2))
    print("successful sessions:", len(report["sessions"]))
    print(output.resolve())
