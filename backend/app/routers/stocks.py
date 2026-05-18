from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.stock import StockBasic, DailyQuote
from app.models.monitor import Alert
from app.models.trade import TradeDetail
from app.schemas.trade import TradeDetailCreate, TradeDetailOut
from app.services.indicator import calc_ma, calc_macd, calc_rsi
from app.services.buy_signal_service import get_signal_marks
from app.services.ai_analysis_service import analyze_stock_detail, get_latest_stock_analysis
from app.services.sync_service import sync_stock_info, sync_daily, sync_daily_backward
from app.services.trading_session import shanghai_trade_date_str, latest_daily_k_trade_date_str
from app.services.tushare_adapter import tushare_adapter, TushareAdapter, TencentAdapter, BaoStockAdapter, AkshareAdapter
from app.exceptions import AppError
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


class StockAiAnalysisRequest(BaseModel):
    mode: str = Field("deep", description="fast 或 deep")
    scope: str = Field("stock_detail", description="stock_detail 或 watch_pool")
    pool_id: str | None = None
    watch_stock_id: str | None = None
    force_refresh: bool = False


@router.get("/search")
def search_stocks(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """按股票名称或代码模糊搜索 stock_basic，用于添加股票时的联想"""
    kw = f"%{q.strip()}%"
    rows = (
        db.query(StockBasic)
        .filter(
            (StockBasic.name.like(kw)) | (StockBasic.ts_code.like(kw)) | (StockBasic.symbol.like(kw))
        )
        .limit(limit)
        .all()
    )
    return [{"ts_code": r.ts_code, "stock_name": r.name} for r in rows]


def _nan_to_none(series: pd.Series) -> list:
    return [None if (v is None or (isinstance(v, float) and np.isnan(v))) else round(v, 4) for v in series]


def _scalar_json_safe(v):
    """避免 nan/inf 进入 JSON（pandas to_dict 会保留 float nan）。"""
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        fv = float(v)
        if not np.isfinite(fv):
            return None
        return fv
    if isinstance(v, (np.integer,)) and not isinstance(v, bool):
        return int(v)
    return v


def _chart_quotes_json_safe(records: list[dict]) -> list[dict]:
    return [{k: _scalar_json_safe(val) for k, val in row.items()} for row in records]


def _enrich_basic_from_fallbacks(db: Session, ts_code: str, basic: StockBasic | None) -> StockBasic | None:
    """
    主数据源返回基础信息字段为空时，尝试用备用来源补齐行业/地区/上市日。
    """
    target = basic or db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    if not target:
        return target
    # area 在多源中缺失较常见，不作为每次详情请求的强制补齐条件，避免频繁外网调用拖慢 K 线加载。
    if target.industry and target.list_date:
        return target

    for provider in (AkshareAdapter(), TushareAdapter(), BaoStockAdapter()):
        try:
            df = provider.get_stock_basic(ts_code=ts_code)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        if "ts_code" in df.columns:
            matched = df[df["ts_code"].astype(str) == str(ts_code)]
            row = matched.iloc[0] if not matched.empty else df.iloc[0]
        else:
            row = df.iloc[0]
        changed = False
        if (not target.industry) and row.get("industry"):
            target.industry = str(row.get("industry"))
            changed = True
        if (not target.area) and row.get("area"):
            target.area = str(row.get("area"))
            changed = True
        if (not target.list_date) and row.get("list_date"):
            target.list_date = str(row.get("list_date"))
            changed = True
        if changed:
            db.commit()
            db.refresh(target)
            break
    return target


def _filter_valid_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["open"] = pd.to_numeric(out["open"], errors="coerce")
    out["high"] = pd.to_numeric(out["high"], errors="coerce")
    out["low"] = pd.to_numeric(out["low"], errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    valid = (
        out["open"].gt(0)
        & out["high"].gt(0)
        & out["low"].gt(0)
        & out["close"].gt(0)
        & out["high"].ge(out["low"])
        & out["high"].ge(out["open"])
        & out["high"].ge(out["close"])
        & out["low"].le(out["open"])
        & out["low"].le(out["close"])
    )
    return out.loc[valid].copy()


def _max_calendar_gap_days(df: pd.DataFrame) -> int:
    if df is None or df.empty or "date" not in df.columns or len(df) < 2:
        return 0
    d = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce").dropna().sort_values()
    if len(d) < 2:
        return 0
    gaps = d.diff().dt.days.dropna()
    return int(gaps.max()) if not gaps.empty else 0


def _backfill_sparse_chart_from_remote(db: Session, ts_code: str, base_df: pd.DataFrame, period: int) -> pd.DataFrame:
    """
    当本地行情过少时，尝试临时拉取远程历史并回填库，避免K线仅1-2根导致显示异常。
    """
    if not base_df.empty and len(base_df) >= max(30, period // 2):
        return base_df

    start_date = (datetime.now() - timedelta(days=max(420, period * 4))).strftime("%Y%m%d")
    end_date = shanghai_trade_date_str()
    # 优先免费源：腾讯日K直连，其次当前路由源，再降级 BaoStock/AkShare。
    providers = [TencentAdapter(), tushare_adapter, BaoStockAdapter(), AkshareAdapter()]
    remote = pd.DataFrame()
    for p in providers:
        try:
            r = p.get_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if r is not None and not r.empty:
                remote = r.copy()
                break
        except Exception:
            continue

    if remote.empty:
        return base_df

    remote = remote.rename(columns={"trade_date": "date"})
    for col in ("vol", "amount", "pct_chg", "turnover_rate"):
        if col not in remote.columns:
            remote[col] = None
    remote = remote[["date", "open", "high", "low", "close", "vol", "amount", "pct_chg", "turnover_rate"]]
    remote["date"] = remote["date"].astype(str)
    remote = _filter_valid_ohlc(remote)
    if remote.empty:
        return base_df

    # 尝试回写数据库（仅新增），后续请求可直接命中本地。
    try:
        existing_dates = {
            x[0]
            for x in db.query(DailyQuote.trade_date).filter(DailyQuote.ts_code == ts_code).all()
        }
        add_count = 0
        for _, row in remote.iterrows():
            td = str(row["date"])
            if td in existing_dates:
                continue
            db.add(DailyQuote(
                ts_code=ts_code,
                trade_date=td,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                pre_close=None,
                change=None,
                pct_chg=float(row["pct_chg"]) if row.get("pct_chg") is not None and pd.notna(row.get("pct_chg")) else None,
                vol=float(row["vol"]) if row.get("vol") is not None and pd.notna(row.get("vol")) else None,
                amount=float(row["amount"]) if row.get("amount") is not None and pd.notna(row.get("amount")) else None,
                turnover_rate=float(row["turnover_rate"]) if row.get("turnover_rate") is not None and pd.notna(row.get("turnover_rate")) else None,
            ))
            add_count += 1
        if add_count > 0:
            db.commit()
    except Exception:
        db.rollback()

    if base_df.empty:
        merged = remote
    else:
        merged = pd.concat([base_df, remote], ignore_index=True)
    merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
    return _filter_valid_ohlc(merged)


def _sync_stock_kline_job(ts_code: str) -> tuple[int | None, Exception | None]:
    """在独立会话中跑同步，供主请求线程做超时控制（Session 非线程安全）。"""
    from app.database import SessionLocal

    s = SessionLocal()
    try:
        sync_stock_info(s, ts_code)
        added = sync_daily(s, ts_code, days=250)
        return (int(added or 0), None)
    except Exception as e:
        try:
            s.rollback()
        except Exception:
            pass
        return (None, e)
    finally:
        s.close()


def _ensure_latest_kline(db: Session, ts_code: str) -> dict:
    """
    详情查询前自动增量补齐该股票日线到最新可用交易日。
    仅同步日线，不再额外做实时/日内K线补数。
    """
    # 这里不再依赖远端交易日历判断“是否最新”。
    # 当上游日历源异常或滞后时，会误把旧日期认成最新，导致自动补齐完全不触发。
    target_latest = latest_daily_k_trade_date_str()
    latest = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
    if latest and latest >= target_latest:
        return {
            "auto_sync_attempted": False,
            "status": "up_to_date",
            "message": "本地数据已是最新",
            "latest_trade_date": latest,
        }
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(_sync_stock_kline_job, ts_code)
        try:
            added, err = fut.result(timeout=25.0)
        except FutureTimeout:
            latest_after = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
            return {
                "auto_sync_attempted": True,
                "status": "sync_failed",
                "message": "自动补齐超时，已返回本地已有 K 线",
                "latest_trade_date": latest_after or latest,
            }
    finally:
        ex.shutdown(wait=False)

    if err is not None:
        latest_after = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
        return {
            "auto_sync_attempted": True,
            "status": "sync_failed",
            "message": f"自动补齐失败：{str(err)[:120]}",
            "latest_trade_date": latest_after or latest,
        }
    latest_after = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
    if (added or 0) <= 0 and (latest_after or latest or "") < target_latest:
        stale_date = latest_after or latest
        return {
            "auto_sync_attempted": True,
            "status": "sync_failed",
            "message": "自动补齐未拿到新数据，当前数据仍未更新到最新交易日",
            "latest_trade_date": stale_date,
            "target_trade_date": target_latest,
            "added_count": int(added or 0),
        }
    return {
        "auto_sync_attempted": True,
        "status": "updated" if (added or 0) > 0 else "up_to_date",
        "message": f"已自动补齐，新增 {added or 0} 条",
        "latest_trade_date": latest_after or latest,
        "added_count": int(added or 0),
    }


def _sync_backward_job(ts_code: str, target_min_rows: int) -> tuple[int | None, Exception | None]:
    """独立会话中向前补齐历史日线，供主线程超时控制。"""
    from app.database import SessionLocal

    s = SessionLocal()
    try:
        added = sync_daily_backward(s, ts_code, target_min_rows)
        return (int(added or 0), None)
    except Exception as e:
        try:
            s.rollback()
        except Exception:
            pass
        return (None, e)
    finally:
        s.close()


def _ensure_chart_depth_kline(db: Session, ts_code: str, period: int) -> dict | None:
    """
    若本地日线条数不足以覆盖当前周期 + 指标预热（period+60），则向更早日期实时拉取补齐。
    """
    need = period + 60
    cnt = db.query(DailyQuote).filter(DailyQuote.ts_code == ts_code).count()
    if cnt >= need:
        return None

    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(_sync_backward_job, ts_code, need)
        try:
            added, err = fut.result(timeout=40.0)
        except FutureTimeout:
            return {
                "chart_depth_attempted": True,
                "status": "timeout",
                "message": f"历史K线补齐超时（建议约 {need} 条，当前 {cnt} 条），已返回本地已有数据",
                "rows_before": cnt,
                "need_rows": need,
            }
    finally:
        ex.shutdown(wait=False)

    if err is not None:
        db.expire_all()
        cnt_after = db.query(DailyQuote).filter(DailyQuote.ts_code == ts_code).count()
        return {
            "chart_depth_attempted": True,
            "status": "failed",
            "message": f"历史K线补齐失败：{str(err)[:120]}",
            "rows_before": cnt,
            "rows_after": cnt_after,
            "need_rows": need,
        }

    db.expire_all()
    cnt_after = db.query(DailyQuote).filter(DailyQuote.ts_code == ts_code).count()
    return {
        "chart_depth_attempted": True,
        "status": "updated" if (added or 0) > 0 else "unchanged",
        "message": f"历史K线已补齐，新增 {added or 0} 条（当前共 {cnt_after} 条）",
        "rows_before": cnt,
        "rows_after": cnt_after,
        "added_count": int(added or 0),
        "need_rows": need,
    }


@router.get("/{ts_code}/chart")
def get_stock_chart(
    ts_code: str,
    period: int = Query(120, ge=10, le=500),
    mark_signals: bool = Query(False, description="是否返回买点标注数据"),
    limit_up_date: str = Query(None, description="涨停日期，用于标注生命线"),
    auto_sync_latest: bool = Query(True, description="查询前是否自动补齐最新日K"),
    db: Session = Depends(get_db),
):
    basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    # K 线首屏优先返回本地数据；行业/上市日缺失不阻塞图表加载。
    # 完全不存在的股票仍保留一次同步兜底，用于支持直接访问新代码。
    if not basic:
        try:
            sync_stock_info(db, ts_code)
            basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
        except Exception:
            basic = None
    if not basic:
        raise AppError(code=5001, message="股票不存在", status_code=404)

    sync_meta = None
    depth_meta = None
    if auto_sync_latest:
        sync_meta = _ensure_latest_kline(db, ts_code)
        depth_meta = _ensure_chart_depth_kline(db, ts_code, period)
        if sync_meta or depth_meta:
            db.expire_all()

    quotes = (
        db.query(DailyQuote)
        .filter(DailyQuote.ts_code == ts_code)
        .order_by(DailyQuote.trade_date.desc())
        .limit(period + 60)
        .all()
    )
    if not quotes:
        return {"basic": _basic_dict(basic), "quotes": [], "indicators": {}}

    quotes.reverse()
    df = pd.DataFrame([{
        "date": q.trade_date,
        "open": q.open, "high": q.high, "low": q.low, "close": q.close,
        "pre_close": q.pre_close, "change": q.change,
        "vol": q.vol, "amount": q.amount, "pct_chg": q.pct_chg,
        "turnover_rate": q.turnover_rate,
    } for q in quotes])
    if "pct_chg" in df.columns:
        miss = df["pct_chg"].isna()
        if miss.any():
            pre_close = pd.to_numeric(df.get("pre_close"), errors="coerce")
            close = pd.to_numeric(df.get("close"), errors="coerce")
            change = pd.to_numeric(df.get("change"), errors="coerce")
            by_close = (close - pre_close) / pre_close * 100.0
            by_change = change / pre_close * 100.0
            df.loc[miss, "pct_chg"] = by_close[miss]
            miss2 = df["pct_chg"].isna()
            df.loc[miss2, "pct_chg"] = by_change[miss2]
            # 第三层兜底：当前记录 pre_close 缺失时，用前一根 K 的 close 估算涨跌幅。
            miss3 = df["pct_chg"].isna()
            if miss3.any():
                prev_close = close.shift(1)
                by_prev_close = (close - prev_close) / prev_close * 100.0
                df.loc[miss3, "pct_chg"] = by_prev_close[miss3]
    df = _filter_valid_ohlc(df)
    # 除“条数过少”外，若存在明显时间断层也触发远程回填（例如中间缺失一大段交易日）。
    gap_days = _max_calendar_gap_days(df)
    if len(df) < max(30, period // 2) or gap_days >= 12:
        df = _backfill_sparse_chart_from_remote(db, ts_code, df, period)
    if df.empty:
        return {"basic": _basic_dict(basic), "quotes": [], "indicators": {}}

    ma5 = _nan_to_none(calc_ma(df, 5))
    ma10 = _nan_to_none(calc_ma(df, 10))
    ma20 = _nan_to_none(calc_ma(df, 20))
    dif, dea, histogram = calc_macd(df)
    rsi = _nan_to_none(calc_rsi(df, 14))

    tail = len(df) - period if len(df) > period else 0
    sl = slice(tail, None)

    result = {
        "basic": _basic_dict(basic),
        "quotes": _chart_quotes_json_safe(df.iloc[sl].to_dict("records")),
        "indicators": {
            "ma5": ma5[sl],
            "ma10": ma10[sl],
            "ma20": ma20[sl],
            "macd": {
                "dif": _nan_to_none(dif)[sl],
                "dea": _nan_to_none(dea)[sl],
                "histogram": _nan_to_none(histogram)[sl],
            },
            "rsi": rsi[sl],
        },
    }

    if sync_meta:
        result["sync_meta"] = sync_meta
    if depth_meta:
        result["chart_depth_meta"] = depth_meta

    if mark_signals:
        result["signal_marks"] = get_signal_marks(db, ts_code, limit_up_date)

    return result


@router.get("/{ts_code}/alerts")
def get_stock_alerts(ts_code: str, db: Session = Depends(get_db)):
    alerts = (
        db.query(Alert)
        .filter(Alert.ts_code == ts_code)
        .order_by(Alert.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": a.id,
            "trigger_date": a.trigger_date,
            "status": a.status,
            "snapshot": a.snapshot,
            "created_at": a.created_at.isoformat() + "Z",
        }
        for a in alerts
    ]


@router.get("/{ts_code}/ai-analysis")
def get_stock_ai_analysis(ts_code: str, db: Session = Depends(get_db)):
    record = get_latest_stock_analysis(db, ts_code)
    if not record:
        return {"analysis": None}
    return record


@router.post("/{ts_code}/ai-analysis")
def run_stock_ai_analysis(ts_code: str, body: StockAiAnalysisRequest, db: Session = Depends(get_db)):
    try:
        return analyze_stock_detail(
            db,
            ts_code,
            mode=body.mode,
            scope=body.scope,
            pool_id=body.pool_id,
            watch_stock_id=body.watch_stock_id,
            force_refresh=body.force_refresh,
        )
    except ValueError as e:
        raise AppError(code=5002, message=str(e), status_code=400)
    except RuntimeError as e:
        raise AppError(code=5003, message=str(e), status_code=400)
    except Exception as e:
        raise AppError(code=5003, message=f"AI 分析失败：{str(e)[:160]}", status_code=400)


@router.get("/{ts_code}/details", response_model=list[TradeDetailOut])
def get_stock_details(ts_code: str, db: Session = Depends(get_db)):
    details = (
        db.query(TradeDetail)
        .filter(TradeDetail.ts_code == ts_code)
        .order_by(TradeDetail.trade_date.desc(), TradeDetail.created_at.desc())
        .limit(200)
        .all()
    )
    return [TradeDetailOut.model_validate(d) for d in details]


@router.post("/{ts_code}/details", response_model=TradeDetailOut, status_code=201)
def create_stock_detail(ts_code: str, body: TradeDetailCreate, db: Session = Depends(get_db)):
    basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    if not basic:
        raise AppError(code=5001, message="股票不存在", status_code=404)
    amount = round(body.price * body.quantity, 2)
    stamp_tax = round(amount * 0.0005, 2) if body.direction == "sell" else 0.0
    detail = TradeDetail(
        ts_code=ts_code,
        amount=amount,
        stamp_tax=stamp_tax,
        **body.model_dump(),
    )
    db.add(detail)
    db.commit()
    db.refresh(detail)
    return TradeDetailOut.model_validate(detail)


def _basic_dict(basic: StockBasic) -> dict:
    return {
        "ts_code": basic.ts_code,
        "name": basic.name,
        "industry": basic.industry,
        "area": basic.area,
        "market": basic.market,
        "list_date": basic.list_date,
    }
