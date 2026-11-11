"""Freeze one declared final source before planning database repairs."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from collections import Counter
from pathlib import Path
import time as clock
import uuid

from app.services.daily_quote_repair_service import SNAPSHOT_VERSION, SPECS, VALUE_FIELDS, RepairError, canonical, normalized_source_row
from app.services.market_data_capabilities import configured_providers, provider_capabilities
from app.services.market_data_quality_service import CODE, finite, parse_date, read_csv
from app.services.trading_session import shanghai_datetime


def repair_dates(start_date, end_date, calendar_file: Path, now=None):
    parse_date(start_date)
    parse_date(end_date)
    if start_date > end_date:
        raise RepairError("起始日期晚于截止日期")
    dt = shanghai_datetime(now)
    cutoff = dt if dt.time() >= time(16) else dt - timedelta(days=1)
    if end_date > cutoff.strftime("%Y%m%d"):
        raise RepairError("请求日期尚未完成盘后窗口")
    rows, provenance = read_csv(calendar_file, {"trade_date", "is_open"})
    calendar = {}
    for row in rows:
        day = parse_date(row["trade_date"])
        if day in calendar or row["is_open"] not in ("0", "1"):
            raise RepairError("日历重复或状态未知")
        calendar[day] = row["is_open"] == "1"
    day = datetime.strptime(start_date, "%Y%m%d")
    dates = []
    while day.strftime("%Y%m%d") <= end_date:
        key = day.strftime("%Y%m%d")
        if key not in calendar:
            raise RepairError("日历不连续或范围不足")
        if calendar[key]:
            dates.append(key)
        day += timedelta(days=1)
    if not dates or len(dates) > 250:
        raise RepairError("窗口必须包含 1–250 个交易日")
    return dates, provenance


def select_repair_source(router, name):
    for source in configured_providers(router):
        caps = provider_capabilities(source)
        if caps.name == name and caps.enabled and caps.reliable_pre_close and caps.history_by_symbol:
            if (caps.volume_unit, caps.amount_unit) != SPECS.get(name):
                raise RepairError("来源单位与修复策略不一致")
            return source, caps
    raise RepairError("来源未配置、未启用或不满足修复能力；不会自动引入新供应商")


def fetch_repair_snapshot(source, caps, dates, codes, calendar, request_interval=.15):
    codes = sorted(set(codes))
    if not codes or any(not CODE.fullmatch(c) for c in codes):
        raise RepairError("证券范围为空或包含非普通A股代码")
    rows, requests = [], []
    source_info = {"name": caps.name, "volume_unit": caps.volume_unit, "amount_unit": caps.amount_unit,
                   "data_stage": "final", "adjustment": "none", "captured_at": datetime.now(timezone.utc).isoformat()}
    valid_keys = set()
    for code in codes:
        if code.rsplit(".", 1)[-1] not in caps.markets:
            requests.append({"ts_code": code, "status": "unsupported"})
            continue
        try:
            if request_interval > 0:
                clock.sleep(max(1.25, request_interval) if caps.name == "tushare" else request_interval)
            kwargs = {"ts_code": code, "start_date": min(dates), "end_date": max(dates)}
            if type(source).__name__ == "AkshareAdapter":
                kwargs["strict"] = True
            frame = source.get_daily(**kwargs)
            if frame is None or frame.empty:
                requests.append({"ts_code": code, "status": "empty"})
                continue
            valid_count = 0
            for raw in frame.to_dict("records"):
                record = {"ts_code": str(raw.get("ts_code", "")), "trade_date": str(raw.get("trade_date", ""))}
                for field in VALUE_FIELDS:
                    v = raw.get(field)
                    record[field] = float(v) if finite(v) else v if isinstance(v, (str, float, int)) else None
                rows.append(canonical(record))
                try:
                    normalized_source_row(record, source_info)
                    key = (record["ts_code"], record["trade_date"])
                    if key[0] == code and key[1] in dates and key not in valid_keys:
                        valid_keys.add(key)
                        valid_count += 1
                except (TypeError, ValueError, KeyError):
                    pass
            status = "success" if valid_count == len(dates) else "partial" if valid_count else "failed"
            requests.append({"ts_code": code, "status": status, "rows": len(frame), "valid_rows": valid_count})
        except Exception as exc:
            requests.append({"ts_code": code, "status": "failed", "error_type": type(exc).__name__})
    counts = Counter((r["ts_code"], r["trade_date"]) for r in rows)
    valid_keys = {k for k in valid_keys if counts[k] == 1}
    for request in requests:
        if request.get("rows"):
            valid = sum(key[0] == request["ts_code"] for key in valid_keys)
            request["valid_rows"] = valid
            request["status"] = "success" if valid == len(dates) else "partial" if valid else "failed"
    source_info["captured_at"] = datetime.now(timezone.utc).isoformat()
    statuses = {r["status"] for r in requests}
    outcome = "success" if statuses == {"success"} else "partial" if valid_keys else "failed" if "failed" in statuses else "no_data" if "empty" in statuses else "unsupported"
    return {"version": SNAPSHOT_VERSION, "id": str(uuid.uuid4()), "dates": dates, "codes": codes,
            "calendar": calendar, "rows": rows, "requests": requests,
            "source": source_info, "outcome": outcome, "valid_row_count": len(valid_keys)}
