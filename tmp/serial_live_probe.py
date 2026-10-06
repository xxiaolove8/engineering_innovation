"""One targeted read-only COM5 probe; never sends motion/reset commands."""
import ctypes
import json
import time
from datetime import datetime
from pathlib import Path
import serial
from serial import win32

report = {"time": datetime.now().isoformat(), "port": "COM5", "baudrate": 9600,
          "format": "8N1", "dtr": False, "rts": False, "exchanges": []}
port = serial.Serial(None, 9600, timeout=0.25, write_timeout=2.0,
                     bytesize=8, parity="N", stopbits=1, xonxoff=False,
                     rtscts=False, dsrdtr=False)
try:
    port.dtr = port.rts = False
    port.port = "COM5"
    port.open()
    dcb = win32.DCB()
    dcb.DCBlength = ctypes.sizeof(dcb)
    if not win32.GetCommState(port._port_handle, ctypes.byref(dcb)):
        raise ctypes.WinError()
    names = ("BaudRate", "ByteSize", "Parity", "StopBits", "fDsrSensitivity",
             "fOutxCtsFlow", "fOutxDsrFlow", "fDtrControl", "fRtsControl",
             "fInX", "fOutX", "fNull", "fErrorChar", "fAbortOnError")
    report["windows_dcb"] = {name: getattr(dcb, name) for name in names}
    report["modem_inputs"] = {name: getattr(port, name) for name in ("cts", "dsr", "cd")}
    idle = port.read(161)
    report["idle_rx_hex"] = idle.hex(" ").upper()
    port.timeout = 2.0
    for attempt in range(1, 4):
        payload = b"PING\n"
        started = time.monotonic()
        written = port.write(payload)
        reply = port.read(161)
        report["exchanges"].append({"attempt": attempt,
            "tx_hex": payload.hex(" ").upper(), "written_bytes": written,
            "rx_hex": reply.hex(" ").upper(), "rx_bytes": len(reply),
            "elapsed_seconds": round(time.monotonic() - started, 3)})
except Exception as exc:
    report["error"] = repr(exc)
finally:
    port.close()
    output = Path("tmp") / ("usb_raw_probe_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(output.resolve())
