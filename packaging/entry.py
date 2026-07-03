"""PyInstaller entry point. Kept as a real file so `pyinstaller packaging/entry.py`
has a script to freeze; it just delegates to the normal CLI."""

import sys

from cocert.cli import main

if __name__ == "__main__":
    sys.exit(main())
