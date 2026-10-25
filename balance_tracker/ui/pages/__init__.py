"""The six main pages, in sidebar order."""
from .checkins import CheckinsPage
from .common import Page
from .dashboard import DashboardPage
from .debts import DebtsPage
from .items import ItemsPage
from .ledger import LedgerPage
from .settings import SettingsPage

__all__ = ["CheckinsPage", "DashboardPage", "DebtsPage", "ItemsPage", "LedgerPage", "Page", "SettingsPage"]
