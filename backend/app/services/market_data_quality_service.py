"""Offline, read-only market-data audit. Does not import app.database or providers."""
from __future__ import annotations

import csv
import copy
import hashlib
import io
import math
import numbers
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from app.services.market_universe_evidence_service import (
    DENOMINATOR_BASIS, MARKETS, WARNING, normalized_universe_digest,
    validate_evidence_manifest, validate_https_url, validated_dates,
)

VERSION = "market-data-quality-v1.1.0"
CORE = ("open", "high", "low", "close", "pre_close", "pct_chg")
FIELDS = CORE + ("vol", "amount", "turnover_rate")
CODE = re.compile(r"^(?:(?:600|601|603|605|688|689)\d{3}\.SH|(?:000|001|002|003|300|301|302)\d{3}\.SZ|(?:43|83|87|88|92)\d{4}\.BJ)$")


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
    path = Path(path)
    body = path.read_bytes()
    try:
        reader = csv.reader(io.StringIO(body.decode("utf-8-sig"), newline=""), strict=True)
        headers = next(reader, None)
        if not headers or any(not field.strip() for field in headers) or len(set(headers)) != len(headers):
            raise ValueError("CSV header必须非空且唯一")
        if not required.issubset(headers):
            raise ValueError("CSV 缺少字段: " + ",".join(sorted(required)))
        rows = []
        for line, values in enumerate(reader, 2):
            if len(values) != len(headers):
                raise ValueError(f"CSV第{line}行字段数量与header不符")
            rows.append(dict(zip(headers, values)))
    except (csv.Error, UnicodeError):
        raise ValueError("CSV编码或结构无效") from None
    return rows, {"file": str(path.resolve()), "sha256": hashlib.sha256(body).hexdigest()}


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


def _canonical_share(code):
    return isinstance(code, str) and code.isascii() and CODE.fullmatch(code) is not None


def _validate_universe_grid(universe, dates):
    if not isinstance(universe, dict):
        raise ValueError("证券grid必须为逐日期集合")
    if universe and set(universe) != set(dates):
        raise ValueError("证券grid日期必须与audit请求严格一致")
    for day, codes in universe.items():
        if not isinstance(codes, (set, frozenset)) or not codes or any(not _canonical_share(code) for code in codes):
            raise ValueError("证券grid必须包含非空规范A股代码集合")


