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
                "hint": "请检查 Tushare trade_cal 是否可用，或稍后重试。",
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
                    "请检查 backend 环境变量 TUSHARE_TOKEN 与积分权限"
                    "（limit_cpt_list / limit_step 约需 8000 积分）。"
                    "详见 https://tushare.pro/document/2"
                ),
            },
        ) from e
