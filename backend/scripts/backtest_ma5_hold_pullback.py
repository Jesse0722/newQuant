#!/usr/bin/env python3
"""回测「五日均线不破」策略：近30个交易日内的涨停股 universe + 本地日线。

用法（在 backend 目录）：
  ./venv/bin/python scripts/backtest_ma5_hold_pullback.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.database import SessionLocal
    from app.services.strategy_backtest import run_strategy_backtest
    from app.services.trade_date_resolver import last_n_resolved_trade_dates

    dates = last_n_resolved_trade_dates(30)
    if len(dates) < 2:
        print("交易日不足，无法回测", file=sys.stderr)
        return 1
    d0, d1 = dates[0], dates[-1]
    print(
        f"回测窗口: {d0} ~ {d1}（30 个交易日），"
        "universe=本地 daily_quote 区间内涨停股（去重，不拉外网）",
        flush=True,
    )

    db = SessionLocal()
    try:
        r = run_strategy_backtest(
            db,
            strategy_id="ma5_hold_pullback",
            trade_date_from=d0,
            trade_date_to=d1,
            use_limit_up_universe=True,
            universe_from_local_db=True,
        )
    finally:
        db.close()

    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
