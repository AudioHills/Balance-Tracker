"""Launcher used by PyInstaller and for `python main.py`."""
import sys

from balance_tracker.app import main

if __name__ == "__main__":
    sys.exit(main())
