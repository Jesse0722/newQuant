"""Capability-based, insert-only full-market history collection.

The target list is a current-master proxy, never a historical market denominator.
Existing quotes are left to the separately audited T07/T08 repair workflow.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path
import time as clock

import pandas as pd

from app.models.stock import DailyQuote, StockBasic
from app.services.market_data_capabilities import configured_providers, provider_capabilities
from app.services.market_data_quality_service import CODE, CORE, audit_dates, finite, parse_date, valid_field
from app.services.trading_session import shanghai_datetime


def resolve_history_dates(provider, days=60, end_date=None, now=None):
    if not 1 <= days <= 250:
        raise ValueError("同步窗口必须为 1–250 个交易日")
    current = shanghai_datetime(now)
    cutoff = current if current.time() >= time(16) else current - timedelta(days=1)
    end = parse_date(end_date) if end_date else cutoff.strftime("%Y%m%d")
    if end > cutoff.strftime("%Y%m%d"):
        raise ValueError("截止日期尚未完成盘后数据窗口")
    local = Path(__file__).resolve().parents[2] / "data_reference" / f"sse_calendar_{end[:4]}.csv"
    if local.exists():
        try:
            dates, calendar = audit_dates(end, days, local)
            return dates, calendar
        except ValueError:
            pass  # The window can cross the local calendar's supported year.
    errors = []
    for source in configured_providers(provider):
        caps = provider_capabilities(source)
        if not caps.enabled:
            continue
        try:
            values = source.get_sse_open_dates(end, lookback_calendar_days=max(400, days * 3))
            dates = sorted({parse_date(d) for d in values if d <= end})
            if len(dates) >= days and (datetime.strptime(end, "%Y%m%d") - datetime.strptime(dates[-1], "%Y%m%d")).days <= 14:
                return dates[-days:], {"status": "provider_calendar", "source": caps.name}
            errors.append(caps.name + ":empty_or_stale")
        except Exception:
            errors.append(caps.name + ":failed")
    raise ValueError("无法取得完整交易日历；" + ",".join(errors))


def normalize_history(frame, caps, dates, codes):
    """Normalize only new history rows; reject wrong identities and broken OHLC."""
    rows, rejected = [], 0
    if frame is None or frame.empty:
        return rows, rejected
    for raw in frame.to_dict("records"):
        code, day = str(raw.get("ts_code", "")), str(raw.get("trade_date", ""))
        if code not in codes or day not in dates:
            rejected += 1
            continue
        if not all(valid_field(f, raw.get(f)) for f in CORE):
            rejected += 1
            continue
        row = {key: float(raw[key]) if finite(raw.get(key)) else None
               for key in ("open", "high", "low", "close", "pre_close", "pct_chg", "change", "vol", "amount", "turnover_rate")}
        if row["high"] < max(row["open"], row["close"]) or row["low"] > min(row["open"], row["close"]) or row["high"] < row["low"]:
            rejected += 1
            continue
        for field, unit, divisor in (("vol", caps.volume_unit, {"share": 100, "lot": 1}),
                                      ("amount", caps.amount_unit, {"cny": 1000, "thousand_cny": 1})):
            value = row[field]
            row[field] = value / divisor[unit] if value is not None and value >= 0 and unit in divisor else None
        row.update(ts_code=code, trade_date=day)
        rows.append(row)
    # Conflicting duplicate source keys are not silently selected.
    counts = Counter((r["ts_code"], r["trade_date"]) for r in rows)
    rejected += sum(n for n in counts.values() if n > 1)
    return [r for r in rows if counts[r["ts_code"], r["trade_date"]] == 1], rejected


def _insert_missing(db, rows):
    """One batch transaction. Any failure rolls back before the next request."""
    inserted, skipped = Counter(), Counter()
    try:
        for row in rows:
            key = (row["ts_code"], row["trade_date"])
            if db.get(DailyQuote, key) is not None:
                skipped[row["trade_date"]] += 1
            else:
                db.add(DailyQuote(**row))
                inserted[row["trade_date"]] += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return inserted, skipped


def collect_full_market_history(db, provider, dates, progress=None, request_interval=.15):
    sources = configured_providers(provider)  # Freeze router selection for this task.
    caps_by_source = [(source, provider_capabilities(source)) for source in sources]
    master = db.query(StockBasic).all()
    bootstrap_source = None
    if not any(CODE.fullmatch(s.ts_code) for s in master):
        # Preserve first-run full-market setup without overwriting current metadata.
        for source, caps in caps_by_source:
            if not caps.enabled or not callable(getattr(source, "get_stock_basic", None)):
                continue
            try:
                frame = source.get_stock_basic()
                if frame is None or frame.empty:
                    continue
                for basic_record in frame.to_dict("records"):
                    code = str(basic_record.get("ts_code", ""))
                    if not CODE.fullmatch(code) or db.get(StockBasic, code) is not None:
                        continue
                    db.add(StockBasic(ts_code=code, name=str(basic_record.get("name") or code),
                                      list_status="L"))
                db.commit()
                master = db.query(StockBasic).all()
                if any(CODE.fullmatch(s.ts_code) for s in master):
                    bootstrap_source = caps.name
                    break
            except Exception:
                db.rollback()
    codes_by_day = {d: {s.ts_code for s in master if CODE.fullmatch(s.ts_code)
                       and s.list_status in (None, "", "L")
                       and (not s.list_date or str(s.list_date) <= d)} for d in dates}
    if not any(codes_by_day.values()):
        raise ValueError("本地证券主数据没有可用目标；请先同步股票清单")
    daily = {d: {"trade_date": d, "requests": Counter(), "inserted": 0, "skipped": 0,
                 "invalid_rows": 0, "returned_sources": Counter(), "inserted_sources": Counter(),
                 "skipped_sources": Counter()} for d in dates}
    resolved_codes = {}
    for day in dates:
        existing = db.query(DailyQuote).filter(DailyQuote.trade_date == day,
                                              DailyQuote.ts_code.in_(codes_by_day[day])).all()
        resolved_codes[day] = {r.ts_code for r in existing}
        daily[day]["preexisting_count"] = len(existing)
        daily[day]["skipped"] = len(existing)
    attempts = Counter()
    examples = []
    direct_outcomes = {d: set() for d in dates}
    rejected_outside_request = 0

    def record(caps, method, status, target):
        attempts[caps.name + ":" + method + ":" + status] += 1
        if status != "success" and len(examples) < 50:
            examples.append({"source": caps.name, "method": method, "status": status, "target": target})

    def fetch(source, caps, method, target, requested_dates, requested_codes):
        nonlocal rejected_outside_request
        try:
            if request_interval > 0:
                clock.sleep(max(request_interval, 1.25) if caps.name == "tushare" else request_interval)
            if method == "by_date":
                frame = source.get_daily_by_date(target)
            else:
                kwargs = dict(ts_code=target, start_date=min(requested_dates), end_date=max(requested_dates))
                if type(source).__name__ == "AkshareAdapter":
                    kwargs["strict"] = True
                frame = source.get_daily(**kwargs)
            if frame is None or frame.empty:
                record(caps, method, "empty", target)
                return [], "empty", 0
            rows, rejected = normalize_history(frame, caps, requested_dates, requested_codes)
            # Attribute rejected rows to their actual requested date, not every day.
            valid_keys = {(r["ts_code"], r["trade_date"]) for r in rows}
            for raw in frame.to_dict("records"):
                day = str(raw.get("trade_date", ""))
                if day not in requested_dates:
                    rejected_outside_request += 1
                elif (str(raw.get("ts_code", "")), day) not in valid_keys:
                    daily[day]["invalid_rows"] += 1
            status = "success" if rows else "failed"
            record(caps, method, status, target)
            return rows, status, rejected
        except Exception:
            # Exception text can contain proxy URLs or credentials.
            record(caps, method, "failed", target)
            return [], "failed", 0

    remaining_dates = []
    for day_index, day in enumerate(dates):
        settled = resolved_codes[day] >= codes_by_day[day]
        for source, caps in caps_by_source:
            if settled:
                break
            if not (caps.enabled and caps.history_by_date):
                record(caps, "by_date", "unsupported", day)
                continue
            pending_codes = codes_by_day[day] - resolved_codes[day]
            rows, status, rejected = fetch(source, caps, "by_date", day, {day}, codes_by_day[day])
            direct_outcomes[day].add(status)
            daily[day]["returned_sources"][caps.name] += len(rows)
            rows = [r for r in rows if r["ts_code"] in pending_codes]
            if rows:
                try:
                    inserted, skipped = _insert_missing(db, rows)
                    daily[day]["inserted"] += inserted[day]
                    daily[day]["skipped"] += skipped[day]
                    daily[day]["inserted_sources"][caps.name] += inserted[day]
                    daily[day]["skipped_sources"][caps.name] += skipped[day]
                    daily[day]["requests"]["success"] += 1
                    resolved_codes[day].update(r["ts_code"] for r in rows)
                    settled = resolved_codes[day] >= codes_by_day[day]
                    if settled:
                        break
                except Exception:
                    record(caps, "write", "failed", day)
                    direct_outcomes[day].add("failed")
        if not settled:
            remaining_dates.append(day)
        if progress:
            progress(.1 * (day_index + 1) / len(dates), f"检查按日历史路径 {day}")

    targets = sorted(set().union(*(codes_by_day[d] - resolved_codes[d] for d in remaining_dates))) if remaining_dates else []
    for index, code in enumerate(targets):
        needed = {d for d in remaining_dates if code in codes_by_day[d] and code not in resolved_codes[d]}
        selected, source_for_day = {}, {}
        outcomes = set()
        for source, caps in caps_by_source:
            if not needed:
                break
            if not (caps.enabled and caps.history_by_symbol and caps.reliable_pre_close and code.rsplit(".", 1)[-1] in caps.markets):
                record(caps, "by_symbol", "unsupported", code)
                continue
            rows, status, rejected = fetch(source, caps, "by_symbol", code, needed, {code})
            outcomes.add(status)
            for row in rows:
                daily[row["trade_date"]]["returned_sources"][caps.name] += 1
                selected[row["trade_date"]] = row
                source_for_day[row["trade_date"]] = caps.name
            needed -= selected.keys()
        if selected:
            try:
                inserted, skipped = _insert_missing(db, list(selected.values()))
                for day in selected:
                    daily[day]["inserted"] += inserted[day]
                    daily[day]["skipped"] += skipped[day]
                    daily[day]["inserted_sources"][source_for_day[day]] += inserted[day]
                    daily[day]["skipped_sources"][source_for_day[day]] += skipped[day]
                    daily[day]["requests"]["success"] += 1
            except Exception:
                for day in selected:
                    daily[day]["requests"]["failed"] += 1
        unresolved_status = "failed" if "failed" in outcomes else "empty" if outcomes else "unsupported"
        for day in needed:
            daily[day]["requests"][unresolved_status] += 1
        if progress:
            progress(.1 + .9 * (index + 1) / max(len(targets), 1), f"历史回补 {code} ({index + 1}/{len(targets)})")

    for day, item in daily.items():
        stored = db.query(DailyQuote).filter(DailyQuote.trade_date == day,
                                            DailyQuote.ts_code.in_(codes_by_day[day])).all()
        core_valid = {r.ts_code for r in stored if all(valid_field(f, getattr(r, f)) for f in CORE)
                      and r.high >= max(r.open, r.close) and r.low <= min(r.open, r.close) and r.high >= r.low}
        item["target_count"] = len(codes_by_day[day])
        item["valid_core_count"] = len(core_valid)
        item["target_coverage_ratio"] = len(core_valid) / item["target_count"] if item["target_count"] else None
        item["market_coverage_ratio"] = None
        counts = item["requests"]
        if not counts["success"] and direct_outcomes[day]:
            counts["failed" if "failed" in direct_outcomes[day] else "empty"] += 1
        good = len(core_valid) > 0
        passed = (item["target_coverage_ratio"] or 0) >= .95
        item["source_quality_warning"] = bool(counts["failed"] or item["invalid_rows"] or counts["empty"] or counts["unsupported"])
        item["requires_existing_row_repair"] = item["preexisting_count"] > len(core_valid) - item["inserted"]
        item["status"] = "success" if passed else "partial" if good else "requires_repair" if item["requires_existing_row_repair"] else "failed" if counts["failed"] else "empty" if counts["empty"] else "unsupported"
        item["requests"] = dict(counts)
        for key in ("returned_sources", "inserted_sources", "skipped_sources"):
            item[key] = dict(item[key])
    data_dates = [d for d, item in daily.items() if item["valid_core_count"] > 0]
    completed = [d for d, item in daily.items() if item["status"] == "success"]
    failed = [d for d, item in daily.items() if item["requests"].get("failed")]
    outcome = "complete" if len(completed) == len(dates) else "partial" if data_dates else "failed" if failed else "no_data" if any(i["status"] in ("empty", "requires_repair") for i in daily.values()) else "unsupported"
    return {"outcome": outcome, "success_count": sum(i["inserted"] for i in daily.values()),
            "skipped_count": sum(i["skipped"] for i in daily.values()), "failed_count": len(failed),
            "days_synced": len(data_dates), "requested_dates": dates, "data_dates": data_dates,
            "already_satisfied": not attempts and outcome == "complete",
            "has_source_warnings": any(i["source_quality_warning"] for i in daily.values()) or any(k.endswith(":failed") and n for k, n in attempts.items()),
            "completed_dates": completed, "failed_dates": [{"date": d, "message": "部分请求或写入失败"} for d in failed],
            "empty_dates": [d for d, i in daily.items() if i["status"] == "empty"],
            "empty_response_dates": [d for d, i in daily.items() if i["requests"].get("empty")],
            "unsupported_dates": [d for d, i in daily.items() if i["status"] == "unsupported"],
            "repair_required_dates": [d for d, i in daily.items() if i["requires_existing_row_repair"]],
            "date_results": list(daily.values()), "provider_attempts": dict(attempts), "attempt_examples": examples,
            "rejected_outside_request_rows": rejected_outside_request,
            "universe_basis": "local_current_master_proxy", "market_coverage_ratio": None,
            "universe_bootstrap_source": bootstrap_source,
            "coverage_status": "unverifiable", "write_policy": "insert_missing_only",
            "units": {"vol": "lot", "amount": "thousand_cny"},
            "diagnostic": "完成日期仅指当前目标清单核心有效覆盖≥95%；空返回不等于漏采，已有异常行需T07/T08修复，真实市场覆盖率不可验证。"}
