"""The keyboard shortcuts list (F1)."""
from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox, QGridLayout

from ..widgets import label
from .base import BaseDialog


class ShortcutsDialog(BaseDialog):
    def __init__(self, shortcuts: list[tuple[str, str]], parent=None):
        super().__init__("Keyboard shortcuts", parent=parent)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        for row, (keys, what) in enumerate(shortcuts):
            grid.addWidget(label(keys, "Kbd"), row, 0)
            grid.addWidget(label(what), row, 1)
        self.outer.addLayout(grid)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        self.outer.addWidget(bb)
