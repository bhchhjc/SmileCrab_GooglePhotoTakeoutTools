"""Core engine package for low-level metadata, parsing, matching, and OS synchronization."""

from src.core.i18n import I18nManager, i18n, t
from src.core.power_management import SleepInhibitor

__all__ = ["SleepInhibitor", "I18nManager", "i18n", "t"]
