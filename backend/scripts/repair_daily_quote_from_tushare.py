#!/usr/bin/env python3
"""按交易日用 Tushare 覆盖修复 daily_quote。"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.stock import DailyQuote
from app.services.tushare_adapter import TushareAdapter


def _valid_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    for col in ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["trade_date"] = out["trade_date"].astype(str)
    out["ts_code"] = out["ts_code"].astype(str)
    valid = (
        out["open"].gt(0)
        & out["high"].gt(0)
        & out["low"].gt(0)
        & out["close"].gt(0)
        & out["high"].ge(out["low"])
        & out["high"].ge(out["open"])
        & out["high"].ge(out["close"])
        & out["low"].le(out["open"])
        & out["low"].le(out["close"])
        & out["vol"].ge(0)
        & out["amount"].ge(0)
    )
    cols = ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]
    return out.loc[valid, cols].copy()


@dataclass
class RepairStats:
    dates_total: int = 0
    dates_ok: int = 0
    dates_failed: int = 0
    rows_inserted: int = 0
    rows_deleted: int = 0


def repair(from_date: str | None = None, to_date: str | None = None, sleep_s: float = 0.16) -> RepairStats:
    db = SessionLocal()
    ad = TushareAdapter()
    st = RepairStats()
    try:
        q = db.query(DailyQuote.trade_date).distinct()
        if from_date:
            q = q.filter(DailyQuote.trade_date >= from_date)
        if to_date:
            q = q.filter(DailyQuote.trade_date <= to_date)
        dates = [r[0] for r in q.order_by(DailyQuote.trade_date.asc()).all()]
        st.dates_total = len(dates)
        print(f"需修复交易日: {st.dates_total}")
        for i, td in enumerate(dates, 1):
            try:
                raw = ad.get_daily_by_date(td)
                day = _valid_daily(raw)
                if day.empty:
                    st.dates_failed += 1
                    print(f"[{i}/{st.dates_total}] {td} 空结果，跳过")
                    continue
                mappings = day.to_dict("records")
                deleted = db.query(DailyQuote).filter(DailyQuote.trade_date == td).delete(synchronize_session=False)
                db.bulk_insert_mappings(DailyQuote, mappings)
                db.commit()
                st.dates_ok += 1
                st.rows_deleted += int(deleted or 0)
                st.rows_inserted += len(mappings)
                if i % 10 == 0 or i == st.dates_total:
                    print(
                        f"[{i}/{st.dates_total}] {td} 完成, 插入={len(mappings)}, "
                        f"累计插入={st.rows_inserted}, 失败日={st.dates_failed}"
                    )
            except Exception as e:
                db.rollback()
                st.dates_failed += 1
                print(f"[{i}/{st.dates_total}] {td} 失败: {str(e)[:180]}")
            time.sleep(sleep_s)
    finally:
        db.close()
    return st


def verify() -> tuple[int, int]:
    db = SessionLocal()
    try:
        bad = db.execute(
            text(
            """
            select count(*) from daily_quote
            where open<=0 or high<=0 or low<=0 or close<=0
               or high<low or high<open or high<close or low>open or low>close
            """
            )
        ).scalar_one()
        total = db.execute(text("select count(*) from daily_quote")).scalar_one()
        return int(total), int(bad)
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="按交易日用 Tushare 覆盖修复 daily_quote")
    p.add_argument("--from-date", dest="from_date", default=None, help="起始交易日 YYYYMMDD")
    p.add_argument("--to-date", dest="to_date", default=None, help="结束交易日 YYYYMMDD")
    p.add_argument("--sleep", dest="sleep_s", type=float, default=0.16, help="每个交易日请求间隔秒")
    args = p.parse_args()

    st = repair(args.from_date, args.to_date, args.sleep_s)
    total, bad = verify()
    print(
        f"完成: dates={st.dates_total}, ok={st.dates_ok}, failed={st.dates_failed}, "
        f"deleted={st.rows_deleted}, inserted={st.rows_inserted}, total_rows={total}, bad_rows={bad}"
    )
    return 0 if st.dates_ok > 0 and bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
