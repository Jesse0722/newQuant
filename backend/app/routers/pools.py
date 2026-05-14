from __future__ import annotations

import csv
import io
from urllib.parse import quote
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Query, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.pool import WatchPool, WatchStock
from app.models.stock import StockBasic, DailyQuote
from app.schemas.pool import (
    PoolCreate, PoolUpdate, PoolOut,
    WatchStockCreate, WatchStockUpdate, WatchStockOut, WatchStockPagination,
    CSVImportResult, BatchAddStocks, BatchAddResult, QuickCreatePool,
    CoreWatchCodesOut, CoreWatchToggleBody, CoreWatchToggleOut,
)
from app.services.core_watch_service import list_core_watch_ts_codes, toggle_core_watch_star
from app.services.limit_up_service import _get_limit_up_threshold
from app.exceptions import AppError
from app.utils import normalize_ts_code
from app.services.sync_service import sync_single_stock
from app.tasks.background import submit_task

router = APIRouter(prefix="/api/pools", tags=["pools"])


def _batch_latest_quotes(db: Session, ts_codes: list[str]) -> dict[str, DailyQuote]:
    if not ts_codes:
        return {}
    subq = (
        db.query(DailyQuote.ts_code, func.max(DailyQuote.trade_date).label("md"))
        .filter(DailyQuote.ts_code.in_(ts_codes))
        .group_by(DailyQuote.ts_code)
        .subquery()
    )
    rows = (
        db.query(DailyQuote)
        .join(subq, (DailyQuote.ts_code == subq.c.ts_code) & (DailyQuote.trade_date == subq.c.md))
        .all()
    )
    return {r.ts_code: r for r in rows}


def _batch_stock_basics(db: Session, ts_codes: list[str]) -> dict[str, StockBasic]:
    if not ts_codes:
        return {}
    rows = db.query(StockBasic).filter(StockBasic.ts_code.in_(ts_codes)).all()
    return {r.ts_code: r for r in rows}


def _est_circ_mv_yi(close: float | None, float_share_wan: float | None) -> float | None:
    """
    估算流通市值（亿元）：daily_basic 口径下 float_share 为万股，
    流通市值约 close(元) * float_share(万股) 万元，再 /10000 得亿元。
    """
    if close is None or float_share_wan is None:
        return None
    try:
        c = float(close)
        fs = float(float_share_wan)
        if c <= 0 or fs <= 0:
            return None
        return c * fs / 10000.0
    except (TypeError, ValueError):
        return None


def _batch_limit_up_counts(
    db: Session,
    ts_codes: list[str],
    d_from: str,
    d_to: str,
    basics: dict[str, StockBasic],
) -> dict[str, int]:
    if not ts_codes or d_from > d_to:
        return {c: 0 for c in ts_codes}
    rows = (
        db.query(DailyQuote.ts_code, DailyQuote.pct_chg)
        .filter(
            DailyQuote.ts_code.in_(ts_codes),
            DailyQuote.trade_date >= d_from,
            DailyQuote.trade_date <= d_to,
        )
        .all()
    )
    by_code: dict[str, list[float]] = {}
    for ts, pct in rows:
        if pct is None:
            continue
        try:
            p = float(pct)
        except (TypeError, ValueError):
            continue
        by_code.setdefault(ts, []).append(p)
    out: dict[str, int] = {}
    for ts in ts_codes:
        th = _get_limit_up_threshold(basics.get(ts).market if basics.get(ts) else None)
        out[ts] = sum(1 for p in by_code.get(ts, []) if p >= th)
    return out