def load_universe(path: Path | None, dates: list[str], counts_file: Path | None = None, *,
                  evidence_manifest: Path | None = None, evidence_sha256: str | None = None):
    dates = validated_dates(dates)
    if (evidence_manifest is None) != (evidence_sha256 is None):
        raise ValueError("manifest与pinned SHA256必须同时提供")
    if path is None:
        if counts_file is not None or evidence_manifest is not None:
            raise ValueError("控制总数/证据包必须搭配证券清单")
        return {}, {"status": "unavailable", "counts_match": False, "control_totals_verified": False,
                    "universe_digest": normalized_universe_digest({}),
                    "evidence": {"status": "not_provided", "scope": None, "bound": False,
                                 "inputs_bound": False, "originals_verified": False},
                    "warning": "缺少历史证券类型、上市/退市及全天停牌状态；" + WARNING}
    if evidence_manifest is not None and counts_file is None:
        raise ValueError("证据包必须绑定证券清单和控制总数")
    required = {"trade_date", "ts_code", "security_type", "is_listed", "is_trading"}
    rows, provenance = read_csv(path, required)
    universe = {day: set() for day in dates}
    seen = set()
    markets = set()
    for row in rows:
        day = validated_dates([row["trade_date"]])[0]
        code, kind = row["ts_code"], row["security_type"]
        if not re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", code):
            raise ValueError("证券代码必须为规范六位代码.exchange")
        if kind not in {"a_share", "index", "fund", "bond", "other"}:
            raise ValueError("security_type不属于已知枚举")
        if kind == "a_share" and not _canonical_share(code):
            raise ValueError("a_share代码与市场不匹配")
        markets.add(code.rsplit(".", 1)[1])
        key = (day, row["ts_code"])
        if key in seen or row["is_listed"] not in ("0", "1") or row["is_trading"] not in ("0", "1"):
            raise ValueError("证券池重复或状态未知；不能计算精确分母")
        if row["is_trading"] == "1" and row["is_listed"] != "1":
            raise ValueError("未上市证券不能标记为交易中")
        seen.add(key)
        if day in universe and row["security_type"] == "a_share" and row["is_listed"] == row["is_trading"] == "1":
            universe[day].add(row["ts_code"])
    # A complete file must contain securities for every audited open session.
    if any(not values for values in universe.values()):
        raise ValueError("证券池未覆盖所有待检查日期或分母为零")
    controls = None
    counts_match = False
    if counts_file:
        control_rows, controls = read_csv(counts_file, {"trade_date", "expected_count", "source_url"})
        counts = {}
        for row in control_rows:
            day = validated_dates([row["trade_date"]])[0]
            if day in counts or not re.fullmatch(r"[0-9]+", row["expected_count"]):
                raise ValueError("证券分母控制总数重复或格式不合法")
            validate_https_url(row["source_url"])
            counts[day] = int(row["expected_count"])
        if any(counts.get(d) != len(u) for d, u in universe.items()):
            raise ValueError("证券清单与独立预期交易证券总数不匹配")
        controls["sources"] = sorted({r["source_url"] for r in control_rows})
        controls["requested_counts"] = {day: counts[day] for day in dates}
        counts_match = True
    universe_digest = normalized_universe_digest(universe)
    evidence = {"status": "not_provided", "scope": None, "bound": False, "inputs_bound": False,
                "originals_verified": False, "universe_digest": universe_digest}
    if evidence_manifest is not None:
        evidence = validate_evidence_manifest(evidence_manifest, evidence_sha256, dates=dates, markets=markets,
            universe_sha256=provenance["sha256"], counts_sha256=controls["sha256"],
            universe_digest=universe_digest, control_urls=controls["sources"])
    qualified = counts_match is True and evidence["bound"] is True and evidence["scope"] == "full_market_point_in_time"
    status = ("evidence_bound_full_market" if qualified else "evidence_bound_security_subset" if evidence["bound"]
              else "diagnostic_counts_matched" if counts_match else "diagnostic_universe_only")
    return universe, {"status": status, **provenance, "counts_match": counts_match,
                      "control_totals_verified": qualified, "controls": controls,
                      "universe_digest": universe_digest, "evidence": evidence, "warning": WARNING}


def _current_counts_match(info, universe):
    controls = info.get("controls")
    if not universe or not isinstance(controls, dict) or info.get("counts_match") is not True:
        return False
    expected_counts = controls.get("requested_counts")
    if not isinstance(expected_counts, dict) or set(expected_counts) != set(universe):
        return False
    return all(type(expected_counts[day]) is int and expected_counts[day] == len(codes)
               for day, codes in universe.items())


