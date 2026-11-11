#!/usr/bin/env python3
"""Compatibility filename for the audited repair CLI.

The previous delete-and-reinsert routine is retired. Old --from-date invocations
now fail argument parsing without touching data; use fetch/plan/apply explicitly.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.repair_daily_quotes import main


if __name__ == "__main__":
    raise SystemExit(main())
