from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.limit_market_board_service import get_limit_market_board_payload
from app.services.trade_date_resolver import TradeDateResolutionError

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard(
    trade_date: str | None = Query(
        None,
        description="可选，覆盖默认解析的交易日 YYYYMMDD",
        pattern=r"^\d{8}$",
    ),
):
    try:
        return get_limit_market_board_payload(trade_date=trade_date)
    except TradeDateResolutionError as e:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "TRADE_DATE_RESOLUTION_FAILED",
                "message": str(e),
                "hint": "请检查已配置数据源的交易日历接口是否可用，或稍后重试。",
            },
        ) from e
    except Exception as e:
        msg = str(e)[:500]
        lower = msg.lower()
        if any(x in lower for x in ("timeout", "connection", "timed out", "network", "errno")):
            code = "TUSHARE_UNAVAILABLE"
            status = 503
        else:
            code = "TUSHARE_ERROR"
            status = 502
        raise HTTPException(
            status_code=status,
            detail={
                "code": code,
                "message": msg,
                "hint": (
                    "请检查当前配置的数据源连通性。若使用 Tushare，"
                    "请同时检查 TUSHARE_TOKEN、代理与积分权限。"
                ),
            },
        ) from e
