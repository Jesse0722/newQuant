from __future__ import annotations

import json
import time
from datetime import datetime

from app.services.tushare_adapter import AkshareAdapter


def _assert_non_empty(name: str, ok: bool, detail: str = ""):
    if not ok:
        raise RuntimeError(f"{name} 失败: {detail}")


def _retry(name: str, fn, retries: int = 3, sleep_s: float = 2.0):
    last = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(sleep_s * (i + 1))
    raise RuntimeError(f"{name} 重试{retries}次后失败: {last}")


def run() -> dict:
    ad = AkshareAdapter()
    today = datetime.now().strftime("%Y%m%d")
    open_dates = _retry("交易日历", lambda: ad.get_sse_open_dates(today))
    last_trade_date = open_dates[-1] if open_dates else today
    report: dict[str, dict] = {}

    # 1) 全量市场 K 线（当日快照口径）
    daily_all = _retry("全量市场K线", lambda: ad.get_daily_by_date(today))
    report["full_market_kline"] = {
        "trade_date": today,
        "rows": int(len(daily_all)),
        "columns": list(daily_all.columns),
    }
    _assert_non_empty("全量市场K线", len(daily_all) > 1000, f"rows={len(daily_all)}")

    # 2) 指定日期涨停板
    limit_step = _retry("指定日期涨停板", lambda: ad.get_limit_step(last_trade_date))
    report["limit_up_by_date"] = {
        "trade_date": last_trade_date,
        "rows": int(len(limit_step)),
        "columns": list(limit_step.columns),
    }
    _assert_non_empty("指定日期涨停板", len(limit_step) > 0, f"trade_date={last_trade_date}")

    # 3) 股票基础 + 个股 K 线
    basic_all = _retry("股票基础数据", lambda: ad.get_stock_basic())
    _assert_non_empty("股票基础数据", len(basic_all) > 1000, f"rows={len(basic_all)}")
    ts_code = str(basic_all.iloc[0]["ts_code"])
    daily_one = _retry("个股K线数据", lambda: ad.get_daily(ts_code, start_date="20260101", end_date=today))
    daily_basic_one = _retry("个股基本日线数据", lambda: ad.get_daily_basic(ts_code, start_date="20260101", end_date=today))
    report["single_stock"] = {
        "ts_code": ts_code,
        "stock_basic_rows": int(len(basic_all)),
        "daily_rows": int(len(daily_one)),
        "daily_basic_rows": int(len(daily_basic_one)),
    }
    _assert_non_empty("个股K线数据", len(daily_one) > 0, f"ts_code={ts_code}")

    # 4) 其他 AkShare 接口（交易日历/实时K/题材板块）
    rt_df = _retry("实时K", lambda: ad.get_rt_k(",".join(basic_all.head(5)["ts_code"].tolist())))
    cpt = _retry("涨停板块统计", lambda: ad.get_limit_cpt_list(last_trade_date))
    report["other_interfaces"] = {
        "open_dates_count": int(len(open_dates)),
        "rt_k_rows": int(len(rt_df)),
        "limit_cpt_rows": int(len(cpt)),
    }
    _assert_non_empty("交易日历", len(open_dates) > 0)
    _assert_non_empty("实时K", len(rt_df) > 0)

    # 接口覆盖率（按 AkshareAdapter 公开接口）
    interfaces = [
        "get_stock_basic",
        "get_daily",
        "get_daily_basic",
        "get_daily_by_date",
        "get_rt_k",
        "get_sse_open_dates",
        "get_limit_cpt_list",
        "get_limit_step",
    ]
    report["coverage"] = {
        "covered": interfaces,
        "coverage_pct": 100,
    }
    return report


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, ensure_ascii=False, indent=2))
