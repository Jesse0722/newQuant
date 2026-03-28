from datetime import datetime
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


def _ensure_latest_kline(db: Session, ts_code: str) -> dict:
    """
    详情查询前自动增量补齐该股票日线到最新可用交易日。
    失败时降级为返回本地已有数据，避免影响页面可用性。
    """
    today = datetime.now().strftime("%Y%m%d")
    latest = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
    if latest and latest >= today:
        return {
            "auto_sync_attempted": False,
            "status": "up_to_date",
            "message": "本地数据已是最新",
            "latest_trade_date": latest,
        }
    try:
        sync_stock_info(db, ts_code)
        added = sync_daily(db, ts_code, days=250)
        latest_after = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
        return {
            "auto_sync_attempted": True,
            "status": "updated" if (added or 0) > 0 else "up_to_date",
            "message": f"已自动补齐，新增 {added or 0} 条",
            "latest_trade_date": latest_after or latest,
            "added_count": int(added or 0),
        }
    except Exception as e:
        db.rollback()
        latest_after = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
        return {
            "auto_sync_attempted": True,
            "status": "sync_failed",
            "message": f"自动补齐失败：{str(e)[:120]}",
            "latest_trade_date": latest_after or latest,
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
    } for q in quotes])

    # 尝试补充换手率（daily_basic）；部分代理不支持时自动降级，不影响 K 线展示。
    df["turnover_rate"] = np.nan
    try:
        start_date = str(df["date"].iloc[0])
        end_date = str(df["date"].iloc[-1])
        basic_df = tushare_adapter.get_daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if not basic_df.empty and "trade_date" in basic_df.columns and "turnover_rate" in basic_df.columns:
            turnover_map = {
                str(row["trade_date"]): row["turnover_rate"]
                for _, row in basic_df.iterrows()
                if row.get("trade_date") is not None
            }
            df["turnover_rate"] = df["date"].map(turnover_map)
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
        "quotes": df.iloc[sl].to_dict("records"),
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
            "created_at": a.created_at.isoformat(),
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
