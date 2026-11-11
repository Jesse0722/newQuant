#!/usr/bin/env python3
"""Read-only daily quote audit, with no app startup, migrations or provider calls."""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from app.services.market_data_quality_service import (
    audit_database, audit_dates, load_universe, readonly_connection, render_markdown,
)


def configured_database(app_cwd, env_file=ROOT / ".env"):
    # dotenv_values has no environment/config mkdir side effects.
    config = dotenv_values(env_file)
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"], "process environment DATABASE_URL"
    if config.get("DATABASE_URL"):
        return config["DATABASE_URL"], str(env_file) + " DATABASE_URL"
    data_dir = Path(os.environ.get("DATA_DIR") or config.get("DATA_DIR") or ROOT / "data")
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    return "sqlite:///" + str(data_dir / "quant.db"), "app default (DATA_DIR/quant.db)"


def _owns_report(path, identity):
    try:
        current = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity


def _write_report_pair(prefix, json_body, markdown_body):
    """Publish a new pair; existing paths, including symlinks, never open for writing.

    Keep descriptors open so replaced paths cannot reuse their original inodes.
    Cleanup checks current path ownership; it leaves observed replacements alone.
    This is not a two-file transaction: interrupted runs require a fresh prefix,
    and readers must require CLI completion (exit 0 or 2) and both report files.
    """
    prefix.parent.mkdir(parents=True, exist_ok=True)
    reserved = []
    try:
        for suffix, body in ((".json", json_body), (".md", markdown_body)):
            path = prefix.with_suffix(suffix)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                metadata = os.fstat(descriptor)
            except BaseException:
                os.close(descriptor)
                raise
            identity = (metadata.st_dev, metadata.st_ino)
            reserved.append((path, descriptor, identity, body))
            os.fchmod(descriptor, 0o600)
        for path, descriptor, identity, body in reserved:
            if not _owns_report(path, identity):
                raise OSError("报告路径已被替换")
            # closefd=False retains ownership for cleanup and inode verification.
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                if stream.write(body) != len(body):
                    raise OSError("报告未完整写入")
                stream.flush()
                os.fsync(descriptor)
        if not all(_owns_report(path, identity) for path, _, identity, _ in reserved):
            raise OSError("报告路径已被替换")
    except BaseException:
        for path, _, identity, _ in reserved:
            try:
                if _owns_report(path, identity):
                    path.unlink()
            except OSError:
                # Leave uncertain paths alone; never risk deleting another file.
                pass
        raise
    finally:
        for _, descriptor, _, _ in reserved:
            os.close(descriptor)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app-cwd", type=Path, default=ROOT, help="运行后端的工作目录，用于解析相对 SQLite URL")
    p.add_argument("--end-date", help="YYYYMMDD，默认上海最近已完成工作日；精确交易日需日历 CSV")
    p.add_argument("--days", type=int, default=120)
    p.add_argument("--detail-days", type=int, default=20)
    p.add_argument("--calendar-csv", type=Path, help="连续自然日 trade_date,is_open")
    p.add_argument("--universe-csv", type=Path, help="每日独立完整证券池，字段见 runbook")
    p.add_argument("--universe-counts-csv", type=Path, help="独立控制总数 trade_date,expected_count,source_url；缺少时不可验证")
    p.add_argument("--universe-evidence-manifest", type=Path, help="离线证券证据 manifest，需同时提供显式 SHA256 和两份 CSV")
    p.add_argument("--universe-evidence-sha256", help="证据 manifest 的显式 SHA256")
    p.add_argument("--output-prefix", type=Path, required=True, help="独占生成新 .json 与 .md，禁止覆盖；需正常完成（退出0/2）且两文件齐全")
    args = p.parse_args(argv)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    end = now if now.time() >= time(16) else now - timedelta(days=1)
    while end.weekday() >= 5:
        end -= timedelta(days=1)
    try:
        if (args.universe_evidence_manifest is None) != (args.universe_evidence_sha256 is None):
            raise ValueError("manifest与显式 SHA256 必须同时提供")
        if args.universe_evidence_manifest is not None and (args.universe_csv is None or args.universe_counts_csv is None):
            raise ValueError("证据 manifest 必须搭配证券清单和控制总数")
        dates, calendar = audit_dates(args.end_date or end.strftime("%Y%m%d"), args.days, args.calendar_csv)
        if args.universe_counts_csv and not args.universe_csv:
            raise ValueError("控制总数需要搭配证券清单")
        universe, info = load_universe(args.universe_csv, dates, args.universe_counts_csv,
            evidence_manifest=args.universe_evidence_manifest, evidence_sha256=args.universe_evidence_sha256)
        url, source = configured_database(args.app_cwd)
        with readonly_connection(url, args.app_cwd) as (conn, identity):
            report = audit_database(conn, dates=dates, calendar=calendar, universe=universe,
                                    universe_info=info, detail_days=args.detail_days)
        report.update(database=identity, configuration_source=source, generated_at=now.isoformat())
        json_body = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        markdown_body = render_markdown(report).encode("utf-8")
        _write_report_pair(args.output_prefix, json_body, markdown_body)
        print(json.dumps({"database": identity, "summary": report["summary"], "output_prefix": str(args.output_prefix)}, ensure_ascii=False))
        return 0 if report["summary"]["scoring_allowed"] else 2
    except Exception as exc:
        # Connection exceptions may contain DSNs or passwords. Never echo exception text.
        print(f"只读审计失败 ({type(exc).__name__})；检查连接、输入格式和权限。未执行数据库修复。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
