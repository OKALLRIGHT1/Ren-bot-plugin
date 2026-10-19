"""Isuzu daily news thin entrypoint.

Implementation lives in magic_daily.plugin_impl (same package directory).
"""

from pathlib import Path
import sys

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from magic_daily.plugin_impl import Plugin

__all__ = ["Plugin"]