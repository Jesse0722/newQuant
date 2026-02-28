"""应用配置"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 数据目录（相对于 backend 目录）
_BASE = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(_BASE / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 数据库
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'quant.db'}")

# Tushare
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
