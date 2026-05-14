"""
涨停回调买入策略：筛选涨停股加入观察池，打涨停日期标签。
不依赖本地全量同步，直接调用 AkShare 涨停池接口筛选涨停，再自动同步涨停股 60 日 K 线。
"""

from __future__ import annotations
import time
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy.orm import Session
from app.models.stock import DailyQuote, StockBasic
from app.models.pool import WatchPool, WatchStock
from app.models.monitor import MonitorRule
from app.services.tushare_adapter import AkshareAdapter

LIMIT_UP_POOL_NAME = "涨停股票观察池"
_AKSHARE_LIMIT_UP = AkshareAdapter()

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


def _load_limit_up_snapshot(trade_date: str) -> pd.DataFrame:
    """
    从 AkShare 加载指定交易日涨停池并标准化字段。
    返回列：ts_code, name, pct_chg
    """
    raw = _AKSHARE_LIMIT_UP._zt_pool_df(trade_date)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["ts_code", "name", "pct_chg"])
    out = pd.DataFrame()
    out["ts_code"] = raw.get("代码", "").astype(str).str.zfill(6).map(_AKSHARE_LIMIT_UP._to_ts_code)
    out["name"] = raw.get("名称", "").astype(str)
    out["pct_chg"] = pd.to_numeric(raw.get("涨跌幅"), errors="coerce")
    out = out[(out["ts_code"].notna()) & (out["ts_code"] != "")]
    return out.reset_index(drop=True)


def _get_trade_dates(days: int = 1) -> list[str]:
    """
    最近 N 个「已完成」交易日（与仪表盘默认日逻辑一致，SSE 日历）。
    盘后含当日；盘中为上一交易日。不再从「自然日昨天」起算（否则交易当天下午永远筛不到当天涨停）。
    """
    from app.services.trade_date_resolver import last_n_resolved_trade_dates

    try:
        return last_n_resolved_trade_dates(days)
    except Exception:
        # 日历失败时降级：从自然日昨天往前数工作日（旧逻辑，不含节假日）
        dates: list[str] = []
        d = datetime.now() - timedelta(days=1)
        for _ in range(400):
            if len(dates) >= days:
                break
            if d.weekday() < 5:
                dates.append(d.strftime("%Y%m%d"))
            d -= timedelta(days=1)
        return dates[:days]


def fetch_limit_up_stocks_in_range(
    db: Session,
    trade_date_from: str,
    trade_date_to: str,
    exclude_one_word_limit: bool = True,
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

    for trade_date in dates:
        time.sleep(0.2)
        try:
            df = _load_limit_up_snapshot(trade_date)
            if df.empty:
                continue
            for _, row in df.iterrows():
                ts_code = row.get("ts_code")
                if not ts_code:
                    continue
                if _is_stock_st(row.get("name")):
                    continue
                # AkShare 涨停池不稳定提供 high/low，无法准确排除一字板；此处仅按涨停池口径。
                existing = result.get(ts_code)
                if not existing or trade_date > existing:
                    result[ts_code] = trade_date
        except Exception:
            pass
    return result


def fetch_limit_up_stocks_from_db(
    db: Session,
    trade_date_from: str,
    trade_date_to: str,
    exclude_one_word_limit: bool = True,
) -> dict[str, str]:
    """
    从本地 daily_quote 筛涨停股（不访问外网），供回测构造 universe。
    返回 ts_code -> 区间内最近一次涨停日（与 fetch_limit_up_stocks_in_range 一致）。
    """
    result: dict[str, str] = {}
    if trade_date_from > trade_date_to:
        return result

    dqs = (
        db.query(DailyQuote)
        .filter(
            DailyQuote.trade_date >= trade_date_from,
            DailyQuote.trade_date <= trade_date_to,
        )
        .all()
    )
    if not dqs:
        return result

    codes = list({d.ts_code for d in dqs})
    basics = {
        b.ts_code: b
        for b in db.query(StockBasic).filter(StockBasic.ts_code.in_(codes)).all()
    }

    for dq in dqs:
        basic = basics.get(dq.ts_code)
        if _is_stock_st(basic.name if basic else None):
            continue
        threshold = _get_limit_up_threshold(basic.market if basic else None)
        pct = dq.pct_chg
        if pct is None or pd.isna(pct) or float(pct) < threshold:
            continue
        if exclude_one_word_limit:
            h, low = dq.high, dq.low
            if h is not None and low is not None and float(h) == float(low):
                continue
        ts_code = dq.ts_code
        td = dq.trade_date
        prev = result.get(ts_code)
        if not prev or td > prev:
            result[ts_code] = td
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
    exclude_one_word_limit: bool = True,
) -> dict:
    """
    按指定交易日筛选涨停股，加入/更新到指定池。
    直接从 AkShare 涨停池获取该日涨停股，不依赖本地 DailyQuote。
    返回 {"added": int, "updated": int, "skipped": int, "errors": list, "added_codes": list}
    """
    result = {"added": 0, "updated": 0, "skipped": 0, "errors": [], "added_codes": []}

    time.sleep(0.2)  # 限流：避免接口频率超限
    try:
        df = _load_limit_up_snapshot(trade_date)
    except Exception as e:
        result["errors"].append(f"{trade_date}: 拉取 AkShare 涨停池失败: {e}")
        db.commit()
        return result
    if df.empty:
        result["errors"].append(f"{trade_date}: AkShare 涨停池无数据")
        db.commit()
        return result

    for _, row in df.iterrows():
        ts_code = row.get("ts_code")
        if not ts_code:
            continue

        try:
            basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
            if _is_stock_st(row.get("name")) or _is_stock_st(basic.name if basic else None):
                result["skipped"] += 1
                continue

            # AkShare 涨停池接口不稳定提供 high/low 字段，无法准确判断一字板，默认不过滤。
            _ = exclude_one_word_limit

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
