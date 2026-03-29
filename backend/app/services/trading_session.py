"""A 股初版交易时段（上海时区）：工作日 9:30–11:30、13:00–15:00，不含节假日剔除。"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

_SH = ZoneInfo("Asia/Shanghai")


def _to_shanghai(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(_SH)
    if now.tzinfo is None:
        return now.replace(tzinfo=_SH)
    return now.astimezone(_SH)


def is_a_share_trading_session(now: datetime | None = None) -> bool:
    dt = _to_shanghai(now)
    if dt.weekday() >= 5:
        return False
    t = dt.time()
    morning = time(9, 30) <= t <= time(11, 30)
    afternoon = time(13, 0) <= t <= time(15, 0)
    return morning or afternoon


def shanghai_trade_date_str(now: datetime | None = None) -> str:
    """自然日 YYYYMMDD（上海），用于与 DB 最后一根 K 的 trade_date 比较。"""
    return _to_shanghai(now).strftime("%Y%m%d")


def shanghai_datetime(now: datetime | None = None) -> datetime:
    """当前或给定时刻的上海时区 datetime。"""
    return _to_shanghai(now)