def _evidence_binds_current_universe(info, universe, counts_match):
    evidence, controls = info.get("evidence"), info.get("controls")
    if not counts_match or not isinstance(evidence, dict) or not isinstance(controls, dict):
        return False
    markets = evidence.get("markets")
    if (not isinstance(markets, list) or not markets or any(not isinstance(m, str) for m in markets)
            or len(set(markets)) != len(markets) or not set(markets) <= MARKETS):
        return False
    try:
        manifest_dates = validated_dates(evidence.get("manifest_dates"))
    except (TypeError, ValueError):
        return False
    actual_markets = {code.rsplit(".", 1)[1] for codes in universe.values() for code in codes}
    scope = evidence.get("scope")
    if (scope not in ("full_market_point_in_time", "security_subset") or not actual_markets <= set(markets)
            or (scope == "full_market_point_in_time" and set(markets) != MARKETS)):
        return False
    return (all(evidence.get(flag) is True for flag in ("bound", "inputs_bound", "originals_verified"))
        and evidence.get("status") == "bound"
        and evidence.get("temporal_basis") == "retrospective" and evidence.get("denominator_basis") == DENOMINATOR_BASIS
        and evidence.get("audit_dates") == sorted(universe) and set(universe) <= set(manifest_dates)
        and isinstance(evidence.get("manifest_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", evidence["manifest_sha256"]) is not None
        and info.get("universe_digest") == evidence.get("universe_digest") == normalized_universe_digest(universe)
        and evidence.get("universe_sha256") == info.get("sha256")
        and isinstance(info.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", info["sha256"]) is not None
        and evidence.get("counts_sha256") == controls.get("sha256")
        and isinstance(controls.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", controls["sha256"]) is not None)


def _effective_universe_info(info, universe):
    """Report current binding separately from the caller's input claims.

    This rechecks the loaded proof's scope, not the original files; provenance
    remains a snapshot. Never mutate metadata that a caller may reuse.
    """
    result = copy.deepcopy(info)
    original_evidence = info.get("evidence") if isinstance(info.get("evidence"), dict) else {}
    result["input_claims"] = {key: copy.deepcopy(info.get(key)) for key in
                              ("status", "counts_match", "control_totals_verified", "universe_digest")}
    result["input_claims"]["evidence"] = {key: copy.deepcopy(original_evidence.get(key)) for key in
        ("status", "scope", "bound", "inputs_bound", "originals_verified", "universe_digest", "audit_dates")}
    counts_match = _current_counts_match(info, universe)
    bound = _evidence_binds_current_universe(info, universe, counts_match)
    qualified = (bound and info.get("control_totals_verified") is True
                 and original_evidence.get("scope") == "full_market_point_in_time")
    evidence = copy.deepcopy(original_evidence)
    evidence.update(bound=bound, inputs_bound=bound,
        originals_verified=original_evidence.get("originals_verified") is True,
        universe_digest=normalized_universe_digest(universe), audit_dates=sorted(universe))
    evidence["status"] = ("bound" if bound else "not_provided" if
        not original_evidence or original_evidence.get("status") == "not_provided" else "binding_mismatch")
    result.update(evidence=evidence, counts_match=counts_match, control_totals_verified=qualified,
                  universe_digest=normalized_universe_digest(universe))
    result["status"] = ("evidence_bound_full_market" if qualified else
        "evidence_bound_security_subset" if bound and evidence.get("scope") == "security_subset" else
        "evidence_bound_unqualified" if bound else "diagnostic_counts_matched" if counts_match else
        "diagnostic_universe_only" if universe else "unavailable")
    return result


def _audit_number(value):
    # Deliberately separate from the legacy repair/source finite/valid_field API.
    if isinstance(value, bool) or not isinstance(value, (str, numbers.Number)):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _audit_valid_field(name, value):
    value = _audit_number(value)
    return value is not None and (value > 0 if name in CORE[:-1] else name == "pct_chg" or value >= 0)


def audit_database(conn, *, dates, calendar, universe=None, universe_info=None, detail_days=20):
    """Produce JSON-safe evidence; missing denominators always remain null."""
    if type(detail_days) is not int or detail_days < 1:
        raise ValueError("日期不能为空且 detail_days 必须大于 0")
    dates = validated_dates(dates)
    universe = {} if universe is None else universe
    _validate_universe_grid(universe, dates)
    universe_info = {"status": "unavailable"} if universe_info is None else universe_info
    if not isinstance(universe_info, dict):
        raise ValueError("证券资格metadata必须为对象")
    universe_info = _effective_universe_info(universe_info, universe)
    universe_ok = universe_info["control_totals_verified"]
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
        candidates = {c for c, b in basic_by_code.items() if _canonical_share(c)
                      and b.get("list_status") in (None, "", "L")
                      and (not b.get("list_date") or not re.fullmatch(r"\d{8}", str(b["list_date"]))
                           or b["list_date"] <= day)}
        expected = universe.get(day)
        heuristic = expected is None
        observed = {r["ts_code"] for r in rows}
        # Even incomplete master metadata must not hide observed price/amount defects.
        canonical_observed = {c for c in observed if _canonical_share(c)}
        scope = candidates | canonical_observed if heuristic else expected
        unexpected_a_shares = sorted(c for c in observed - scope if _canonical_share(c))
        scoped = [r for r in rows if r["ts_code"] in scope]
        issues = []
        valid_codes = set()
        field_ok = Counter()
        consistency = Counter({"pct_checked_rows": 0, "pct_inconsistent_rows": 0,
            "amount_checked_rows": 0, "amount_uncheckable_rows": 0,
            "zero_pair_mismatch_rows": 0, "vwap_out_of_range_rows": 0,
            "amount_inconsistent_rows": 0})
        anomaly_codes = set()
        for row in scoped:
            values = {field: _audit_number(row.get(field)) for field in FIELDS}
            bad = [f for f in CORE if not _audit_valid_field(f, row.get(f))]
            for name in FIELDS:
                field_ok[name] += int(_audit_valid_field(name, row.get(name)))
            if not bad:
                if values["low"] > min(values["open"], values["close"]) or values["high"] < max(values["open"], values["close"]) or values["high"] < values["low"]:
                    bad.append("ohlc_order")
                consistency["pct_checked_rows"] += 1
                expected_pct = (values["close"] - values["pre_close"]) / values["pre_close"] * 100
                if not math.isfinite(expected_pct) or abs(values["pct_chg"] - expected_pct) > .03:
                    bad.append("pct_consistency")
                    consistency["pct_inconsistent_rows"] += 1
            for name in ("vol", "amount", "turnover_rate"):
                if row.get(name) is not None and not _audit_valid_field(name, row.get(name)):
                    bad.append(name)
            if counts[row["ts_code"]] > 1:
                bad.append("duplicate_key")
            if bad:
                anomaly_codes.add(row["ts_code"])
            # New amount consistency diagnostics do not redefine the existing
            # price/coverage scoring gate. They have their own absolute veto.
            price_checkable = all(_audit_valid_field(field, row.get(field)) for field in ("open", "high", "low", "close"))
            if price_checkable:
                price_checkable = (values["low"] <= min(values["open"], values["close"])
                                   <= max(values["open"], values["close"]) <= values["high"])
            quantity_checkable = all(_audit_valid_field(field, row.get(field)) for field in ("vol", "amount"))
            zero_mismatch = quantity_checkable and ((values["vol"] == 0) != (values["amount"] == 0))
            if zero_mismatch:
                bad.append("volume_amount_zero_mismatch")
                consistency["zero_pair_mismatch_rows"] += 1
                consistency["amount_inconsistent_rows"] += 1
            if price_checkable and quantity_checkable:
                consistency["amount_checked_rows"] += 1
                if not zero_mismatch and values["vol"] > 0:
                    average = values["amount"] * 10 / values["vol"]
                    tolerance = max(1e-8, max(abs(values["low"]), abs(values["high"])) * 1e-9)
                    if not math.isfinite(average) or not values["low"] - tolerance <= average <= values["high"] + tolerance:
                        bad.append("vwap_out_of_range")
                        consistency["vwap_out_of_range_rows"] += 1
                        consistency["amount_inconsistent_rows"] += 1
            else:
                consistency["amount_uncheckable_rows"] += 1
            if bad:
                issues.append({"ts_code": row["ts_code"], "issues": bad})
            if not any(f in bad for f in (*CORE, "ohlc_order", "pct_consistency", "duplicate_key")):
                valid_codes.add(row["ts_code"])
        ratio = len(valid_codes) / len(expected) if expected else None
        fields = {f: {"valid": field_ok[f], "total": len(scoped),
                      "ratio": field_ok[f] / len(scoped) if scoped else None} for f in FIELDS}
        calendar_ok = calendar["status"] == "provided_calendar"
        coverage_ok = ratio is not None and ratio >= .95
        core_ok = all(fields[f]["ratio"] is not None and fields[f]["ratio"] >= .99 for f in CORE)
        anomaly_ratio = (len(anomaly_codes) + len(unexpected_a_shares)) / max(len(canonical_observed), 1)
        clean = anomaly_ratio <= .001 and not unexpected_a_shares
        gate = calendar_ok and universe_ok and coverage_ok and core_ok and clean
        consistency["amount_checkable_ratio"] = consistency["amount_checked_rows"] / len(scoped) if scoped else None
        amount_allowed = bool(gate and fields["amount"]["ratio"] is not None and fields["amount"]["ratio"] >= .95
            and consistency["amount_checkable_ratio"] is not None and consistency["amount_checkable_ratio"] >= .95
            and consistency["amount_inconsistent_rows"] == 0)
        row_result = {"trade_date": day, "raw_rows": len(rows), "scoped_rows": len(scoped),
                      "valid_core_codes": len(valid_codes), "duplicate_codes": sum(n > 1 for n in counts.values()),
                      "expected_count": len(expected) if expected else None,
                      "coverage_ratio": ratio, "diagnostic_candidate_count": len(candidates),
                      "diagnostic_observed_ratio": len(observed & candidates) / len(candidates) if candidates else None,
                      "missing_count": len(scope - observed), "invalid_core_count": len((observed & scope) - valid_codes),
                      "unexpected_a_share_codes": unexpected_a_shares, "anomaly_ratio": anomaly_ratio,
                      "fields": fields, "consistency": dict(consistency), "quality_status": "pass" if gate else
                      "unverifiable" if not calendar_ok or heuristic or not universe_ok else "fail",
                      "scoring_allowed": gate,
                      "amount_metrics_allowed": amount_allowed,
                      "coverage_basis": "evidence_bound_full_market" if universe_ok else "current_master_proxy" if heuristic else "provided_universe_diagnostic",
                      "missing_list_basis": "current_master_proxy" if heuristic else "provided_point_in_time_universe" if universe_ok else "provided_universe_diagnostic"}
        if day in detailed:
            row_result.update(missing_codes=sorted(scope - observed), invalid_rows=issues,
                              out_of_scope_codes=sorted(observed - scope),
                              unknown_master_codes=sorted(observed - basic_by_code.keys()),
                              missing_field_codes={f: sorted({r["ts_code"] for r in scoped if not _audit_valid_field(f, r.get(f))}) for f in FIELDS})
        day_results.append(row_result)
    scoring_allowed = all(r["scoring_allowed"] for r in day_results) and not unexpected and not invalid_dates
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
                        "scoring_allowed": scoring_allowed,
                        "amount_metrics_allowed": scoring_allowed and all(r["amount_metrics_allowed"] for r in day_results)},
            "limitations": ["无网络采集，无数据库写入；报告为文件快照。",
                "当前主数据代理不能恢复退市、停牌或历史证券类型；代理比例不是市场覆盖率。",
                "字段完整不代表量额单位一致或盘后正式数据；本工具不推断供应商血缘。",
                "scoring_allowed为覆盖/核心价格门槛；amount_metrics_allowed另需量额数值完整、一致且可检查比例至少95%。",
                WARNING]}


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
             f"- 清单与控制数值匹配（counts_match）：`{report['universe'].get('counts_match') is True}`；全市场证据资格：`{report['universe'].get('control_totals_verified') is True}`",
             f"- 证据绑定：`{report['universe'].get('evidence', {}).get('bound') is True}`；范围：`{report['universe'].get('evidence', {}).get('scope') or '未提供'}`",
             f"- 覆盖与核心字段门槛：{'通过' if report['summary']['scoring_allowed'] else '不通过/证据不足，禁止据此启用评分'}",
             f"- 金额指标门槛（amount_metrics_allowed）：`{report['summary']['amount_metrics_allowed']}`", "",
             ("使用显式提供的离线交易日历，包含整日无行情的交易日；日历文件和哈希见 JSON。" if report["calendar"]["status"] == "provided_calendar" else
              "缺少日历，下表是工作日诊断网格，可能包含休市日；不将整日无数据自动定性为漏采。"), "",
             "清单比例仅针对所提供的集合；数值吻合及哈希绑定均不认证来源权威性、实际独立性或真实全市场完整性。", "",
             "| 日期 | 原始行 | 核心有效代码 | 清单分母 | 清单覆盖比例 | 当前主数据代理比例 | 成交额数值有效率 | 金额门槛 | 质量 |",
             "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for row in report["days"]:
        lines.append(f"| {row['trade_date']} | {row['raw_rows']} | {row['valid_core_codes']} | {row['expected_count'] if row['expected_count'] is not None else '未知'} | {pct(row['coverage_ratio'])} | {pct(row['diagnostic_observed_ratio'])} | {pct(row['fields']['amount']['ratio'])} | {row['amount_metrics_allowed']} | {row['quality_status']} |")
    lines += ["", "## 最近窗口明细", "", "完整缺失代码、异常代码、逐字段问题见同名 JSON 的 days；以下为明细日期统计。", "",
              "| 日期 | 缺失（按所示口径） | 核心异常 | 成交量有效率 | 换手率有效率 | 量额可检查率 | 量额矛盾行 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in report["days"]:
        if "missing_codes" in row:
            lines.append(f"| {row['trade_date']} | {row['missing_count']} ({row['missing_list_basis']}) | {row['invalid_core_count']} | {pct(row['fields']['vol']['ratio'])} | {pct(row['fields']['turnover_rate']['ratio'])} | {pct(row['consistency']['amount_checkable_ratio'])} | {row['consistency']['amount_inconsistent_rows']} |")
    lines += ["", "## 限制", ""] + ["- " + v for v in report["limitations"]]
    return "\n".join(lines) + "\n"
