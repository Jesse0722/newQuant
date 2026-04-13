#!/usr/bin/env python3
"""备份当前 SQLite（若存在），清理 WAL/SHM，重建空库并全量同步 stock_basic（AkShare）。

运行前需已安装依赖：pip install -r requirements.txt
用法（在 backend 目录下）：
  python scripts/rebuild_db_akshare.py --yes
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="备份 quant.db 并重建，再同步全市场 stock_basic（AkShare）"
    )
    ap.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="确认备份并重建（删除/移动现有库文件）",
    )
    args = ap.parse_args()

    import os

    # 重建时强制 AkShare，避免 .env 中 composite/tushare 影响全市场基础表拉取
    os.environ["DATA_PROVIDER"] = "akshare"

    from app.config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path = DATA_DIR / "quant.db"
    wal = DATA_DIR / "quant.db-wal"
    shm = DATA_DIR / "quant.db-shm"

    has_any = db_path.exists() or wal.exists() or shm.exists()
    if has_any and not args.yes:
        print(
            "检测到现有 quant.db 或 WAL/SHM 文件，请使用 --yes 确认备份并重建。"
        )
        return 1

    if has_any and args.yes:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        if db_path.exists():
            dest = DATA_DIR / f"quant.db.bak-{ts}"
            shutil.move(str(db_path), str(dest))
            print(f"已备份: {dest}")
        for p in (wal, shm):
            if p.exists():
                p.unlink()
                print(f"已删除: {p}")

    from app.database import SessionLocal, init_db
    from app.services.sync_service import _sync_stock_basic_full

    init_db()
    db = SessionLocal()
    try:
        n, ok = _sync_stock_basic_full(db)
        print(f"stock_basic 同步完成: 新增 {n} 条, API 有数据={ok}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
