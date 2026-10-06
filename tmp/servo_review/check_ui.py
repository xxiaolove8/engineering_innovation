import sys
from pathlib import Path
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from host.gui import App

root = tk.Tk()
root.withdraw()
root.attributes("-alpha", 0)
with patch.object(App, "_refresh_ports", return_value=None):
    app = App(root)
try:
    app.view.tabs.select(app.view.debug_page)
    root.deiconify()
    for width, height in ((1180, 840), (1000, 700)):
        root.geometry(f"{width}x{height}")
        root.update()
        page = app.view.debug_page
        body_width = page.body.winfo_width()
        overflow = [
            (card.winfo_reqwidth(), body_width)
            for card in page.body.winfo_children()
            if card.winfo_reqwidth() > body_width
        ]
        print(f"{width}x{height}: actual={root.winfo_width()}x{root.winfo_height()}, body={body_width}, cards={[c.winfo_reqwidth() for c in page.body.winfo_children()]}")
        if overflow:
            raise RuntimeError(f"Horizontal overflow: {overflow}")
finally:
    app._close()
    app.worker.join(3)
