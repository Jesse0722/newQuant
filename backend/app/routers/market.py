from __future__ import annotations

from fastapi import APIRouter

from app.services.trading_session import is_a_share_trading_session

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/trading-session")
def get_trading_session():
    """与扫描服务同源的交易时段判定，供前端轻量轮询。"""
    return {"in_session": is_a_share_trading_session()}
