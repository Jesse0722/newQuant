from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.stock import StockBasic, DailyQuote
from app.models.monitor import Alert
from app.models.trade import TradeDetail
from app.schemas.trade import TradeDetailCreate, TradeDetailOut
from app.services.indicator import calc_ma, calc_macd, calc_rsi
from app.services.buy_signal_service import get_signal_marks
from app.services.sync_service import sync_stock_info, sync_daily
from app.services.trade_date_resolver import TradeDateResolutionError, resolve_dashboard_trade_date
from app.services.trading_session import shanghai_trade_date_str
from app.services.tushare_adapter import tushare_adapter
from app.exceptions import AppError
import pandas as pd
import numpy as np

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


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
    失败或超时时降级为返回本地已有数据，避免源站阻塞导致图表长时间无响应。
    是否「已最新」与仪表盘一致：按上海时区 + 交易日历得到目标 trade_date，而非服务器本地日历日。
    """
    try:
        target_latest = resolve_dashboard_trade_date()
    except TradeDateResolutionError:
        target_latest = shanghai_trade_date_str()
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
                "message": "自动补齐超时，已返回本地已有 K 线（可稍后在数据页全量同步）",
                "latest_trade_date": latest_after or latest,
            }
    finally:
        # 勿用 with ThreadPoolExecutor：退出时 shutdown(wait=True) 会在超时后仍等待后台线程，请求永久挂起
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
    return {
        "auto_sync_attempted": True,
        "status": "updated" if (added or 0) > 0 else "up_to_date",
        "message": f"已自动补齐，新增 {added or 0} 条",
        "latest_trade_date": latest_after or latest,
        "added_count": int(added or 0),
    }


@router.get("/{ts_code}/chart")
def get_stock_chart(
    ts_code: str,
    period: int = Query(120, ge=10, le=500),
    mark_signals: bool = Query(False, description="是否返回买点标注数据"),
    limit_up_date: str = Query(None, description="涨停日期，用于标注生命线"),
    auto_sync_latest: bool = Query(True, description="查询前是否自动补齐最新K线"),
    db: Session = Depends(get_db),
):
    basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    if not basic:
        raise AppError(code=5001, message="股票不存在", status_code=404)

    sync_meta = None
    if auto_sync_latest:
        sync_meta = _ensure_latest_kline(db, ts_code)

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
        "vol": q.vol, "amount": q.amount, "pct_chg": q.pct_chg,
        "turnover_rate": q.turnover_rate,
    } for q in quotes])

    def _fetch_daily_basic_bounded() -> pd.DataFrame:
        start_date = str(df["date"].iloc[0])
        end_date = str(df["date"].iloc[-1])
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(
                tushare_adapter.get_daily_basic,
                ts_code,
                start_date,
                end_date,
            )
            try:
                return fut.result(timeout=12.0)
            except FutureTimeout:
                return pd.DataFrame()
        finally:
            ex.shutdown(wait=False)

    # 仅当本地仍有缺失换手率时再请求 Tushare，且带超时，避免图表接口被网络挂死
    if df["turnover_rate"].isna().any():
        try:
            basic_df = _fetch_daily_basic_bounded()
            if not basic_df.empty and "trade_date" in basic_df.columns and "turnover_rate" in basic_df.columns:
                turnover_map = {
                    str(row["trade_date"]): row["turnover_rate"]
                    for _, row in basic_df.iterrows()
                    if row.get("trade_date") is not None
                }
                fill = df["date"].map(turnover_map)
                df["turnover_rate"] = df["turnover_rate"].where(~df["turnover_rate"].isna(), fill)
        except Exception:
            pass

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
