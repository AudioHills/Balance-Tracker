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

# Web app (iPhone home screen) icons
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter, QColor  # noqa: E402

web = out.parent / "web" / "icons"
web.mkdir(parents=True, exist_ok=True)


def full_bleed(size: int) -> QImage:
    """iOS rounds the corners itself, so draw the icon edge to edge."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(QColor("#4F5FE8"))
    p = QPainter(img)
    inner = render(int(size * 1.18))
    p.drawImage(-(inner.width() - size) // 2, -(inner.height() - size) // 2, inner)
    p.end()
    return img


for s in (180, 192, 512):
    full_bleed(s).save(str(web / f"icon-{s}.png"))
mask = QImage(512, 512, QImage.Format_ARGB32)
mask.fill(QColor("#4F5FE8"))
p = QPainter(mask)
p.drawImage(76, 76, render(360))
p.end()
mask.save(str(web / "maskable-512.png"))
print("wrote web icons")
