"""Regenerate assets/icon.ico and assets/icon.png from the in-code icon drawing."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from balance_tracker.ui.icon import render  # noqa: E402

app = QGuiApplication([])
out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)
render(256).save(str(out / "icon.png"))
if not render(256).save(str(out / "icon.ico")):
    sys.exit("Qt could not write .ico on this system")
print("wrote", out / "icon.ico")
