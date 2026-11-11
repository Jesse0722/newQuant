#!/usr/bin/env python3
"""Audited daily-quote repair: fetch -> plan -> apply -> verify / rollback."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, select
from app.models.stock import StockBasic
from app.models.daily_quote_repair import DailyQuoteRepairAudit, DailyQuoteRepairBatch
from app.services.daily_quote_repair_service import (
    RepairError, apply_repair_plan, make_repair_plan, rollback_repair_batch, validate_plan, verify_repair_batch,
)
from app.services.market_data_quality_service import CODE, readonly_connection
from app.services.quote_repair_io import QuoteRepairIOError, create_backup, database_identity, writer_connection
from app.services.quote_repair_source_service import fetch_repair_snapshot, repair_dates, select_repair_source
from scripts.audit_market_data_quality import configured_database


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_json(path, expected_sha256=None):
    path = Path(path)
    if path.stat().st_size > 512 * 1024 * 1024:
        raise RepairError("输入文件过大，请拆分日期窗口")
    with path.open("rb") as f:
        body = f.read(512 * 1024 * 1024 + 1)
    if len(body) > 512 * 1024 * 1024:
        raise RepairError("输入文件过大，请拆分日期窗口")
    if expected_sha256 is not None and hashlib.sha256(body).hexdigest() != expected_sha256.lower():
        raise RepairError("计划文件SHA-256不匹配")
    # Decode the exact bytes that were hashed; never reopen the path afterwards.
    result = json.loads(body)
    if not isinstance(result, dict):
        raise RepairError("输入必须为JSON对象")
    return result


def write_json(path, value):
    """Artifacts are exclusive; never overwrite a reviewed plan or source snapshot."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def render_plan(plan):
    lines = ["# 行情修复差异计划", "", f"- 计划：{plan['id']}", f"- 目标库：`{plan['database_identity']}`",
             f"- 权威来源：{plan['source']['name']}，不复权正式日线",
             f"- 汇总：{plan['summary']}",
             "- 旧行情来源未知；新行全部字段来自本次同一个来源。缺少已有附加字段时默认跳过整条修复。", "",
             "| 股票 | 日期 | 操作 | 变化字段 |", "|---|---|---|---|"]
    lines += [f"| {i['ts_code']} | {i['trade_date']} | {i['operation']} | {', '.join(i['changed_fields'])} |" for i in plan["items"][:1000]]
    lines += ["", "JSON 含所有逐字段新旧值、哈希、原始来源和跳过原因；本摘要最多显示前 1000 条。",
              "应用前核对 JSON；apply 只执行该计划，不会重新联网选取其他行情。", ""]
    return "\n".join(lines)


