"""AI 智能选股服务：支持 OpenAI、通义千问、Ollama"""
import re
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.stock import StockBasic
from app.models.pool import WatchStock
from app.services.llm_client import call_llm
from app.services.tushare_adapter import tushare_adapter
from app.tasks.background import task_registry

SCREEN_PROMPT = """你是一个A股选股助手。用户会用一句话描述选股条件，请根据描述返回符合条件的股票代码列表。

要求：
1. 只返回JSON格式的股票代码列表，不要其他解释。
2. 格式必须为：{"ts_codes": ["000001.SZ", "600000.SH", ...]}
3. 股票代码格式：6位数字+交易所后缀，沪市.SH，深市.SZ，北交所.BJ
4. 仅返回你确信存在的A股代码，不要编造
5. 若无法确定，返回空列表 {"ts_codes": []}

用户选股描述："""
# 可选：若 scope 为 pool，可追加：\n\n可选股票池（仅从以下筛选）：{ts_codes}


def _get_valid_codes(db: Session, ts_codes: list[str]) -> set[str]:
    """校验股票代码是否存在于 stock_basic"""
    valid = set()
    for code in ts_codes:
        if not code or not isinstance(code, str):
            continue
        code = code.strip().upper()
        if not re.match(r"^\d{6}\.(SH|SZ|BJ)$", code):
            continue
        exists = db.query(StockBasic).filter(StockBasic.ts_code == code).first()
        if exists:
            valid.add(code)
    return valid


def _ensure_stock_basic(db: Session, ts_codes: list[str]):
    """若 stock_basic 中无记录，从 Tushare 拉取并入库"""
    missing = [c for c in ts_codes if not db.query(StockBasic).filter(StockBasic.ts_code == c).first()]
    if not missing:
        return
    try:
        df = tushare_adapter.get_stock_basic()
        if df.empty:
            return
        missing_set = set(missing)
        for _, row in df.iterrows():
            c = row.get("ts_code")
            if c in missing_set:
                existing = db.query(StockBasic).filter(StockBasic.ts_code == c).first()
                if not existing:
                    db.add(StockBasic(**row.to_dict()))
        db.commit()
    except Exception:
        pass


def _parse_ts_codes(text: str) -> list[str]:
    """从 AI 返回文本中解析 ts_codes"""
    text = text.strip()
    match = re.search(r'\{[^{}]*"ts_codes"\s*:\s*\[([^\]]*)\]', text, re.DOTALL)
    if match:
        inner = match.group(1)
        codes = re.findall(r'"([^"]+)"', inner)
        return [c.strip() for c in codes if c.strip()]
    codes = re.findall(r'\b(\d{6})\.(SH|SZ|BJ)\b', text, re.I)
    return [f"{n}.{e.upper()}" for n, e in codes]


def run_ai_screen(task_id: str, description: str, scope: str | None):
    """
    执行 AI 智能选股。
    description: 用户描述，≤200 字
    scope: full 或 pool_id，可选
    """
    task = task_registry.get(task_id)
    if not task:
        return
    db = SessionLocal()
    try:
        task.message = "正在调用 AI 分析..."
        prompt = SCREEN_PROMPT + description.strip()

        if scope and scope != "full":
            stocks = db.query(WatchStock).filter(WatchStock.pool_id == scope).all()
            if stocks:
                codes_str = ", ".join([s.ts_code for s in stocks[:200]])
                prompt += f"\n\n可选股票池（仅从以下筛选）：{codes_str}"

        raw = call_llm(prompt)

        ts_codes = _parse_ts_codes(raw)
        if not ts_codes:
            task.result = {"ts_codes": [], "stock_names": {}, "total": 0}
            task.status = "completed"
            task.message = "AI 未返回有效股票"
            return

        _ensure_stock_basic(db, ts_codes)
        db.commit()
        valid = _get_valid_codes(db, ts_codes)
        name_map = {}
        for c in valid:
            b = db.query(StockBasic).filter(StockBasic.ts_code == c).first()
            name_map[c] = b.name if b else ""

        task.result = {
            "ts_codes": list(valid),
            "stock_names": name_map,
            "total": len(valid),
        }
        task.status = "completed"
        task.progress = 1.0
        task.message = f"筛选完成，共 {len(valid)} 只"
    except Exception as e:
        task.status = "failed"
        task.message = str(e)
    finally:
        db.close()
