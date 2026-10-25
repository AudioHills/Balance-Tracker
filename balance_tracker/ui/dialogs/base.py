"""The common dialog frame: title, subtitle, content, then Save/Cancel."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout

from ..widgets import label


class BaseDialog(QDialog):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(24, 22, 24, 20)
        self.outer.setSpacing(14)
        self.outer.addWidget(label(title, "PageTitle"))
        if subtitle:
            self.outer.addWidget(label(subtitle, "PageSubtitle", wrap=True))

    def add_buttons(self, ok_text: str = "Save") -> QDialogButtonBox:
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = bb.button(QDialogButtonBox.Ok)
        ok.setText(ok_text)
        ok.setObjectName("Primary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.outer.addWidget(bb)
        return bb


def form(spacing: int = 10) -> QFormLayout:
    """A right-aligned label/field form, as used by every dialog."""
    f = QFormLayout()
    f.setLabelAlignment(Qt.AlignRight)
    f.setHorizontalSpacing(14)
    f.setVerticalSpacing(spacing)
    return f
