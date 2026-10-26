"""Every dialog in the app. Each one returns its result in a `result_*` attribute on accept."""
from ..widgets import date_edit, from_qdate, to_qdate
from .afford import AffordDialog
from .base import BaseDialog
from .checkin import CheckInDialog, WelcomeDialog
from .debt import DebtDialog
from .item import ChangeAmountDialog, ItemDialog
from .notify import NotifyDialog
from .reminders import RemindersDialog
from .security import BackupPasswordDialog, LockScreen, LockSetupDialog, SyncPassphraseDialog, ask_password
from .shortcuts import ShortcutsDialog

__all__ = [
    "AffordDialog", "BackupPasswordDialog", "BaseDialog", "ChangeAmountDialog", "CheckInDialog", "DebtDialog",
    "ItemDialog", "LockScreen", "LockSetupDialog", "NotifyDialog", "RemindersDialog", "ShortcutsDialog",
    "SyncPassphraseDialog", "WelcomeDialog", "ask_password", "date_edit", "from_qdate", "to_qdate",
]
