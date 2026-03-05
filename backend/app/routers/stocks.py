from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.stock import StockBasic, DailyQuote
from app.models.monitor import Alert
from app.models.trade import TradeDetail
from app.schemas.trade import TradeDetailCreate, TradeDetailOut
from app.services.indicator import calc_ma, calc_macd, calc_rsi
from app.exceptions import AppError
import pandas as pd
import numpy as np

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


def _nan_to_none(series: pd.Series) -> list:
    return [None if (v is None or (isinstance(v, float) and np.isnan(v))) else round(v, 4) for v in series]


@router.get("/{ts_code}/chart")
def get_stock_chart(
    ts_code: str,
    period: int = Query(120, ge=10, le=500),
    db: Session = Depends(get_db),
):
    basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    if not basic:
        raise AppError(code=5001, message="股票不存在", status_code=404)

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

    ma5 = _nan_to_none(calc_ma(df, 5))
    ma10 = _nan_to_none(calc_ma(df, 10))
    ma20 = _nan_to_none(calc_ma(df, 20))
    dif, dea, histogram = calc_macd(df)
    rsi = _nan_to_none(calc_rsi(df, 14))

    tail = len(df) - period if len(df) > period else 0
    sl = slice(tail, None)

    return {
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
