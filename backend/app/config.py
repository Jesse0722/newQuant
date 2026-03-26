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


def _normalize_tushare_api_base(url: str) -> str:
    """与 tushare DataApi 一致：请求 POST 到 ``{base}/{api_name}``。

    官方默认 base 为 ``http://api.waditu.com/dataapi``。若 .env 只写
    ``http://IP`` 或 ``http://IP:端口``，库会错误地请求 ``http://IP/stock_basic``，
    多数代理返回「token不对」等非直白错误。**仅主机无路径时自动补全 ``/dataapi``**。
    若代理挂载在其它路径（如 ``http://host/tushare``），请写完整 base，勿依赖自动补全。
    """
    url = url.strip().rstrip("/")
    if not url:
        return ""
    try:
        from urllib.parse import urlparse

        path = (urlparse(url).path or "").strip("/")
    except Exception:
        path = ""
    if not path:
        fixed = f"{url}/dataapi"
        logger.info("TUSHARE_API_URL 无路径，已自动补全为 %s", fixed)
        return fixed
    return url


DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'quant.db'}")
# 去掉首尾空格/换行，避免从网页复制 token 后出现「您的token不对」
TUSHARE_TOKEN = (os.getenv("TUSHARE_TOKEN") or "").strip()
_tushare_url_raw = (os.getenv("TUSHARE_API_URL") or "").strip().rstrip("/")
TUSHARE_API_URL = _normalize_tushare_api_base(_tushare_url_raw) if _tushare_url_raw else ""

if not TUSHARE_TOKEN:
    logger.warning("TUSHARE_TOKEN 未配置，数据同步功能将不可用。请在 .env 文件中设置 TUSHARE_TOKEN")