def _batch_rising_trend_flags(db: Session, ts_codes: list[str]) -> dict[str, bool]:
    """
    计算“上升趋势”标记（近似口径）：
    latest_close > MA5 > MA10 > MA20 且 MA5(今日) >= MA5(昨日)。
    """
    if not ts_codes:
        return {}
    rows = (
        db.query(DailyQuote.ts_code, DailyQuote.trade_date, DailyQuote.close)
        .filter(DailyQuote.ts_code.in_(ts_codes))
        .order_by(DailyQuote.ts_code.asc(), DailyQuote.trade_date.desc())
        .all()
    )
    by_code: dict[str, list[float]] = {}
    for ts_code, _, close in rows:
        if close is None:
            continue
        seq = by_code.setdefault(ts_code, [])
        if len(seq) >= 25:
            continue
        try:
            seq.append(float(close))
        except (TypeError, ValueError):
            continue

    flags: dict[str, bool] = {}
    for ts_code in ts_codes:
        closes = by_code.get(ts_code, [])
        if len(closes) < 21:
            flags[ts_code] = False
            continue
        latest_close = closes[0]
        ma5 = sum(closes[0:5]) / 5.0
        ma10 = sum(closes[0:10]) / 10.0
        ma20 = sum(closes[0:20]) / 20.0
        ma5_prev = sum(closes[1:6]) / 5.0
        flags[ts_code] = (
            latest_close > ma5 > ma10 > ma20
            and ma5 >= ma5_prev
        )
    return flags


def _enrich_stock(
    db: Session,
    stock: WatchStock,
) -> WatchStockOut:
    basic = db.query(StockBasic).filter(StockBasic.ts_code == stock.ts_code).first()
    latest = db.query(DailyQuote).filter(
        DailyQuote.ts_code == stock.ts_code
    ).order_by(DailyQuote.trade_date.desc()).first()
    out = WatchStockOut.model_validate(stock)
    out.stock_name = basic.name if basic else None
    out.industry = basic.industry if basic else None
    if latest:
        out.latest_price = latest.close
        out.pct_chg = latest.pct_chg
        out.trade_date = latest.trade_date
    return out


def _calc_limit_up_streak_and_5d_pct(db: Session, ts_code: str) -> tuple[int, float | None]:
    """返回 (连板数, 5日涨幅%)。连板数按最新开始连续涨停日近似统计。"""
    quotes = (
        db.query(DailyQuote)
        .filter(DailyQuote.ts_code == ts_code)
        .order_by(DailyQuote.trade_date.desc())
        .limit(30)
        .all()
    )
    if not quotes:
        return 0, None

    streak = 0
    for q in quotes:
        pct = q.pct_chg
        if pct is None:
            break
        # 主板/创业板/科创板涨停幅度不同，这里取兼容阈值，作为列表展示近似口径
        if float(pct) >= 9.5:
            streak += 1
        else:
            break

    five_day_pct = None
    if len(quotes) >= 5:
        latest_close = quotes[0].close
        close_5d_ago = quotes[4].close
        if latest_close is not None and close_5d_ago not in (None, 0):
            five_day_pct = (float(latest_close) / float(close_5d_ago) - 1.0) * 100.0
    return streak, five_day_pct


def _normalize_pct_for_export(db: Session, ts_code: str, pct_chg: float | None) -> float | None:
    """导出展示口径：接近涨停幅度时，规范显示为 10/20/30%。"""
    if pct_chg is None:
        return None
    basic = db.query(StockBasic.market).filter(StockBasic.ts_code == ts_code).first()
    market = (basic[0] if basic and basic[0] else "") or ""
    limit_pct = 10.0
    if "创业" in market or "科创" in market:
        limit_pct = 20.0
    elif "北交" in market:
        limit_pct = 30.0
    if abs(float(pct_chg) - limit_pct) <= 0.02:
        return limit_pct
    return float(pct_chg)


