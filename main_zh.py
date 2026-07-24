"""Simplified Chinese entry point for PL Analyzer Pro."""

from __future__ import annotations

from main import main
from ui.localization import AppLanguage

if __name__ == "__main__":
    raise SystemExit(main(AppLanguage.ZH_CN))
