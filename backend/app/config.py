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
# 去掉首尾空格/换行，避免从网页复制 token 后出现「您的token不对」
TUSHARE_TOKEN = (os.getenv("TUSHARE_TOKEN") or "").strip()
# 代理地址不要尾部的 /，与 tushare 客户端约定一致
TUSHARE_API_URL = (os.getenv("TUSHARE_API_URL") or "").strip().rstrip("/")

if not TUSHARE_TOKEN:
    logger.warning("TUSHARE_TOKEN 未配置，数据同步功能将不可用。请在 .env 文件中设置 TUSHARE_TOKEN")