def _passes_pool_advanced_filters(
    latest: DailyQuote | None,
    basic: StockBasic | None,
    limit_up_hits: int,
    *,
    price_min: float | None,
    price_max: float | None,
    circ_mv_min: float | None,
    circ_mv_max: float | None,
    limit_up_count_min: int | None,
    limit_up_count_max: int | None,
    need_limit_up_stats: bool,
    rising_trend_only: bool,
    rising_trend_ok: bool,
) -> bool:
    close = float(latest.close) if latest and latest.close is not None else None
    if price_min is not None:
        if close is None or close < price_min:
            return False
    if price_max is not None:
        if close is None or close > price_max:
            return False

    fs = None
    if latest and latest.float_share is not None:
        fs = float(latest.float_share)
    elif basic and basic.float_share is not None:
        fs = float(basic.float_share)
    mv_yi = _est_circ_mv_yi(close if latest else None, fs)

    if circ_mv_min is not None:
        if mv_yi is None or mv_yi < circ_mv_min:
            return False
    if circ_mv_max is not None:
        if mv_yi is None or mv_yi > circ_mv_max:
            return False

    if need_limit_up_stats:
        if limit_up_count_min is not None and limit_up_hits < limit_up_count_min:
            return False
        if limit_up_count_max is not None and limit_up_hits > limit_up_count_max:
            return False
    if rising_trend_only and not rising_trend_ok:
        return False
    return True


@router.get("", response_model=list[PoolOut])
def list_pools(db: Session = Depends(get_db)):
    pools = db.query(WatchPool).order_by(WatchPool.sort_order.asc(), WatchPool.created_at.desc()).all()
    result = []
    for p in pools:
        count = db.query(func.count(WatchStock.id)).filter(WatchStock.pool_id == p.id).scalar()
        out = PoolOut.model_validate(p)
        out.stock_count = count
        result.append(out)
    return result


@router.get("/all-stocks")
def list_all_stocks(
    keyword: str = Query(None),
    db: Session = Depends(get_db),
):
    """所有观察池股票（扁平列表），支持 keyword 按名称/代码模糊搜索"""
    q = db.query(WatchStock, WatchPool).join(WatchPool, WatchStock.pool_id == WatchPool.id)
    rows = q.order_by(WatchPool.name, WatchStock.ts_code).all()
    result = []
    for ws, pool in rows:
        basic = db.query(StockBasic).filter(StockBasic.ts_code == ws.ts_code).first()
        stock_name = basic.name if basic else None
        if keyword:
            kw = keyword.lower()
            if kw not in (ws.ts_code or "").lower() and kw not in (stock_name or "").lower():
                continue
        result.append({
            "ts_code": ws.ts_code,
            "stock_name": stock_name,
            "pool_id": pool.id,
            "pool_name": pool.name,
        })
    return result


@router.put("/reorder")
def reorder_pools(body: dict = Body(...), db: Session = Depends(get_db)):
    """拖拽排序：body 为 { "pool_ids": ["id1", "id2", ...] }"""
    pool_ids = body.get("pool_ids") or []
    if not pool_ids:
        return {"ok": True}
    for i, pid in enumerate(pool_ids):
        pool = db.query(WatchPool).filter(WatchPool.id == pid).first()
        if pool:
            pool.sort_order = i
    db.commit()
    return {"ok": True}


@router.get("/core-watch/codes", response_model=CoreWatchCodesOut)
def get_core_watch_codes(db: Session = Depends(get_db)):
    """买点雷达：获取「核心关注」池内股票代码（池不存在则 pool_id 为空）"""
    pool_id, ts_codes = list_core_watch_ts_codes(db)
    return CoreWatchCodesOut(pool_id=pool_id, ts_codes=ts_codes)


@router.post("/core-watch/toggle", response_model=CoreWatchToggleOut)
def core_watch_toggle(body: CoreWatchToggleBody, db: Session = Depends(get_db)):
    """加星加入「核心关注」池 / 取消星标移除（买点雷达与股票详情等共用）"""
    try:
        result = toggle_core_watch_star(
            db,
            body.ts_code,
            body.starred,
            limit_up_date=body.limit_up_date,
            source=(body.source or "buy_radar"),
        )
        return CoreWatchToggleOut(**result)
    except ValueError as e:
        raise AppError(code=2003, message=str(e))


