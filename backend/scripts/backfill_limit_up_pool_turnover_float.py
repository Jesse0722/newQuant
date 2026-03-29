#!/usr/bin/env python3
"""
补齐「涨停股票观察池」内所有股票在 daily_quote 表中的 turnover_rate、float_share
（数据来源：Tushare daily_basic，与 sync_service._backfill_turnover_rate 逻辑一致）。

用法（在 backend 目录下）:
  ./venv/bin/python scripts/backfill_limit_up_pool_turnover_float.py
  ./venv/bin/python scripts/backfill_limit_up_pool_turnover_float.py --dry-run
  ./venv/bin/python scripts/backfill_limit_up_pool_turnover_float.py --limit 10
  ./venv/bin/python scripts/backfill_limit_up_pool_turnover_float.py --force   # 覆盖已有非空值

依赖: TUSHARE_TOKEN、网络；SQLite 注意 database locked 时已用 commit 重试。

输出: 已 `flush`，长任务每 `--heartbeat` 秒（默认 30）打印 `[进度]`。管道到 `head`/`tee` 时若仍无输出，可用 `python -u scripts/...`。
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.pool import WatchPool, WatchStock
from app.models.stock import DailyQuote, StockBasic
from app.services.limit_up_service import LIMIT_UP_POOL_NAME
from app.services.sync_service import _commit_with_retry
from app.services.tushare_adapter import tushare_adapter


def _log(msg: str) -> None:
    """立即输出，避免管道/nohup 长时间无输出。"""
    print(msg, flush=True)


def _apply_daily_basic(
    db: Session,
    ts_code: str,
    start_date: str,
    end_date: str,
    *,
    force: bool,
) -> tuple[int, int, str | None]:
    """
    返回 (更新 turnover 行数, 更新 float_share 行数, 错误信息)
    """
    n_tr = 0
    n_fs = 0
    try:
        basic_df = tushare_adapter.get_daily_basic(
            ts_code=ts_code, start_date=start_date, end_date=end_date
        )
        if basic_df.empty:
            return 0, 0, "daily_basic 空"

        latest_fs = None
        sub = basic_df.dropna(subset=["float_share"]) if "float_share" in basic_df.columns else None
        if sub is not None and not sub.empty:
            sub = sub.sort_values("trade_date")
            v = sub.iloc[-1].get("float_share")
            if v is not None and not (isinstance(v, float) and v != v):
                latest_fs = float(v)

        for _, row in basic_df.iterrows():
            td = str(row.get("trade_date", ""))
            if not td:
                continue
            quote = (
                db.query(DailyQuote)
                .filter(DailyQuote.ts_code == ts_code, DailyQuote.trade_date == td)
                .first()
            )
            if not quote:
                continue
            tr = row.get("turnover_rate")
            if tr is not None and not (isinstance(tr, float) and tr != tr):
                fv = float(tr)
                if force or quote.turnover_rate is None:
                    if quote.turnover_rate != fv:
                        quote.turnover_rate = fv
                        n_tr += 1
            fs = row.get("float_share")
            if fs is not None and not (isinstance(fs, float) and fs != fs):
                fv = float(fs)
                if force or quote.float_share is None:
                    if quote.float_share != fv:
                        quote.float_share = fv
                        n_fs += 1

        if latest_fs is not None:
            basic_row = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
            if basic_row:
                basic_row.float_share = latest_fs

        _commit_with_retry(db)
        return n_tr, n_fs, None
    except Exception as e:
        db.rollback()
        return 0, 0, str(e)[:200]


def _pool_stats(db: Session, ts_codes: list[str]) -> tuple[int, int, int]:
    """(总行数, turnover 为空行数, float_share 为空行数)"""
    if not ts_codes:
        return 0, 0, 0
    total = (
        db.query(func.count())
        .select_from(DailyQuote)
        .filter(DailyQuote.ts_code.in_(ts_codes))
        .scalar()
    )
    null_tr = (
        db.query(func.count())
        .select_from(DailyQuote)
        .filter(DailyQuote.ts_code.in_(ts_codes), DailyQuote.turnover_rate.is_(None))
        .scalar()
    )
    null_fs = (
        db.query(func.count())
        .select_from(DailyQuote)
        .filter(DailyQuote.ts_code.in_(ts_codes), DailyQuote.float_share.is_(None))
        .scalar()
    )
    return int(total or 0), int(null_tr or 0), int(null_fs or 0)


def main():
    ap = argparse.ArgumentParser(description="补齐涨停池 daily_quote 换手率/流通股本")
    ap.add_argument("--dry-run", action="store_true", help="只统计不调用接口")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 只股票（0=全部）")
    ap.add_argument("--force", action="store_true", help="覆盖已有 turnover/float_share")
    ap.add_argument("--sleep", type=float, default=0.2, help="每股请求间隔秒（防限流）")
    ap.add_argument(
        "--heartbeat",
        type=float,
        default=30.0,
        help="至少每 N 秒打印一次进度摘要（默认 30）",
    )
    args = ap.parse_args()

    db = SessionLocal()
    try:
        pool = db.query(WatchPool).filter(WatchPool.name == LIMIT_UP_POOL_NAME).first()
        if not pool:
            _log(f"未找到池子: {LIMIT_UP_POOL_NAME}")
            sys.exit(1)
        stocks = (
            db.query(WatchStock)
            .filter(WatchStock.pool_id == pool.id)
            .order_by(WatchStock.ts_code)
            .all()
        )
        codes = [s.ts_code for s in stocks]
        if args.limit and args.limit > 0:
            codes = codes[: args.limit]
        _log(f"池: {LIMIT_UP_POOL_NAME} (id={pool.id})")
        _log(f"待处理股票数: {len(codes)}（全池共 {len(stocks)} 只）")

        t0, null_tr0, null_fs0 = _pool_stats(db, codes)
        _log(f"回填前 daily_quote: 总行={t0}, turnover_rate 空={null_tr0}, float_share 空={null_fs0}")

        if args.dry_run:
            return

        ok = 0
        fail = 0
        api_empty = 0
        sum_tr = 0
        sum_fs = 0
        t_start = time.time()
        last_heartbeat = t_start
        est_min = len(codes) * max(0.0, args.sleep) / 60.0
        _log(
            f"开始回填… heartbeat 每 {args.heartbeat:g}s；sleep {args.sleep:g}s/股；粗估约 {est_min:.1f} 分钟"
        )

        for i, ts_code in enumerate(codes):
            bounds = (
                db.query(func.min(DailyQuote.trade_date), func.max(DailyQuote.trade_date))
                .filter(DailyQuote.ts_code == ts_code)
                .first()
            )
            if not bounds or bounds[0] is None:
                _log(f"[{i+1}/{len(codes)}] {ts_code} 无日线，跳过")
                fail += 1
                continue
            start_date, end_date = str(bounds[0]), str(bounds[1])
            n_tr, n_fs, err = _apply_daily_basic(
                db, ts_code, start_date, end_date, force=args.force
            )
            if err:
                if err == "daily_basic 空":
                    api_empty += 1
                _log(f"[{i+1}/{len(codes)}] {ts_code} err: {err}")
                fail += 1
            else:
                ok += 1
                sum_tr += n_tr
                sum_fs += n_fs
                if (i + 1) % 50 == 0 or n_tr + n_fs > 0:
                    _log(f"[{i+1}/{len(codes)}] {ts_code} ok 更新 tr行={n_tr} fs行={n_fs}")

            now = time.time()
            if now - last_heartbeat >= args.heartbeat:
                done = i + 1
                pct = 100.0 * done / len(codes) if codes else 0
                _log(
                    f"[进度] {done}/{len(codes)} ({pct:.1f}%) "
                    f"成功={ok} 失败={fail} 已写入tr行≈{sum_tr} fs行≈{sum_fs} "
                    f"历时 {now - t_start:.0f}s"
                )
                last_heartbeat = now

            time.sleep(max(0.0, args.sleep))

        elapsed = time.time() - t_start
        t1, null_tr1, null_fs1 = _pool_stats(db, codes)
        _log("---")
        _log(f"完成: 成功调用={ok}, 失败/无数据={fail}, daily_basic 空≈{api_empty}")
        _log(f"累计写入 turnover 字段次数(行)≈{sum_tr}, float_share≈{sum_fs}, 耗时 {elapsed:.1f}s")
        _log(
            f"回填后 daily_quote: 总行={t1}, turnover_rate 空={null_tr1}, float_share 空={null_fs1}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
