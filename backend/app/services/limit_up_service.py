"""
涨停回调买入策略：筛选涨停股加入观察池，打涨停日期标签。
不依赖本地全量同步，直接调用 Tushare API 获取日线筛选涨停，再自动同步涨停股 60 日 K 线。
"""
import time
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy.orm import Session
from app.models.stock import StockBasic
from app.models.pool import WatchPool, WatchStock
from app.models.monitor import MonitorRule
from app.services.tushare_adapter import tushare_adapter

LIMIT_UP_POOL_NAME = "涨停股票观察池"

# 涨停阈值：market -> pct_chg 下限
LIMIT_UP_THRESHOLD = {
    "主板": 9.9,
    "中小板": 9.9,
    "创业板": 19.9,
    "科创板": 19.9,
    "北交所": 29.9,
}


def _get_limit_up_threshold(market: str | None) -> float:
    """根据 market 返回涨停阈值"""
    if not market:
        return 9.9
    for k, v in LIMIT_UP_THRESHOLD.items():
        if k in (market or ""):
            return v
    return 9.9


def _is_stock_st(name: str | None) -> bool:
    """判断是否为 ST 股票"""
    return bool(name and ("ST" in name.upper()))


def _get_trade_dates(days: int = 1) -> list[str]:
    """获取最近 N 个交易日（从昨天开始）"""
    dates = []
    d = datetime.now() - timedelta(days=1)
    while len(dates) < days:
        s = d.strftime("%Y%m%d")
        if d.weekday() < 5:
            dates.append(s)
        d -= timedelta(days=1)
    return dates


def fetch_limit_up_stocks_in_range(
    db: Session,
    trade_date_from: str,
    trade_date_to: str,
) -> dict[str, str]:
    """
    按日期范围拉取涨停股，不写入数据库。
    返回 ts_code -> limit_up_date（同一股票取最近涨停日）
    """
    result: dict[str, str] = {}
    if trade_date_from > trade_date_to:
        return result

    current = datetime.strptime(trade_date_from, "%Y%m%d")
    end = datetime.strptime(trade_date_to, "%Y%m%d")
    dates: list[str] = []
    while current <= end:
        s = current.strftime("%Y%m%d")
        if current.weekday() < 5:
            dates.append(s)
        current += timedelta(days=1)

    basic_map: dict[str, StockBasic | None] = {}
    for trade_date in dates:
        time.sleep(0.2)
        try:
            df = tushare_adapter.get_daily_by_date(trade_date)
            if df.empty:
                continue
            for _, row in df.iterrows():
                ts_code = row.get("ts_code")
                if not ts_code:
                    continue
                if ts_code not in basic_map:
                    basic_map[ts_code] = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
                basic = basic_map[ts_code]
                if _is_stock_st(basic.name if basic else None):
                    continue
                threshold = _get_limit_up_threshold(basic.market if basic else None)
                pct = row.get("pct_chg")
                if pct is None or pd.isna(pct) or pct < threshold:
                    continue
                # 排除一字板（开盘价=收盘价=最高价=最低价）
                high, low = row.get("high"), row.get("low")
                if high is not None and low is not None and high == low:
                    continue
                existing = result.get(ts_code)
                if not existing or trade_date > existing:
                    result[ts_code] = trade_date
        except Exception:
            pass
    return result


def get_or_create_limit_up_pool(db: Session) -> WatchPool:
    """获取或创建「涨停股票观察池」"""
    pool = db.query(WatchPool).filter(WatchPool.name == LIMIT_UP_POOL_NAME).first()
    if pool:
        return pool
    max_order = db.query(WatchPool.sort_order).order_by(WatchPool.sort_order.desc()).first()
    sort_order = (max_order[0] + 1) if max_order and max_order[0] is not None else 0
    pool = WatchPool(
        name=LIMIT_UP_POOL_NAME,
        description="涨停回调买入策略：近期涨停股，监控回踩 MA10 买点",
        sort_order=sort_order,
    )
    db.add(pool)
    db.flush()
    rule = MonitorRule(
        pool_id=pool.id,
        template_id="ma_support",
        params={"n": 10},
        is_active=True,
    )
    db.add(rule)
    db.commit()
    db.refresh(pool)
    return pool


def collect_limit_up_stocks(
    db: Session,
    trade_date: str,
    pool_id: str,
) -> dict:
    """
    按指定交易日筛选涨停股，加入/更新到指定池。
    直接从 Tushare API 获取该日全市场日线，不依赖本地 DailyQuote。
    返回 {"added": int, "updated": int, "skipped": int, "errors": list, "added_codes": list}
    """
    result = {"added": 0, "updated": 0, "skipped": 0, "errors": [], "added_codes": []}

    time.sleep(0.2)  # 限流：避免 Tushare 接口频率超限
    df = tushare_adapter.get_daily_by_date(trade_date)
    if df.empty:
        db.commit()
        return result

    basic_map = {}
    for _, row in df.iterrows():
        ts_code = row.get("ts_code")
        if not ts_code:
            continue
        if ts_code not in basic_map:
            basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
            basic_map[ts_code] = basic

        try:
            basic = basic_map[ts_code]
            if _is_stock_st(basic.name if basic else None):
                result["skipped"] += 1
                continue

            threshold = _get_limit_up_threshold(basic.market if basic else None)
            pct = row.get("pct_chg")
            if pct is None or pd.isna(pct) or pct < threshold:
                continue

            # 排除一字板
            high, low = row.get("high"), row.get("low")
            if high is not None and low is not None and high == low:
                result["skipped"] += 1
                continue

            existing = (
                db.query(WatchStock)
                .filter(
                    WatchStock.pool_id == pool_id,
                    WatchStock.ts_code == ts_code,
                )
                .first()
            )

            if existing:
                existing.limit_up_date = trade_date
                result["updated"] += 1
            else:
                stock = WatchStock(
                    pool_id=pool_id,
                    ts_code=ts_code,
                    source="limit_up",
                    limit_up_date=trade_date,
                )
                db.add(stock)
                result["added"] += 1
                result["added_codes"].append(ts_code)
        except Exception as e:
            result["errors"].append(f"{ts_code}: {e}")

    db.commit()
    return result
