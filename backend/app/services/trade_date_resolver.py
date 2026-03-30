"""仪表盘默认交易日：最近已完成 A 股交易日（与 trading_session 一致，上海时区）。"""
from __future__ import annotations

from datetime import datetime, time

from app.services.trading_session import is_a_share_trading_session, shanghai_datetime
from app.services.tushare_adapter import TushareAdapter, tushare_adapter


class TradeDateResolutionError(Exception):
    """无法从交易日历解析出默认 trade_date。"""


def _last_open_before(cal_today: str, open_dates_sorted: list[str]) -> str | None:
    candidates = [d for d in open_dates_sorted if d < cal_today]
    return candidates[-1] if candidates else None


def resolve_dashboard_trade_date(
    now: datetime | None = None,
    adapter: TushareAdapter | None = None,
) -> str:
    """
    盘中：严格早于今日自然日的最近交易日。
    非盘中：若今日为交易日且已过 15:00（上海）则用今日；否则同上。
    """
    ad = adapter or tushare_adapter
    now_sh = shanghai_datetime(now)
    cal_today = now_sh.strftime("%Y%m%d")
    open_dates = ad.get_sse_open_dates(cal_today)
    open_set = set(open_dates)

    if is_a_share_trading_session(now_sh):
        td = _last_open_before(cal_today, open_dates)
    else:
        t = now_sh.time()
        if cal_today in open_set and t >= time(15, 0):
            td = cal_today
        else:
            td = _last_open_before(cal_today, open_dates)

    if not td:
        raise TradeDateResolutionError(f"无法解析默认交易日（cal_today={cal_today}）")
    return td


def last_n_resolved_trade_dates(
    n: int,
    adapter: TushareAdapter | None = None,
    lookback_calendar_days: int = 400,
) -> list[str]:
    """
    最近 n 个可用于日线的「已完成」交易日（升序），上限日为 resolve_dashboard_trade_date()。
    供涨停筛选等与仪表盘一致的默认日期窗口。
    """
    if n < 1:
        return []
    ad = adapter or tushare_adapter
    end = resolve_dashboard_trade_date(adapter=ad)
    open_dates = ad.get_sse_open_dates(end, lookback_calendar_days=lookback_calendar_days)
    if not open_dates:
        return []
    return open_dates[-n:] if len(open_dates) > n else open_dates


def resolve_dashboard_trade_date_with_calendar(
    now: datetime,
    open_dates_sorted: list[str],
) -> str:
    """测试用：注入已排序的开放日列表（YYYYMMDD）。"""
    now_sh = shanghai_datetime(now)
    cal_today = now_sh.strftime("%Y%m%d")
    open_set = set(open_dates_sorted)

    if is_a_share_trading_session(now_sh):
        td = _last_open_before(cal_today, open_dates_sorted)
    else:
        t = now_sh.time()
        if cal_today in open_set and t >= time(15, 0):
            td = cal_today
        else:
            td = _last_open_before(cal_today, open_dates_sorted)

    if not td:
        raise TradeDateResolutionError(f"无法解析默认交易日（cal_today={cal_today}）")
    return td
