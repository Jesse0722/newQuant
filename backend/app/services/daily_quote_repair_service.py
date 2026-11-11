"""Deterministic quote repair plans and transactional, conflict-safe reversal."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import uuid

from sqlalchemy import and_, delete, func, insert, select, update

from app.models.stock import DailyQuote
from app.models.daily_quote_repair import DailyQuoteRepairAudit, DailyQuoteRepairBatch
from app.services.market_data_quality_service import CODE, CORE, finite, parse_date, valid_field
from app.services.quote_repair_io import database_identity, validate_backup, quote_fingerprint

PLAN_VERSION = "daily-quote-repair-v1"
SNAPSHOT_VERSION = "daily-quote-source-v1"
INPUT_VALIDATION_POLICY = "complete-grid-price-volume-v1"
Q = DailyQuote.__table__
B = DailyQuoteRepairBatch.__table__
A = DailyQuoteRepairAudit.__table__
VALUE_FIELDS = tuple(c.name for c in Q.columns if c.name not in ("ts_code", "trade_date"))
ROW_FIELDS = {c.name for c in Q.columns}
SPECS = {"baostock": ("share", "cny"), "akshare": ("lot", "cny"),
         "tushare": ("lot", "thousand_cny")}


class RepairError(ValueError):
    """An actionable error containing no DSNs, SQL parameters or credentials."""


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def canonical(value):
    """Lossless JSON representation of legacy non-finite float values."""
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return {"__float__": "nan" if math.isnan(value) else "+inf" if value > 0 else "-inf"}
    if isinstance(value, float) and value == 0:
        return 0.0
    return value


def restore(value):
    if isinstance(value, dict):
        if set(value) == {"__float__"} and value["__float__"] in ("nan", "+inf", "-inf"):
            return float(value["__float__"].replace("+inf", "inf"))
        return {k: restore(v) for k, v in value.items()}
    if isinstance(value, list):
        return [restore(v) for v in value]
    return value


def digest(value):
    body = json.dumps(canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


def quote_state(row):
    if row is None:
        return None
    result = {}
    for key in sorted(ROW_FIELDS):
        value = row[key]
        if key in VALUE_FIELDS and value is not None:
            try:
                value = float(value)
            except (ValueError, TypeError):
                pass  # SQLite legacy REAL columns may contain invalid text.
        result[key] = value
    return canonical(result)


def state_hash(row):
    return None if row is None else digest(row)


def normalized_source_row(raw, source, *, enforce_market_consistency=True):
    if source.get("identity_policy"):
        from app.services.source_identity import IDENTITY_POLICY, verify_row_identity
        if source["identity_policy"] != IDENTITY_POLICY:
            raise RepairError("原始身份验证策略不支持")
        verify_row_identity(raw.get("source_identity"), source.get("name"), raw.get("ts_code"), raw.get("trade_date"))
    if source.get("name") not in SPECS or (source.get("volume_unit"), source.get("amount_unit")) != SPECS[source["name"]]:
        raise RepairError("来源或量额单位未认证")
    if source.get("data_stage") != "final" or source.get("adjustment") != "none":
        raise RepairError("修复仅接受不复权、盘后正式来源")
    row = restore(raw)
    code, day = row.get("ts_code"), row.get("trade_date")
    if not isinstance(code, str) or not CODE.fullmatch(code):
        raise RepairError("来源证券代码无效")
    parse_date(day)
    if not all(valid_field(f, row.get(f)) for f in (*CORE, "vol", "amount")):
        raise RepairError("来源缺少有效核心字段或量额")
    new = {f: float(row[f]) if finite(row.get(f)) else None for f in VALUE_FIELDS}
    if new["high"] < max(new["open"], new["close"]) or new["low"] > min(new["open"], new["close"]) or new["high"] < new["low"]:
        raise RepairError("来源OHLC顺序无效")
    new["change"] = new["close"] - new["pre_close"]
    expected_pct = new["change"] / new["pre_close"] * 100
    if abs(new["pct_chg"] - expected_pct) > .03:
        raise RepairError("来源前收与涨跌幅口径不一致")
    if source["volume_unit"] == "share":
        new["vol"] /= 100
    if source["amount_unit"] == "cny":
        new["amount"] /= 1000
    if enforce_market_consistency:
        if (new["vol"] == 0) != (new["amount"] == 0):
            raise RepairError("来源零量与零成交额必须配对")
        if new["vol"] > 0:
            # Canonical units are lots (100 shares) and thousand CNY.
            average_price = new["amount"] * 10 / new["vol"]
            tolerance = max(1e-8, max(abs(new["low"]), abs(new["high"])) * 1e-9)
            if not math.isfinite(average_price) or not new["low"] - tolerance <= average_price <= new["high"] + tolerance:
                raise RepairError("来源量额均价不在日内价格区间")
    for field in ("turnover_rate", "float_share"):
        if row.get(field) is not None and not valid_field(field, row[field]):
            raise RepairError("来源附加字段无效")
    new.update(ts_code=code, trade_date=day)
    return quote_state(new)


def _key(row):
    return row["ts_code"], row["trade_date"]


def _where(key):
    return and_(Q.c.ts_code == key[0], Q.c.trade_date == key[1])


def _read(conn, key, lock=False):
    query = select(Q).where(_where(key))
    if lock:
        query = query.with_for_update()
    return quote_state(conn.execute(query).mappings().first())


def _losses(old, new):
    return [f for f in ("turnover_rate", "float_share") if old and valid_field(f, old.get(f)) and new.get(f) is None]


def _grid_scope(codes, dates):
    if not isinstance(codes, list) or not isinstance(dates, list) or not codes or not dates or len(dates) > 250:
        raise RepairError("来源网格范围为空或格式无效")
    if any(not isinstance(code, str) or not CODE.fullmatch(code) for code in codes):
        raise RepairError("来源网格证券代码无效")
    if any(not isinstance(day, str) for day in dates):
        raise RepairError("来源网格日期无效")
    if len(set(codes)) != len(codes) or len(set(dates)) != len(dates):
        raise RepairError("来源网格证券或日期重复")
    for day in dates:
        parse_date(day)
    if len(codes) * len(dates) > 1000000:
        raise RepairError("来源网格过大")
    return {(code, day) for code in codes for day in dates}


def validate_snapshot_grid(snapshot):
    """Validate actual input cells; status labels and reported counts are not proof."""
    from app.services.source_identity import IDENTITY_POLICY
    if snapshot.get("version") != SNAPSHOT_VERSION:
        raise RepairError("来源快照版本不匹配")
    if snapshot.get("source", {}).get("identity_policy") != IDENTITY_POLICY:
        raise RepairError("新快照缺少原始身份强校验")
    expected = _grid_scope(snapshot.get("codes"), snapshot.get("dates"))
    rows = snapshot.get("rows")
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise RepairError("来源网格不完整：实际行数与证券×日期范围不符")
    if "valid_row_count" in snapshot and (type(snapshot["valid_row_count"]) is not int or snapshot["valid_row_count"] != len(expected)):
        raise RepairError("来源网格有效行汇总不一致")
    normalized = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise RepairError("来源网格行格式无效")
        key = (raw.get("ts_code"), raw.get("trade_date"))
        if key not in expected or key in normalized:
            raise RepairError("来源网格存在范围外或重复主键")
        try:
            normalized[key] = normalized_source_row(raw, snapshot["source"])
        except (ValueError, TypeError, KeyError) as exc:
            raise RepairError("来源网格含无效行情或原始身份") from exc
    if set(normalized) != expected:
        raise RepairError("来源网格不完整")
    return normalized


def _input_grid_digest(plan):
    return digest({"policy": INPUT_VALIDATION_POLICY, "codes": plan["codes"], "dates": plan["dates"],
                   "source": plan["source"], "cells": plan["input_grid"]})


def make_repair_plan(conn, snapshot, *, allow_clear_optional=False):
    normalized = validate_snapshot_grid(snapshot)
    dates, codes = snapshot["dates"], snapshot["codes"]
    source = snapshot["source"]
    snapshot_hash = digest(snapshot)
    raw_rows = snapshot.get("rows", [])
    # One bulk read per 400 symbols; no database mutation or per-row network calls.
    existing = {}
    for index in range(0, len(codes), 400):
        query = select(Q).where(Q.c.ts_code.in_(codes[index:index + 400]),
                                Q.c.trade_date.in_(dates))
        existing.update({_key(r): quote_state(r) for r in conn.execute(query).mappings()})
    items, skipped, input_grid = [], [], []
    unchanged = 0
    for raw in sorted(raw_rows, key=_key):
        key = _key(raw)
        new = normalized[key]
        old = existing.get(key)
        raw_state = canonical(raw)
        raw_hash = digest(raw_state)
        cell = {"ts_code": key[0], "trade_date": key[1], "raw_hash": raw_hash}
        input_grid.append(cell)
        if _losses(old, new) and not allow_clear_optional:
            skipped.append({"ts_code": key[0], "trade_date": key[1], "reason": "optional_field_loss",
                            "fields": _losses(old, new)})
            cell.update(disposition="skipped", proof={"raw_values": raw_state, "old_values": old})
            continue
        changed = [f for f in VALUE_FIELDS if old is None or old[f] != new[f]]
        if not changed:
            unchanged += 1
            cell.update(disposition="unchanged", proof={"raw_values": raw_state, "old_values": old})
            continue
        cell["disposition"] = "insert" if old is None else "update"
        source_json = {"source": source, "snapshot_id": snapshot["id"], "snapshot_hash": snapshot_hash,
                       "raw_values": raw_state, "raw_hash": raw_hash, "normalization_version": PLAN_VERSION,
                       "field_source": {f: raw_hash for f in VALUE_FIELDS}}
        items.append({"operation": "insert" if old is None else "update", "ts_code": key[0], "trade_date": key[1],
                      "old_values": old, "new_values": new, "old_hash": state_hash(old), "new_hash": digest(new),
                      "changed_fields": changed, "source_json": source_json})
    result = {"version": PLAN_VERSION, "id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
            "database_identity": database_identity(conn), "source": source, "dates": dates, "codes": codes,
            "snapshot_id": snapshot["id"], "snapshot_hash": snapshot_hash,
            "policy": {"selection": "single_authoritative_row", "allow_clear_optional": allow_clear_optional,
                       "input_validation": INPUT_VALIDATION_POLICY},
            "summary": {"updates": sum(i["operation"] == "update" for i in items),
                        "inserts": sum(i["operation"] == "insert" for i in items),
                        "unchanged": unchanged, "skipped": len(skipped), "requested_cells": len(codes) * len(dates)},
            "items": items, "skipped": skipped, "input_grid": input_grid,
            "source_requests": snapshot.get("requests", []), "calendar": snapshot.get("calendar", {})}
    result["input_grid_digest"] = _input_grid_digest(result)
    return result


def _validate_input_grid(plan):
    from app.services.source_identity import IDENTITY_POLICY
    if plan.get("source", {}).get("identity_policy") != IDENTITY_POLICY:
        raise RepairError("新计划缺少原始身份强校验")
    expected = _grid_scope(plan.get("codes"), plan.get("dates"))
    cells = plan.get("input_grid")
    if not isinstance(cells, list) or len(cells) != len(expected):
        raise RepairError("计划输入网格不完整")
    counts = Counter()
    seen = set()
    writes = {_key(item): item for item in plan["items"]}
    skipped = {}
    for item in plan.get("skipped", []):
        key = _key(item)
        if key in skipped or key not in expected or item.get("reason") != "optional_field_loss":
            raise RepairError("计划跳过记录与输入网格不一致")
        skipped[key] = item
    for cell in cells:
        key = _key(cell)
        if key in seen or key not in expected:
            raise RepairError("计划输入网格有重复或范围外主键")
        seen.add(key)
        disposition = cell.get("disposition")
        counts[disposition] += 1
        if key in writes:
            item = writes[key]
            if disposition != item["operation"] or cell.get("raw_hash") != item["source_json"]["raw_hash"] or key in skipped:
                raise RepairError("计划写入与输入网格证明不一致")
            continue
        proof = cell.get("proof")
        if not isinstance(proof, dict) or not isinstance(proof.get("raw_values"), dict):
            raise RepairError("计划非写入格缺少来源证明")
        raw, old = proof["raw_values"], proof.get("old_values")
        if _key(raw) != key or digest(raw) != cell.get("raw_hash"):
            raise RepairError("计划输入网格来源证明不一致")
        if not isinstance(old, dict) or set(old) != ROW_FIELDS or _key(old) != key:
            raise RepairError("计划非写入格缺少完整旧值证明")
        new = normalized_source_row(raw, plan["source"])
        if disposition == "unchanged":
            if old != new or key in skipped:
                raise RepairError("计划未变化格与输入证明不一致")
        elif disposition == "skipped":
            losses = _losses(old, new)
            if (not losses or plan["policy"]["allow_clear_optional"] or key not in skipped
                    or skipped[key].get("fields") != losses):
                raise RepairError("计划可选字段保护与输入证明不一致")
        else:
            raise RepairError("计划输入网格处置类型无效")
    summary = plan["summary"]
    actual_counts = {"updates": counts["update"], "inserts": counts["insert"],
                     "unchanged": counts["unchanged"], "skipped": counts["skipped"],
                     "requested_cells": len(expected)}
    if (seen != expected or len(writes) != counts["insert"] + counts["update"]
            or len(skipped) != counts["skipped"] or sum(counts.values()) != len(expected)):
        raise RepairError("计划输入网格与处置集合不完整")
    if any(type(summary.get(field)) is not int or summary[field] != count for field, count in actual_counts.items()):
        raise RepairError("计划输入网格与汇总不一致")
    if plan.get("input_grid_digest") != _input_grid_digest(plan):
        raise RepairError("计划输入网格摘要校验失败")


def validate_plan(plan, *, allow_legacy=False):
    if plan.get("version") != PLAN_VERSION or plan.get("policy", {}).get("selection") != "single_authoritative_row":
        raise RepairError("修复计划版本或策略无效")
    if not isinstance(plan["policy"].get("allow_clear_optional"), bool):
        raise RepairError("计划附加字段策略格式无效")
    policy = plan["policy"].get("input_validation")
    if policy not in (None, INPUT_VALIDATION_POLICY):
        raise RepairError("计划输入网格验证版本不支持")
    if policy is None and not allow_legacy:
        raise RepairError("旧计划缺少完整输入网格证明，请重新生成")
    if len(plan.get("items", [])) > 1000000:
        raise RepairError("修复计划过大")
    for operation, field in (("insert", "inserts"), ("update", "updates")):
        if plan["summary"].get(field) != sum(i["operation"] == operation for i in plan["items"]):
            raise RepairError("计划汇总与修复明细不匹配")
    seen = set()
    for item in plan["items"]:
        key = _key(item)
        if key in seen or key[0] not in plan["codes"] or key[1] not in plan["dates"]:
            raise RepairError("计划有重复或范围外主键")
        seen.add(key)
        old, new = item["old_values"], item["new_values"]
        if set(new) != ROW_FIELDS or (old is not None and set(old) != ROW_FIELDS):
            raise RepairError("计划行情字段不完整")
        if _key(new) != key or (old is not None and _key(old) != key):
            raise RepairError("计划主键不一致")
        if item["operation"] != ("insert" if old is None else "update"):
            raise RepairError("计划操作类型错误")
        evidence = item["source_json"]
        if evidence.get("snapshot_id") != plan.get("snapshot_id") or evidence.get("snapshot_hash") != plan.get("snapshot_hash"):
            raise RepairError("来源快照身份不一致")
        if evidence["source"] != plan["source"] or digest(evidence["raw_values"]) != evidence["raw_hash"]:
            raise RepairError("原始来源校验失败")
        if evidence.get("normalization_version") != PLAN_VERSION or evidence.get("field_source") != {f: evidence["raw_hash"] for f in VALUE_FIELDS}:
            raise RepairError("字段来源血缘不一致")
        recomputed = normalized_source_row(evidence["raw_values"], evidence["source"],
                                           enforce_market_consistency=policy == INPUT_VALIDATION_POLICY)
        if recomputed != new or state_hash(old) != item["old_hash"] or digest(new) != item["new_hash"]:
            raise RepairError("新旧值或标准化校验失败")
        changed = [f for f in VALUE_FIELDS if old is None or old[f] != new[f]]
        if not changed or changed != item["changed_fields"]:
            raise RepairError("字段差异清单不匹配")
        if _losses(old, new) and not plan["policy"].get("allow_clear_optional"):
            raise RepairError("计划会清空已有附加字段")
    if policy == INPUT_VALIDATION_POLICY:
        _validate_input_grid(plan)


def _full_grid_checks(grid, items):
    """Bind every frozen disposition to its claimed database state."""
    writes = {_key(item): item for item in items}
    checks = []
    for cell in grid:
        key = _key(cell)
        if key in writes:
            checks.append({**writes[key], "disposition": cell["disposition"]})
        else:
            frozen = state_hash(cell["proof"]["old_values"])
            checks.append({"ts_code": key[0], "trade_date": key[1], "old_hash": frozen,
                           "new_hash": frozen, "disposition": cell["disposition"]})
    return checks


def _state_mismatches(conn, items, expected, lock=False):
    mismatches = []
    for item in sorted(items, key=_key):
        current = _read(conn, _key(item), lock)
        if state_hash(current) != item[expected]:
            mismatch = {"ts_code": item["ts_code"], "trade_date": item["trade_date"]}
            if "disposition" in item:
                mismatch["disposition"] = item["disposition"]
            mismatches.append(mismatch)
    return mismatches


def _preflight(conn, items, expected, lock=True):
    conflicts = _state_mismatches(conn, items, expected, lock)
    if conflicts:
        raise RepairError(f"发现 {len(conflicts)} 条并发修改冲突；未应用本批次")


def _lock_quotes(conn):
    if conn.dialect.name == "postgresql":
        # Keep one lock ordering for apply and rollback; no network work inside.
        conn.exec_driver_sql("LOCK TABLE daily_quote IN SHARE ROW EXCLUSIVE MODE")


def _backup_state(conn, manifest):
    identity = database_identity(conn)
    validate_backup(manifest, identity)
    state = quote_fingerprint(conn)
    if any(manifest.get(key) != value for key, value in state.items()):
        raise RepairError("备份后行情库已变化；请重新备份再应用")


def _audit_digest(items):
    return digest([{key: value for key, value in dict(i).items() if key != "rolled_back_at"} for i in items])


def _validate_audits(batch, items):
    summary = batch["summary"]
    if len(items) != summary["inserts"] + summary["updates"] or not items:
        raise RepairError("批次审计数量不匹配，禁止回滚")
    if [i["sequence"] for i in items] != list(range(len(items))):
        raise RepairError("审计明细序号不连续")
    if _audit_digest(items) != summary.get("audit_hash"):
        raise RepairError("批次审计集合或来源校验失败")
    proof = {"version": PLAN_VERSION, "policy": batch["policy"], "source": summary["source"],
             "snapshot_id": summary["snapshot_id"], "snapshot_hash": summary["snapshot_hash"],
             "summary": summary, "dates": [i["trade_date"] for i in items],
             "codes": [i["ts_code"] for i in items], "items": items}
    if batch["policy"].get("input_validation") == INPUT_VALIDATION_POLICY:
        scope = summary.get("input_grid_scope", {})
        proof.update(codes=scope.get("codes"), dates=scope.get("dates"),
                     input_grid=summary.get("input_grid"), input_grid_digest=summary.get("input_grid_digest"),
                     skipped=summary.get("input_grid_skipped", []))
    validate_plan(proof, allow_legacy=True)


def apply_repair_plan(conn, plan, backup_manifest, *, approved_file_sha256=None):
    """Caller uses writer_connection; all data and audit writes share one transaction."""
    validate_plan(plan, allow_legacy=True)
    if approved_file_sha256 is not None and (len(approved_file_sha256) != 64 or any(c not in "0123456789abcdef" for c in approved_file_sha256)):
        raise RepairError("已核对文件哈希格式无效")
    _lock_quotes(conn)
    identity = database_identity(conn)
    if identity != plan["database_identity"]:
        raise RepairError("当前数据库与计划目标不一致")
    plan_hash = digest(plan)
    batch = conn.execute(select(B).where(B.c.plan_hash == plan_hash).with_for_update()).mappings().first()
    if batch:
        if batch["status"] != "applied":
            raise RepairError("该计划已回滚或状态异常；请重新生成计划")
        return {"batch_id": batch["id"], "status": "already_applied", "plan_hash": batch["plan_hash"],
                "approved_file_sha256": batch["summary"].get("approved_file_sha256")}
    from app.services.source_identity import IDENTITY_POLICY
    if plan.get("source", {}).get("identity_policy") != IDENTITY_POLICY:
        raise RepairError("尚未应用的旧计划缺少原始身份强校验；请保留工件并重新采集生成计划")
    validate_plan(plan)
    if not plan["items"]:
        # An empty change set still makes claims about unchanged/skipped cells.
        # Verify those claims under the same write lock before reporting success.
        _preflight(conn, _full_grid_checks(plan["input_grid"], plan["items"]), "old_hash")
        return {"batch_id": None, "status": "no_changes"}
    _backup_state(conn, backup_manifest)
    checks = _full_grid_checks(plan["input_grid"], plan["items"])
    _preflight(conn, checks, "old_hash")
    now, batch_id = utc_now(), str(uuid.uuid4())
    before_count = conn.execute(select(func.count()).select_from(Q)).scalar_one()
    conn.execute(insert(B).values(id=batch_id, plan_hash=plan_hash, status="applied", database_identity=identity,
                                 policy=plan["policy"], backup_manifest=backup_manifest, summary=plan["summary"],
                                 created_at=now, applied_at=now))
    audit_records = []
    for sequence, item in enumerate(plan["items"]):
        values = restore(item["new_values"])
        if item["operation"] == "insert":
            conn.execute(insert(Q).values(**values))
        else:
            conn.execute(update(Q).where(_where(_key(item))).values(**{f: values[f] for f in VALUE_FIELDS}))
        audit_record = dict(id=str(uuid.uuid4()), batch_id=batch_id, sequence=sequence,
                     ts_code=item["ts_code"], trade_date=item["trade_date"], operation=item["operation"],
                     old_values=item["old_values"], new_values=item["new_values"],
                     changed_fields=item["changed_fields"], old_hash=item["old_hash"], new_hash=item["new_hash"],
                     source_json=item["source_json"], applied_at=now)
        conn.execute(insert(A).values(**audit_record))
        audit_records.append({**audit_record, "rolled_back_at": None})
    _preflight(conn, checks, "new_hash")
    count = conn.execute(select(func.count()).select_from(Q)).scalar_one()
    if count != before_count + plan["summary"]["inserts"]:
        raise RepairError("修复后的行数不匹配")
    summary = {**plan["summary"], "row_count_before": before_count, "row_count_after": count,
               "plan_hash": plan_hash,
               "plan_id": plan["id"], "plan_version": plan["version"], "source": plan["source"],
               "snapshot_id": plan["snapshot_id"], "snapshot_hash": plan["snapshot_hash"],
               "approved_file_sha256": approved_file_sha256, "audit_hash": _audit_digest(audit_records),
               "input_grid_scope": {"codes": plan["codes"], "dates": plan["dates"]},
               "input_grid": plan["input_grid"], "input_grid_digest": plan["input_grid_digest"],
               "input_grid_skipped": plan["skipped"],
               "affected_hash": digest([(i["ts_code"], i["trade_date"], i["new_hash"]) for i in plan["items"]])}
    conn.execute(update(B).where(B.c.id == batch_id).values(summary=summary))
    stored_batch = conn.execute(select(B).where(B.c.id == batch_id)).mappings().one()
    stored_audits = list(conn.execute(select(A).where(A.c.batch_id == batch_id).order_by(A.c.sequence)).mappings())
    _validate_audits(stored_batch, stored_audits)
    public_summary = {key: value for key, value in summary.items()
                      if key not in {"input_grid", "input_grid_scope", "input_grid_skipped"}}
    return {"batch_id": batch_id, "status": "applied", **public_summary}


def rollback_repair_batch(conn, batch_id, backup_manifest):
    _lock_quotes(conn)
    batch = conn.execute(select(B).where(B.c.id == batch_id).with_for_update()).mappings().first()
    if not batch:
        raise RepairError("修复批次不存在")
    if batch["status"] == "rolled_back":
        return {"batch_id": batch_id, "status": "already_rolled_back"}
    if batch["status"] != "applied" or batch["database_identity"] != database_identity(conn):
        raise RepairError("批次状态或数据库身份不匹配")
    _backup_state(conn, backup_manifest)
    items = [dict(r) for r in conn.execute(select(A).where(A.c.batch_id == batch_id).order_by(A.c.sequence).with_for_update()).mappings()]
    _validate_audits(batch, items)
    # Check every row before any mutation; later edits to any field are protected.
    checks = (_full_grid_checks(batch["summary"]["input_grid"], items)
              if batch["policy"].get("input_validation") == INPUT_VALIDATION_POLICY else items)
    _preflight(conn, checks, "new_hash")
    before_count = conn.execute(select(func.count()).select_from(Q)).scalar_one()
    for item in reversed(items):
        if item["old_values"] is None:
            conn.execute(delete(Q).where(_where(_key(item))))
        else:
            old = restore(item["old_values"])
            if conn.dialect.name == "sqlite":
                # Preserve even legacy invalid text without Float bind coercion.
                assignments = ",".join(f'"{f}"=?' for f in VALUE_FIELDS)
                conn.exec_driver_sql(f'UPDATE daily_quote SET {assignments} WHERE ts_code=? AND trade_date=?',
                                     tuple(old[f] for f in VALUE_FIELDS) + _key(item))
            else:
                conn.execute(update(Q).where(_where(_key(item))).values(**{f: old[f] for f in VALUE_FIELDS}))
    _preflight(conn, checks, "old_hash")
    current_audits = list(conn.execute(select(A).where(A.c.batch_id == batch_id).order_by(A.c.sequence).with_for_update()).mappings())
    _validate_audits(batch, current_audits)
    count = conn.execute(select(func.count()).select_from(Q)).scalar_one()
    if count != before_count - sum(i["old_values"] is None for i in items):
        raise RepairError("回滚后的行数不匹配")
    now = utc_now()
    conn.execute(update(A).where(A.c.batch_id == batch_id).values(rolled_back_at=now))
    summary = {**batch["summary"], "rollback_backup": backup_manifest, "rollback_row_count": count,
               "restored_hash": digest([(i["ts_code"], i["trade_date"], i["old_hash"]) for i in items])}
    conn.execute(update(B).where(B.c.id == batch_id).values(status="rolled_back", rolled_back_at=now, summary=summary))
    return {"batch_id": batch_id, "status": "rolled_back", "restored_rows": len(items), "row_count": count}


def verify_repair_batch(conn, batch_id):
    batch = conn.execute(select(B).where(B.c.id == batch_id)).mappings().first()
    if not batch or batch["database_identity"] != database_identity(conn):
        raise RepairError("批次不存在或目标数据库不匹配")
    if batch["status"] not in ("applied", "rolled_back"):
        raise RepairError("批次状态异常")
    items = list(conn.execute(select(A).where(A.c.batch_id == batch_id).order_by(A.c.sequence)).mappings())
    expected = "old_hash" if batch["status"] == "rolled_back" else "new_hash"
    try:
        _validate_audits(batch, items)
        integrity = True
    except (ValueError, TypeError, KeyError):
        integrity = False
    full_grid = integrity and batch["policy"].get("input_validation") == INPUT_VALIDATION_POLICY
    checks = _full_grid_checks(batch["summary"]["input_grid"], items) if full_grid else items
    mismatches = _state_mismatches(conn, checks, expected)
    return {"batch_id": batch_id, "status": batch["status"], "audit_rows": len(items),
            "plan_hash": batch["plan_hash"], "approved_file_sha256": batch["summary"].get("approved_file_sha256"),
            "audit_integrity": integrity, "matches": not mismatches and integrity, "mismatches": mismatches,
            "verification_scope": "full_input_grid" if full_grid else "written_audit_rows",
            "scope_rows": len(checks)}