@router.post("", response_model=PoolOut, status_code=201)
def create_pool(body: PoolCreate, db: Session = Depends(get_db)):
    max_order = db.query(func.max(WatchPool.sort_order)).scalar() or -1
    pool = WatchPool(**body.model_dump(), sort_order=max_order + 1)
    db.add(pool)
    db.commit()
    db.refresh(pool)
    out = PoolOut.model_validate(pool)
    out.stock_count = 0
    return out


@router.post("/quick-create", response_model=PoolOut, status_code=201)
def quick_create_pool(body: QuickCreatePool, db: Session = Depends(get_db)):
    """快捷创建观察池并批量添加股票"""
    max_order = db.query(func.max(WatchPool.sort_order)).scalar() or -1
    pool = WatchPool(name=body.name, description=body.description, sort_order=max_order + 1)
    db.add(pool)
    db.commit()
    db.refresh(pool)
    added = 0
    for ts_code in body.ts_codes:
        try:
            code = normalize_ts_code(ts_code)
        except ValueError:
            continue
        existing = db.query(WatchStock).filter(
            WatchStock.pool_id == pool.id, WatchStock.ts_code == code
        ).first()
        if existing:
            continue
        stock = WatchStock(pool_id=pool.id, ts_code=code, source="strategy")
        db.add(stock)
        added += 1
    db.commit()
    for ws in db.query(WatchStock).filter(WatchStock.pool_id == pool.id).all():
        submit_task("sync", sync_single_stock, ws.ts_code)
    count = db.query(func.count(WatchStock.id)).filter(WatchStock.pool_id == pool.id).scalar()
    out = PoolOut.model_validate(pool)
    out.stock_count = count
    return out


