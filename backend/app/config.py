from __future__ import annotations

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# 显式从 backend/.env 加载，避免 cwd 导致找不到
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)


DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'quant.db'}")
TUSHARE_TOKEN = (os.getenv("TUSHARE_TOKEN") or "").strip()
# 代理地址原样使用，不自动追加路径（不同代理路由规则不同）
TUSHARE_API_URL = (os.getenv("TUSHARE_API_URL") or "").strip().rstrip("/")
DATA_PROVIDER = (os.getenv("DATA_PROVIDER") or "akshare").strip().lower()
COMPOSITE_ORDER = [
    x.strip().lower()
    for x in (os.getenv("COMPOSITE_ORDER") or "akshare,tushare").split(",")
    if x.strip()
]

if DATA_PROVIDER in ("tushare", "composite") and not TUSHARE_TOKEN:
    logger.warning(
        "TUSHARE_TOKEN 未配置，Tushare/组合源将不可用。仅使用 AkShare 时请设置 DATA_PROVIDER=akshare"
    )
