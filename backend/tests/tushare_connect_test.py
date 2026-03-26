"""从 backend/ 目录运行: python tests/tushare_connect_test.py

使用与主程序相同的 .env 与 TushareAdapter（含 TUSHARE_API_URL 自动补全 /dataapi）。
"""
import sys
from pathlib import Path

# 保证可导入 app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import TUSHARE_TOKEN, TUSHARE_API_URL  # noqa: E402
from app.services.tushare_adapter import tushare_adapter  # noqa: E402


def main() -> None:
    print("TUSHARE_API_URL:", TUSHARE_API_URL or "(未设置，官方接口)")
    print("TOKEN 长度:", len(TUSHARE_TOKEN))
    if not TUSHARE_TOKEN:
        print("未配置 TUSHARE_TOKEN，请编辑 backend/.env")
        sys.exit(1)
    df = tushare_adapter.get_stock_basic()
    print("stock_basic 行数:", len(df))
    if df is not None and not df.empty:
        print(df.head(3))
    else:
        print("Empty DataFrame（若 TOKEN 在官网正确，检查代理是否需完整路径 /dataapi）")
        sys.exit(2)


if __name__ == "__main__":
    main()
