"""
涨停回调买入策略：筛选涨停股加入观察池，打涨停日期标签。
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchPool, WatchStock
from app.models.monitor import MonitorRule

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
    返回 {"added": int, "updated": int, "skipped": int, "errors": list, "added_codes": list}
    """
    result = {"added": 0, "updated": 0, "skipped": 0, "errors": [], "added_codes": []}

    # 获取该日全市场日线（左连接 stock_basic，无基础信息时用默认阈值）
    rows = (
        db.query(DailyQuote, StockBasic)
        .outerjoin(StockBasic, DailyQuote.ts_code == StockBasic.ts_code)
        .filter(DailyQuote.trade_date == trade_date)
        .all()
    )

    for dq, basic in rows:
        try:
            if _is_stock_st(basic.name if basic else None):
                result["skipped"] += 1
                continue

            threshold = _get_limit_up_threshold(basic.market if basic else None)
            pct = dq.pct_chg if dq.pct_chg is not None else 0
            if pct < threshold:
                continue

            existing = (
                db.query(WatchStock)
                .filter(
                    WatchStock.pool_id == pool_id,
                    WatchStock.ts_code == dq.ts_code,
                )
                .first()
            )

            if existing:
                existing.limit_up_date = trade_date
                result["updated"] += 1
            else:
                stock = WatchStock(
                    pool_id=pool_id,
                    ts_code=dq.ts_code,
                    source="limit_up",
                    limit_up_date=trade_date,
                )
                db.add(stock)
                result["added"] += 1
                result["added_codes"].append(dq.ts_code)
        except Exception as e:
            result["errors"].append(f"{dq.ts_code}: {e}")

    db.commit()
    return result
