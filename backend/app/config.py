from __future__ import annotations

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# 显式从 backend/.env 加载，避免 cwd 导致找不到
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)
_raw_data_dir = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR = _raw_data_dir if _raw_data_dir.is_absolute() else BASE_DIR / _raw_data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'quant.db'}")
TUSHARE_TOKEN = (os.getenv("TUSHARE_TOKEN") or "").strip()
# 代理地址原样使用，不自动追加路径（不同代理路由规则不同）
TUSHARE_API_URL = (os.getenv("TUSHARE_API_URL") or "").strip().rstrip("/")
DATA_PROVIDER = (os.getenv("DATA_PROVIDER") or "composite").strip().lower()
COMPOSITE_ORDER = [
    x.strip().lower()
    for x in (os.getenv("COMPOSITE_ORDER") or "tencent,baostock,akshare").split(",")
    if x.strip()
]
APP_ENV = (os.getenv("APP_ENV") or "development").strip().lower()
AUTO_INIT_DB = env_flag("AUTO_INIT_DB", True)
RUN_STARTUP_MIGRATIONS = env_flag("RUN_STARTUP_MIGRATIONS", True)
AUTO_START_SCHEDULER = env_flag("AUTO_START_SCHEDULER", False)
SCHEDULER_ENABLED = env_flag("SCHEDULER_ENABLED", True)
IDLE_KLINE_BACKFILL_ENABLED = env_flag("IDLE_KLINE_BACKFILL_ENABLED", True)
IDLE_KLINE_BACKFILL_INTERVAL_MINUTES = int(os.getenv("IDLE_KLINE_BACKFILL_INTERVAL_MINUTES") or "30")
IDLE_KLINE_BACKFILL_BATCH_SIZE = int(os.getenv("IDLE_KLINE_BACKFILL_BATCH_SIZE") or "4")
IDLE_KLINE_BACKFILL_DAYS = int(os.getenv("IDLE_KLINE_BACKFILL_DAYS") or "250")
IDLE_KLINE_BACKFILL_TARGET_ROWS = int(os.getenv("IDLE_KLINE_BACKFILL_TARGET_ROWS") or "310")
IDLE_KLINE_BACKFILL_MAX_SECONDS = int(os.getenv("IDLE_KLINE_BACKFILL_MAX_SECONDS") or "90")
IDLE_KLINE_BACKFILL_RETRY_COOLDOWN_HOURS = int(os.getenv("IDLE_KLINE_BACKFILL_RETRY_COOLDOWN_HOURS") or "12")
IDLE_MAIN_WAVE_CONCEPT_BACKFILL_ENABLED = env_flag("IDLE_MAIN_WAVE_CONCEPT_BACKFILL_ENABLED", True)
IDLE_MAIN_WAVE_CONCEPT_BACKFILL_INTERVAL_MINUTES = int(os.getenv("IDLE_MAIN_WAVE_CONCEPT_BACKFILL_INTERVAL_MINUTES") or "120")
IDLE_MAIN_WAVE_CONCEPT_BACKFILL_BATCH_SIZE = int(os.getenv("IDLE_MAIN_WAVE_CONCEPT_BACKFILL_BATCH_SIZE") or "12")
IDLE_MAIN_WAVE_CONCEPT_BACKFILL_MAX_SECONDS = int(os.getenv("IDLE_MAIN_WAVE_CONCEPT_BACKFILL_MAX_SECONDS") or "60")
IDLE_MAIN_WAVE_CONCEPT_BACKFILL_RETRY_COOLDOWN_HOURS = int(os.getenv("IDLE_MAIN_WAVE_CONCEPT_BACKFILL_RETRY_COOLDOWN_HOURS") or "24")
INDUSTRY_REPORT_LLM_ENABLED = env_flag("INDUSTRY_REPORT_LLM_ENABLED", False)
INDUSTRY_REPORT_MODEL_PROVIDER = (os.getenv("INDUSTRY_REPORT_MODEL_PROVIDER") or "deepseek").strip().lower()
INDUSTRY_REPORT_MODEL = (os.getenv("INDUSTRY_REPORT_MODEL") or os.getenv("DEEPSEEK_FAST_MODEL") or "deepseek-v4-flash").strip()
MESSAGE_AGENT_MODEL_PROVIDER = (os.getenv("MESSAGE_AGENT_MODEL_PROVIDER") or "deepseek").strip().lower()
MESSAGE_AGENT_MODEL = (os.getenv("MESSAGE_AGENT_MODEL") or os.getenv("DEEPSEEK_FAST_MODEL") or "deepseek-v4-flash").strip()
CORS_ORIGINS = [
    origin.strip()
    for origin in (os.getenv("CORS_ORIGINS") or "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS = env_flag("CORS_ALLOW_CREDENTIALS", True)
X_API_BEARER_TOKEN = (os.getenv("X_API_BEARER_TOKEN") or "").strip()
X_API_BASE_URL = (os.getenv("X_API_BASE_URL") or "https://api.twitter.com").strip().rstrip("/")

if DATA_PROVIDER in ("tushare", "composite") and not TUSHARE_TOKEN:
    logger.warning(
        "TUSHARE_TOKEN 未配置，Tushare/组合源内的 Tushare 回退将不可用。仅使用 BaoStock/AkShare 时可忽略。"
    )
