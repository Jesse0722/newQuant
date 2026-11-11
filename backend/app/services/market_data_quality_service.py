"""Offline, read-only market-data audit. Does not import app.database or providers."""
from __future__ import annotations

import csv
import hashlib
import math
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

VERSION = "market-data-quality-v1.0.0"
CORE = ("open", "high", "low", "close", "pre_close", "pct_chg")
FIELDS = CORE + ("vol", "amount", "turnover_rate")
CODE = re.compile(r"^(?:(?:600|601|603|605|688|689)\d{3}\.SH|(?:000|001|002|003|300|301)\d{3}\.SZ|(?:43|83|87|88|92)\d{4}\.BJ)$")


def parse_date(value: str) -> str:
    if not re.fullmatch(r"\d{8}", value):
        raise ValueError("日期必须为 YYYYMMDD")
    datetime.strptime(value, "%Y%m%d")
    return value


def finite(value) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (ValueError, TypeError, OverflowError):
        return False


def valid_field(name, value):
    if not finite(value):
        return False
    return float(value) > 0 if name in CORE[:-1] else (name == "pct_chg" or float(value) >= 0)


@contextmanager
def readonly_connection(database_url: str, app_cwd: Path):
    """Enforce read-only at DB level, including SQLite's existing-file requirement."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        if not url.database or url.database == ":memory:" or url.query:
            raise ValueError("只接受已有 SQLite 文件，不接受内存库或 URL query")
        path = Path(url.database)
        path = (app_cwd / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_file():
            raise ValueError("SQLite 文件不存在（不会自动建库）")
        engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=15), poolclass=NullPool)
        identity = {"backend": "sqlite", "database": str(path), "app_cwd": str(app_cwd.resolve())}
    elif url.get_backend_name() == "postgresql":
        engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 8},
                               isolation_level="REPEATABLE READ")
        identity = {"backend": "postgresql", "host": url.host, "port": url.port,
                    "database": url.database}
    else:
        raise ValueError("只支持 SQLite 和 PostgreSQL")
    try:
        with engine.connect() as conn:
            if identity["backend"] == "sqlite":
                conn.exec_driver_sql("PRAGMA query_only=ON")
                # Explicit BEGIN: sqlite legacy mode otherwise does not snapshot SELECTs.
                conn.exec_driver_sql("BEGIN")
            else:
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql("SET LOCAL statement_timeout = '60s'")
            try:
                yield conn, identity
            finally:
                conn.rollback()
    finally:
        engine.dispose()


def read_csv(path: Path, required: set[str]):
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV 缺少字段: " + ",".join(sorted(required)))
        rows = list(reader)
    return rows, {"file": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def audit_dates(end_date: str, days: int, calendar_file: Path | None = None):
    parse_date(end_date)
    if days < 1:
        raise ValueError("days 必须大于 0")
    if calendar_file:
        rows, provenance = read_csv(calendar_file, {"trade_date", "is_open"})
        calendar = {}
        for row in rows:
            day = parse_date(row["trade_date"])
            if day in calendar or row["is_open"] not in ("0", "1"):
                raise ValueError("交易日历重复日期或非法 is_open")
            calendar[day] = row["is_open"] == "1"
        # Require every calendar day, so missing sessions cannot disappear silently.
        if end_date not in calendar:
            raise ValueError("日历未覆盖截止日期")
        selected = []
        day = datetime.strptime(end_date, "%Y%m%d")
        while len(selected) < days:
            key = day.strftime("%Y%m%d")
            if key not in calendar:
                raise ValueError("日历范围不足或不连续: " + key)
            if calendar[key]:
                selected.append(key)
            day -= timedelta(days=1)
        return sorted(selected), {"status": "provided_calendar", **provenance}
    result = []
    day = datetime.strptime(end_date, "%Y%m%d")
    while len(result) < days:
        if day.weekday() < 5:
            result.append(day.strftime("%Y%m%d"))
        day -= timedelta(days=1)
    return sorted(result), {"status": "unverified_weekday_grid", "warning":
        "缺少独立交易日历；使用工作日诊断网格，包含节假日，不能称为最近 N 个交易日"}


def load_universe(path: Path | None, dates: list[str], counts_file: Path | None = None):
    if path is None:
        return {}, {"status": "unavailable", "warning": "缺少历史证券类型、上市/退市及全天停牌状态"}
    required = {"trade_date", "ts_code", "security_type", "is_listed", "is_trading"}
    rows, provenance = read_csv(path, required)
    universe = {day: set() for day in dates}
    seen = set()
    for row in rows:
        day = parse_date(row["trade_date"])
        key = (day, row["ts_code"])
        if key in seen or row["is_listed"] not in ("0", "1") or row["is_trading"] not in ("0", "1"):
            raise ValueError("证券池重复或状态未知；不能计算精确分母")
        seen.add(key)
        if day in universe and row["security_type"] == "a_share" and row["is_listed"] == row["is_trading"] == "1":
            universe[day].add(row["ts_code"])
    # A complete file must contain securities for every audited open session.
    if any(not values for values in universe.values()):
        raise ValueError("证券池未覆盖所有待检查日期或分母为零")
    controls = None
    if counts_file:
        control_rows, controls = read_csv(counts_file, {"trade_date", "expected_count", "source_url"})
        counts = {}
        for row in control_rows:
            day = parse_date(row["trade_date"])
            if day in counts or not row["expected_count"].isdigit() or not row["source_url"].startswith("https://"):
                raise ValueError("证券分母控制总数重复或格式不合法")
            counts[day] = int(row["expected_count"])
        if any(counts.get(d) != len(u) for d, u in universe.items()):
            raise ValueError("证券清单与独立预期交易证券总数不匹配")
        controls["sources"] = sorted({r["source_url"] for r in control_rows})
    return universe, {"status": "provided_universe_with_controls" if controls else "unverified_provided_universe",
                      **provenance, "control_totals_verified": controls is not None, "controls": controls,
                      "warning": "控制总数须来自独立权威主数据；哈希/数量核对不认证供应商原始数据真实性"}


def audit_database(conn, *, dates, calendar, universe=None, universe_info=None, detail_days=20):
    """Produce JSON-safe evidence; missing denominators always remain null."""
    if not dates or detail_days < 1:
        raise ValueError("日期不能为空且 detail_days 必须大于 0")
    dates = sorted(set(parse_date(d) for d in dates))
    universe = universe or {}
    universe_info = universe_info or {"status": "unavailable"}
    metadata = MetaData()
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    if not {"daily_quote", "stock_basic"}.issubset(tables):
        raise ValueError("缺少 daily_quote 或 stock_basic 表")
    quotes = Table("daily_quote", metadata, autoload_with=conn)
    basics = Table("stock_basic", metadata, autoload_with=conn)
    if not {"ts_code", "trade_date"}.issubset(quotes.c.keys()):
        raise ValueError("行情表缺少代码/日期字段")
    basic_rows = [dict(r) for r in conn.execute(select(basics)).mappings()]
    basic_by_code = {r["ts_code"]: r for r in basic_rows}
    total, first, latest = conn.execute(select(func.count(), func.min(quotes.c.trade_date),
                                              func.max(quotes.c.trade_date))).one()
    invalid_dates = []
    for value, count in conn.execute(select(quotes.c.trade_date, func.count()).group_by(quotes.c.trade_date)):
        try:
            parse_date(value)
        except (TypeError, ValueError):
            invalid_dates.append({"trade_date": value, "rows": count})
    detailed = set(dates[-detail_days:])
    day_results = []
    excluded = sorted(c for c in basic_by_code if not CODE.fullmatch(c))
    requested = set(dates)
    # Also audit unexpected rows in the window; do not hide malformed session dates.
    unexpected = []
    for day, count in conn.execute(select(quotes.c.trade_date, func.count()).where(
            quotes.c.trade_date >= dates[0], quotes.c.trade_date <= dates[-1]).group_by(quotes.c.trade_date)):
        if day not in requested:
            unexpected.append({"trade_date": day, "rows": count})
    for day in dates:
        rows = list(conn.execute(select(quotes).where(quotes.c.trade_date == day)).mappings())
        counts = Counter(r["ts_code"] for r in rows)
        candidates = {c for c, b in basic_by_code.items() if CODE.fullmatch(c)
                      and b.get("list_status") in (None, "", "L")
                      and (not b.get("list_date") or not re.fullmatch(r"\d{8}", str(b["list_date"]))
                           or b["list_date"] <= day)}
        expected = universe.get(day)
        heuristic = expected is None
        observed = {r["ts_code"] for r in rows}
        # Even incomplete master metadata must not hide observed price/amount defects.
        scope = candidates | {c for c in observed if CODE.fullmatch(c)} if heuristic else expected
        unexpected_a_shares = sorted(c for c in observed - scope if CODE.fullmatch(c))
        scoped = [r for r in rows if r["ts_code"] in scope]
        issues = []
        valid_codes = set()
        field_ok = Counter()
        for row in scoped:
            bad = [f for f in CORE if not valid_field(f, row.get(f))]
            for name in FIELDS:
                field_ok[name] += int(valid_field(name, row.get(name)))
            if not bad:
                if row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]) or row["high"] < row["low"]:
                    bad.append("ohlc_order")
            for name in ("vol", "amount", "turnover_rate"):
                if row.get(name) is not None and not valid_field(name, row.get(name)):
                    bad.append(name)
            if counts[row["ts_code"]] > 1:
                bad.append("duplicate_key")
            if bad:
                issues.append({"ts_code": row["ts_code"], "issues": bad})
            if not any(f in bad for f in (*CORE, "ohlc_order", "duplicate_key")):
                valid_codes.add(row["ts_code"])
        ratio = len(valid_codes) / len(expected) if expected else None
        fields = {f: {"valid": field_ok[f], "total": len(scoped),
                      "ratio": field_ok[f] / len(scoped) if scoped else None} for f in FIELDS}
        calendar_ok = calendar["status"] == "provided_calendar"
        universe_ok = bool(universe_info.get("control_totals_verified"))
        coverage_ok = ratio is not None and ratio >= .95
        core_ok = all(fields[f]["ratio"] is not None and fields[f]["ratio"] >= .99 for f in CORE)
        anomaly_ratio = (len({r["ts_code"] for r in issues}) + len(unexpected_a_shares)) / max(len(observed), 1)
        clean = anomaly_ratio <= .001 and not unexpected_a_shares
        gate = calendar_ok and universe_ok and coverage_ok and core_ok and clean
        row_result = {"trade_date": day, "raw_rows": len(rows), "scoped_rows": len(scoped),
                      "valid_core_codes": len(valid_codes), "duplicate_codes": sum(n > 1 for n in counts.values()),
                      "expected_count": len(expected) if expected else None,
                      "coverage_ratio": ratio, "diagnostic_candidate_count": len(candidates),
                      "diagnostic_observed_ratio": len(observed & candidates) / len(candidates) if candidates else None,
                      "missing_count": len(scope - observed), "invalid_core_count": len((observed & scope) - valid_codes),
                      "unexpected_a_share_codes": unexpected_a_shares, "anomaly_ratio": anomaly_ratio,
                      "fields": fields, "quality_status": "pass" if gate else
                      "unverifiable" if not calendar_ok or heuristic or not universe_ok else "fail",
                      "scoring_allowed": gate,
                      "amount_metrics_allowed": bool(gate and fields["amount"]["ratio"] is not None and fields["amount"]["ratio"] >= .95),
                      "missing_list_basis": "current_master_proxy" if heuristic else "provided_point_in_time_universe"}
        if day in detailed:
            row_result.update(missing_codes=sorted(scope - observed), invalid_rows=issues,
                              out_of_scope_codes=sorted(observed - scope),
                              unknown_master_codes=sorted(observed - basic_by_code.keys()),
                              missing_field_codes={f: sorted({r["ts_code"] for r in scoped if not valid_field(f, r.get(f))}) for f in FIELDS})
        day_results.append(row_result)
    return {"version": VERSION, "quote_inventory": {"total_rows": total, "first_date": first, "latest_date": latest},
            "master_inventory": {"rows": len(basic_rows), "code_pattern_excluded": excluded,
                                 "missing_list_status": sum(not r.get("list_status") for r in basic_rows),
                                 "missing_list_date": sum(not r.get("list_date") for r in basic_rows),
                                 "classification": "代码规则仅供诊断，不是证券类型认证"},
            "calendar": calendar, "universe": universe_info, "days": day_results,
            "unexpected_session_rows": unexpected, "invalid_date_rows": invalid_dates,
            "missing_schema_fields": sorted(set(FIELDS) - set(quotes.c.keys())),
            "summary": {"requested_days": len(dates), "detail_days": min(detail_days, len(dates)),
                        "empty_slots": sum(r["raw_rows"] == 0 for r in day_results),
                        "verified_pass_days": sum(r["quality_status"] == "pass" for r in day_results),
                        "scoring_allowed": all(r["scoring_allowed"] for r in day_results) and not unexpected and not invalid_dates},
            "limitations": ["无网络采集，无数据库写入；报告为文件快照。",
                "当前主数据代理不能恢复退市、停牌或历史证券类型；代理比例不是市场覆盖率。",
                "字段完整不代表量额单位一致或盘后正式数据；本工具不推断供应商血缘。",
                "scoring_allowed 仅为覆盖/核心字段门槛，不替代未来模块的全套质量检查。"]}


def render_markdown(report):
    def pct(value):
        return "不可验证" if value is None else f"{value:.1%}"
    inv = report["quote_inventory"]
    identity = report["database"]
    window = report["days"]
    lines = ["# 全市场日线只读质量报告", "", f"- 生成时间：{report['generated_at']}",
             f"- 检查范围：{window[0]['trade_date']} — {window[-1]['trade_date']}，{len(window)} 个日期",
             f"- 数据库：`{identity}`", f"- 配置来源：{report['configuration_source']}",
             f"- 行情总数：{inv['total_rows']:,}；范围：{inv['first_date']} — {inv['latest_date']}",
             f"- 日历：`{report['calendar']['status']}`；证券池：`{report['universe']['status']}`",
             f"- 覆盖与核心字段门槛：{'通过' if report['summary']['scoring_allowed'] else '不通过/证据不足，禁止据此启用评分'}", "",
             ("使用显式提供的离线交易日历，包含整日无行情的交易日；日历文件和哈希见 JSON。" if report["calendar"]["status"] == "provided_calendar" else
              "缺少日历，下表是工作日诊断网格，可能包含休市日；不将整日无数据自动定性为漏采。"), "",
             "| 日期 | 原始行 | 核心有效代码 | 真实分母 | 真实覆盖率 | 当前主数据代理比例 | 成交额有效率 | 质量 |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for row in report["days"]:
        lines.append(f"| {row['trade_date']} | {row['raw_rows']} | {row['valid_core_codes']} | {row['expected_count'] if row['expected_count'] is not None else '未知'} | {pct(row['coverage_ratio'])} | {pct(row['diagnostic_observed_ratio'])} | {pct(row['fields']['amount']['ratio'])} | {row['quality_status']} |")
    lines += ["", "## 最近窗口明细", "", "完整缺失代码、异常代码、逐字段问题见同名 JSON 的 days；以下为明细日期统计。", "",
              "| 日期 | 缺失（按所示口径） | 核心异常 | 成交量有效率 | 换手率有效率 |", "|---|---:|---:|---:|---:|"]
    for row in report["days"]:
        if "missing_codes" in row:
            lines.append(f"| {row['trade_date']} | {row['missing_count']} ({row['missing_list_basis']}) | {row['invalid_core_count']} | {pct(row['fields']['vol']['ratio'])} | {pct(row['fields']['turnover_rate']['ratio'])} |")
    lines += ["", "## 限制", ""] + ["- " + v for v in report["limitations"]]
    return "\n".join(lines) + "\n"