def _backup(url, app_cwd, directory):
    manifest = create_backup(url, str(app_cwd), str(directory))
    write_json(str(manifest["path"]) + ".manifest.json", manifest)
    return manifest


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app-cwd", type=Path, default=ROOT)
    sub = p.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="采集单一来源到离线快照，不写数据库")
    fetch.add_argument("--source", required=True, choices=["baostock", "akshare", "tushare"])
    fetch.add_argument("--from-date", required=True)
    fetch.add_argument("--to-date", required=True)
    fetch.add_argument("--codes", help="逗号分隔；省略则使用当前主数据诊断股票清单")
    fetch.add_argument("--calendar-csv", type=Path)
    fetch.add_argument("--max-target-rows", type=int, default=50000)
    fetch.add_argument("--output", type=Path, required=True)
    plan = sub.add_parser("plan", help="只读dry-run，输出逐字段差异计划")
    plan.add_argument("--snapshot", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--allow-clear-optional", action="store_true", help="允许计划清空来源缺失的换手率/股本；默认跳过")
    apply = sub.add_parser("apply", help="验证计划哈希，自动备份后应用")
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--plan-sha256", required=True)
    apply.add_argument("--backup-dir", type=Path, required=True)
    verify = sub.add_parser("verify", help="只读校验批次当前值")
    verify.add_argument("--batch-id", required=True)
    rollback = sub.add_parser("rollback", help="重新备份，按批次恢复；有后续修改则拒绝")
    rollback.add_argument("--batch-id", required=True)
    rollback.add_argument("--backup-dir", type=Path, required=True)
    init = sub.add_parser("init-audit-schema", help="仅SQLite显式初始化两张审计表")
    init.add_argument("--backup-dir", type=Path, required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        url, config_source = configured_database(args.app_cwd)
        if args.command == "fetch":
            from app.services.tushare_adapter import tushare_adapter
            source, caps = select_repair_source(tushare_adapter, args.source)
            calendar_path = args.calendar_csv or ROOT / "data_reference" / f"sse_calendar_{args.to_date[:4]}.csv"
            dates, calendar = repair_dates(args.from_date, args.to_date, calendar_path)
            with readonly_connection(url, args.app_cwd) as (conn, _):
                if args.codes:
                    codes = sorted(set(c.strip().upper() for c in args.codes.split(",") if c.strip()))
                else:
                    codes = sorted(c for c in conn.execute(select(StockBasic.ts_code)).scalars() if CODE.fullmatch(c))
                identity = database_identity(conn)
            if not 1 <= args.max_target_rows <= 1000000 or len(codes) * len(dates) > args.max_target_rows:
                raise RepairError("目标范围超过上限，请拆分窗口或明确max-target-rows")
            logger = logging.getLogger("app.services.tushare_adapter")
            disabled = logger.disabled
            try:
                logger.disabled = True  # Suppress upstream URL/token-bearing exception text.
                with redirect_stdout(io.StringIO()):
                    snapshot = fetch_repair_snapshot(source, caps, dates, codes, calendar)
            finally:
                logger.disabled = disabled
            snapshot["target_at_fetch"] = identity
            write_json(args.output, snapshot)
            result = {"status": snapshot["outcome"], "path": str(args.output), "sha256": file_hash(args.output),
                      "rows": len(snapshot["rows"]), "valid_rows": snapshot["valid_row_count"], "requests": snapshot["requests"]}
        elif args.command == "plan":
            snapshot = load_json(args.snapshot)
            if not snapshot.get("rows") or snapshot.get("outcome") in ("failed", "no_data", "unsupported"):
                raise RepairError("来源快照没有有效修复数据；请先处理上游空数据或失败")
            with readonly_connection(url, args.app_cwd) as (conn, _):
                if snapshot.get("target_at_fetch") not in (None, database_identity(conn)):
                    raise RepairError("快照采集目标与当前库不一致")
                plan = make_repair_plan(conn, snapshot, allow_clear_optional=args.allow_clear_optional)
            validate_plan(plan)
            write_json(args.output, plan)
            report = args.output.with_suffix(".md")
            with report.open("x", encoding="utf-8") as f:
                f.write(render_plan(plan))
            result = {"status": "dry_run", "path": str(args.output), "plan_sha256": file_hash(args.output),
                      "summary": plan["summary"], "configuration_source": config_source}
        elif args.command == "verify":
            with readonly_connection(url, args.app_cwd) as (conn, _):
                result = verify_repair_batch(conn, args.batch_id)
        else:
            plan = None
            with readonly_connection(url, args.app_cwd) as (conn, _):
                identity = database_identity(conn)
                if args.command == "init-audit-schema":
                    if identity["dialect"] != "sqlite":
                        raise RepairError("PostgreSQL审计表请使用Alembic增量迁移")
                else:
                    if not {DailyQuoteRepairBatch.__tablename__, DailyQuoteRepairAudit.__tablename__}.issubset(inspect(conn).get_table_names()):
                        raise RepairError("审计表未初始化；先迁移schema")
                if args.command == "apply":
                    plan = load_json(args.plan, args.plan_sha256)
                    validate_plan(plan)
                    if identity != plan["database_identity"]:
                        raise RepairError("计划不属于当前数据库")
            manifest = _backup(url, args.app_cwd, args.backup_dir)
            with writer_connection(url, str(args.app_cwd)) as conn:
                if args.command == "init-audit-schema":
                    for table in (DailyQuoteRepairBatch.__table__, DailyQuoteRepairAudit.__table__):
                        table.create(conn, checkfirst=True)
                    result = {"status": "schema_ready", "backup": manifest}
                elif args.command == "apply":
                    result = apply_repair_plan(conn, plan, manifest, approved_file_sha256=args.plan_sha256.lower())
                else:
                    result = rollback_repair_batch(conn, args.batch_id, manifest)
            result["backup_path"] = manifest["path"]
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        if args.command == "fetch" and result["status"] != "success":
            return 2
        return 2 if args.command == "verify" and not result["matches"] else 0
    except (RepairError, QuoteRepairIOError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"操作失败 ({type(exc).__name__})；未完成的数据库事务已回滚。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