@router.get("/{pool_id}", response_model=PoolOut)
def get_pool(pool_id: str, db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    count = db.query(func.count(WatchStock.id)).filter(WatchStock.pool_id == pool.id).scalar()
    out = PoolOut.model_validate(pool)
    out.stock_count = count
    return out


@router.put("/{pool_id}", response_model=PoolOut)
def update_pool(pool_id: str, body: PoolUpdate, db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(pool, k, v)
    db.commit()
    db.refresh(pool)
    count = db.query(func.count(WatchStock.id)).filter(WatchStock.pool_id == pool.id).scalar()
    out = PoolOut.model_validate(pool)
    out.stock_count = count
    return out


@router.delete("/{pool_id}", status_code=204)
def delete_pool(pool_id: str, db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    db.delete(pool)
    db.commit()


@router.get("/{pool_id}/stocks", response_model=WatchStockPagination)
def list_stocks(
    pool_id: str,
    keyword: str = Query(None),
    monitor_status: str = Query(None),
    limit_up_date_from: str = Query(None, description="涨停日期起 YYYYMMDD"),
    limit_up_date_to: str = Query(None, description="涨停日期止 YYYYMMDD"),
    price_min: Optional[float] = Query(None, description="最新收盘价下限"),
    price_max: Optional[float] = Query(None, description="最新收盘价上限"),
    circ_mv_min: Optional[float] = Query(None, description="估算流通市值下限（亿元，收盘价×流通股本）"),
    circ_mv_max: Optional[float] = Query(None, description="估算流通市值上限（亿元）"),
    limit_up_stats_from: Optional[str] = Query(None, description="统计涨停次数：起始日 YYYYMMDD"),
    limit_up_stats_to: Optional[str] = Query(None, description="统计涨停次数：截止日 YYYYMMDD"),
    limit_up_count_min: Optional[int] = Query(None, ge=0, description="区间内涨停次数下限"),
    limit_up_count_max: Optional[int] = Query(None, ge=0, description="区间内涨停次数上限"),
    rising_trend: bool = Query(False, description="仅保留上升趋势（close>MA5>MA10>MA20 且 MA5 不下拐）"),
    sort_by: str = Query("created_at", description="排序字段: created_at | limit_up_date"),
    order: str = Query("desc", description="排序方向: asc | desc"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    if (limit_up_count_min is not None or limit_up_count_max is not None) and (
        not limit_up_stats_from or not limit_up_stats_to
    ):
        raise AppError(
            code=2003,
            message="筛选涨停次数时需同时传入 limit_up_stats_from 与 limit_up_stats_to",
            status_code=400,
        )
    if limit_up_stats_from and limit_up_stats_to and limit_up_stats_from > limit_up_stats_to:
        raise AppError(code=2003, message="涨停统计起止日期顺序无效", status_code=400)
    q = db.query(WatchStock).filter(WatchStock.pool_id == pool_id)
    if monitor_status:
        q = q.filter(WatchStock.monitor_status == monitor_status)
    if limit_up_date_from:
        q = q.filter(WatchStock.limit_up_date >= limit_up_date_from)
    if limit_up_date_to:
        q = q.filter(WatchStock.limit_up_date <= limit_up_date_to)
    stocks = q.all()
    ts_codes = list({s.ts_code for s in stocks})
    latest_map = _batch_latest_quotes(db, ts_codes)
    basic_map = _batch_stock_basics(db, ts_codes)
    luc_map: dict[str, int] = {}
    trend_map: dict[str, bool] = {}
    need_luc = limit_up_stats_from and limit_up_stats_to and (
        limit_up_count_min is not None or limit_up_count_max is not None
    )
    if need_luc:
        luc_map = _batch_limit_up_counts(db, ts_codes, limit_up_stats_from, limit_up_stats_to, basic_map)
    if rising_trend:
        trend_map = _batch_rising_trend_flags(db, ts_codes)
    result = []
    for s in stocks:
        out = _enrich_stock(db, s)
        if keyword and keyword.lower() not in (s.ts_code + (out.stock_name or "")).lower():
            continue
        if not _passes_pool_advanced_filters(
            latest_map.get(s.ts_code),
            basic_map.get(s.ts_code),
            luc_map.get(s.ts_code, 0),
            price_min=price_min,
            price_max=price_max,
            circ_mv_min=circ_mv_min,
            circ_mv_max=circ_mv_max,
            limit_up_count_min=limit_up_count_min,
            limit_up_count_max=limit_up_count_max,
            need_limit_up_stats=bool(need_luc),
            rising_trend_only=rising_trend,
            rising_trend_ok=trend_map.get(s.ts_code, False),
        ):
            continue
        result.append(out)
    # 排序：置顶优先，再按指定字段
    rev = order == "desc"
    null_val = "00000000" if rev else "99999999"
    if sort_by == "limit_up_date":
        result.sort(key=lambda x: (x.limit_up_date or null_val), reverse=rev)
    else:
        result.sort(key=lambda x: str(x.created_at or ""), reverse=rev)
    result.sort(key=lambda x: x.pinned, reverse=True)  # 置顶优先，稳定排序
    total = len(result)
    offset = (page - 1) * size
    items = result[offset : offset + size]
    return WatchStockPagination(items=items, total=total)


@router.get("/{pool_id}/stocks/export")
def export_stocks_csv(
    pool_id: str,
    keyword: str = Query(None),
    monitor_status: str = Query(None),
    limit_up_date_from: str = Query(None, description="涨停日期起 YYYYMMDD"),
    limit_up_date_to: str = Query(None, description="涨停日期止 YYYYMMDD"),
    price_min: Optional[float] = Query(None),
    price_max: Optional[float] = Query(None),
    circ_mv_min: Optional[float] = Query(None),
    circ_mv_max: Optional[float] = Query(None),
    limit_up_stats_from: Optional[str] = Query(None),
    limit_up_stats_to: Optional[str] = Query(None),
    limit_up_count_min: Optional[int] = Query(None, ge=0),
    limit_up_count_max: Optional[int] = Query(None, ge=0),
    rising_trend: bool = Query(False),
    sort_by: str = Query("created_at", description="排序字段: created_at | limit_up_date"),
    order: str = Query("desc", description="排序方向: asc | desc"),
    db: Session = Depends(get_db),
):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    if (limit_up_count_min is not None or limit_up_count_max is not None) and (
        not limit_up_stats_from or not limit_up_stats_to
    ):
        raise AppError(
            code=2003,
            message="筛选涨停次数时需同时传入 limit_up_stats_from 与 limit_up_stats_to",
            status_code=400,
        )
    if limit_up_stats_from and limit_up_stats_to and limit_up_stats_from > limit_up_stats_to:
        raise AppError(code=2003, message="涨停统计起止日期顺序无效", status_code=400)

    q = db.query(WatchStock).filter(WatchStock.pool_id == pool_id)
    if monitor_status:
        q = q.filter(WatchStock.monitor_status == monitor_status)
    if limit_up_date_from:
        q = q.filter(WatchStock.limit_up_date >= limit_up_date_from)
    if limit_up_date_to:
        q = q.filter(WatchStock.limit_up_date <= limit_up_date_to)
    stocks = q.all()

    ts_codes = list({s.ts_code for s in stocks})
    latest_map = _batch_latest_quotes(db, ts_codes)
    basic_map = _batch_stock_basics(db, ts_codes)
    need_luc = limit_up_stats_from and limit_up_stats_to and (
        limit_up_count_min is not None or limit_up_count_max is not None
    )
    luc_map = (
        _batch_limit_up_counts(db, ts_codes, limit_up_stats_from, limit_up_stats_to, basic_map)
        if need_luc
        else {}
    )
    trend_map = _batch_rising_trend_flags(db, ts_codes) if rising_trend else {}

    result = []
    for s in stocks:
        out = _enrich_stock(db, s)
        if keyword and keyword.lower() not in (s.ts_code + (out.stock_name or "")).lower():
            continue
        if not _passes_pool_advanced_filters(
            latest_map.get(s.ts_code),
            basic_map.get(s.ts_code),
            luc_map.get(s.ts_code, 0),
            price_min=price_min,
            price_max=price_max,
            circ_mv_min=circ_mv_min,
            circ_mv_max=circ_mv_max,
            limit_up_count_min=limit_up_count_min,
            limit_up_count_max=limit_up_count_max,
            need_limit_up_stats=bool(need_luc),
            rising_trend_only=rising_trend,
            rising_trend_ok=trend_map.get(s.ts_code, False),
        ):
            continue
        result.append(out)

    rev = order == "desc"
    null_val = "00000000" if rev else "99999999"
    if sort_by == "limit_up_date":
        result.sort(key=lambda x: (x.limit_up_date or null_val), reverse=rev)
    else:
        result.sort(key=lambda x: str(x.created_at or ""), reverse=rev)
    result.sort(key=lambda x: x.pinned, reverse=True)

    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["股票名称", "股票代码", "所属行业", "当前股价", "当日涨幅", "连板数", "5日涨幅"])
    for item in result:
        lb, pct_5d = _calc_limit_up_streak_and_5d_pct(db, item.ts_code)
        pct_display = _normalize_pct_for_export(db, item.ts_code, item.pct_chg)
        writer.writerow([
            item.stock_name or "",
            item.ts_code,
            item.industry or "",
            f"{item.latest_price:.2f}" if item.latest_price is not None else "",
            f"{pct_display:.2f}%" if pct_display is not None else "",
            lb,
            f"{pct_5d:.2f}%" if pct_5d is not None else "",
        ])

    csv_text = "\ufeff" + stream.getvalue()
    filename = f"{pool.name}_stocks.csv"
    filename_star = quote(filename)
    return StreamingResponse(
        io.BytesIO(csv_text.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=stocks.csv; filename*=UTF-8''{filename_star}",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.post("/{pool_id}/stocks", response_model=WatchStockOut, status_code=201)
def add_stock(pool_id: str, body: WatchStockCreate, db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    try:
        ts_code = normalize_ts_code(body.ts_code)
    except ValueError as e:
        raise AppError(code=2003, message=str(e))
    existing = db.query(WatchStock).filter(
        WatchStock.pool_id == pool_id, WatchStock.ts_code == ts_code
    ).first()
    if existing:
        raise AppError(code=2002, message="股票已在观察池中")
    data = body.model_dump()
    data["ts_code"] = ts_code
    stock = WatchStock(pool_id=pool_id, **data)
    db.add(stock)
    db.commit()
    db.refresh(stock)
    out = _enrich_stock(db, stock)
    submit_task("sync", sync_single_stock, ts_code)
    return out


@router.post("/{pool_id}/stocks/batch", response_model=BatchAddResult)
def batch_add_stocks(pool_id: str, body: BatchAddStocks, db: Session = Depends(get_db)):
    """批量添加股票到观察池（策略选股结果）"""
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    result = BatchAddResult()
    added_codes = []
    for ts_code in body.ts_codes:
        try:
            code = normalize_ts_code(ts_code)
        except ValueError as e:
            result.errors.append(f"{ts_code}: {e}")
            continue
        existing = db.query(WatchStock).filter(
            WatchStock.pool_id == pool_id, WatchStock.ts_code == code
        ).first()
        if existing:
            result.skipped += 1
            continue
        stock = WatchStock(
            pool_id=pool_id, ts_code=code, source="strategy",
            added_price=body.added_price, note=body.note,
        )
        db.add(stock)
        result.added += 1
        added_codes.append(code)
    db.commit()
    for code in added_codes:
        submit_task("sync", sync_single_stock, code)
    return result


@router.put("/{pool_id}/stocks/{stock_id}", response_model=WatchStockOut)
def update_stock(pool_id: str, stock_id: str, body: WatchStockUpdate, db: Session = Depends(get_db)):
    stock = db.query(WatchStock).filter(WatchStock.id == stock_id, WatchStock.pool_id == pool_id).first()
    if not stock:
        raise AppError(code=2001, message="股票不存在", status_code=404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(stock, k, v)
    db.commit()
    db.refresh(stock)
    return _enrich_stock(db, stock)


@router.delete("/{pool_id}/stocks/{stock_id}", status_code=204)
def delete_stock(pool_id: str, stock_id: str, db: Session = Depends(get_db)):
    stock = db.query(WatchStock).filter(WatchStock.id == stock_id, WatchStock.pool_id == pool_id).first()
    if not stock:
        raise AppError(code=2001, message="股票不存在", status_code=404)
    db.delete(stock)
    db.commit()


@router.post("/{pool_id}/stocks/import", response_model=CSVImportResult)
async def import_csv(pool_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("gbk")
    reader = csv.DictReader(io.StringIO(text))
    result = CSVImportResult()
    imported_codes: list[str] = []
    for i, raw_row in enumerate(reader):
        row = {k.strip(): v.strip() if v else v for k, v in raw_row.items() if k}
        ts_code = row.get("ts_code") or row.get("股票代码") or row.get("code")
        if not ts_code:
            result.errors.append(f"第 {i+1} 行缺少股票代码")
            continue
        try:
            ts_code = normalize_ts_code(ts_code)
        except ValueError:
            result.errors.append(f"第 {i+1} 行股票代码无效：{ts_code}")
            continue
        existing = db.query(WatchStock).filter(
            WatchStock.pool_id == pool_id, WatchStock.ts_code == ts_code
        ).first()
        if existing:
            result.skipped += 1
            continue
        added_price = None
        price_str = row.get("added_price") or row.get("加入价格") or row.get("price")
        if price_str:
            try:
                added_price = float(price_str)
            except ValueError:
                pass
        note = row.get("note") or row.get("备注") or ""
        stock = WatchStock(
            pool_id=pool_id, ts_code=ts_code,
            added_price=added_price, note=note or None,
            source="csv",
        )
        db.add(stock)
        result.imported += 1
        imported_codes.append(ts_code)
    db.commit()
    for code in imported_codes:
        submit_task("sync", sync_single_stock, code)
    return result
