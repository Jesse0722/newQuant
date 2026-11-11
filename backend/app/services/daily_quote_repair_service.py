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


def normalized_source_row(raw, source):
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


def make_repair_plan(conn, snapshot, *, allow_clear_optional=False):
    if snapshot.get("version") != SNAPSHOT_VERSION:
        raise RepairError("来源快照版本不匹配")
    dates = snapshot.get("dates", [])
    codes = snapshot.get("codes", [])
    if not dates or not codes or len(dates) * len(codes) > 1000000:
        raise RepairError("快照范围为空或过大")
    for d in dates:
        parse_date(d)
    source = snapshot["source"]
    snapshot_hash = digest(snapshot)
    raw_rows = snapshot.get("rows", [])
    counts = Counter(_key(r) for r in raw_rows)
    # One bulk read per 400 symbols; no database mutation or per-row network calls.
    existing = {}
    for index in range(0, len(codes), 400):
        query = select(Q).where(Q.c.ts_code.in_(codes[index:index + 400]),
                                Q.c.trade_date.in_(dates))
        existing.update({_key(r): quote_state(r) for r in conn.execute(query).mappings()})
    items, skipped = [], []
    unchanged = 0
    for raw in sorted(raw_rows, key=_key):
        key = _key(raw)
        if key[0] not in codes or key[1] not in dates or counts[key] != 1:
            skipped.append({"ts_code": key[0], "trade_date": key[1], "reason": "outside_scope_or_duplicate"})
            continue
        try:
            new = normalized_source_row(raw, source)
        except (ValueError, TypeError, KeyError):
            skipped.append({"ts_code": key[0], "trade_date": key[1], "reason": "invalid_source_row"})
            continue
        old = existing.get(key)
        if _losses(old, new) and not allow_clear_optional:
            skipped.append({"ts_code": key[0], "trade_date": key[1], "reason": "optional_field_loss",
                            "fields": _losses(old, new)})
            continue
        changed = [f for f in VALUE_FIELDS if old is None or old[f] != new[f]]
        if not changed:
            unchanged += 1
            continue
        raw_state = canonical(raw)
        raw_hash = digest(raw_state)
        source_json = {"source": source, "snapshot_id": snapshot["id"], "snapshot_hash": snapshot_hash,
                       "raw_values": raw_state, "raw_hash": raw_hash, "normalization_version": PLAN_VERSION,
                       "field_source": {f: raw_hash for f in VALUE_FIELDS}}
        items.append({"operation": "insert" if old is None else "update", "ts_code": key[0], "trade_date": key[1],
                      "old_values": old, "new_values": new, "old_hash": state_hash(old), "new_hash": digest(new),
                      "changed_fields": changed, "source_json": source_json})
    return {"version": PLAN_VERSION, "id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
            "database_identity": database_identity(conn), "source": source, "dates": dates, "codes": codes,
            "snapshot_id": snapshot["id"], "snapshot_hash": snapshot_hash,
            "policy": {"selection": "single_authoritative_row", "allow_clear_optional": allow_clear_optional},
            "summary": {"updates": sum(i["operation"] == "update" for i in items),
                        "inserts": sum(i["operation"] == "insert" for i in items),
                        "unchanged": unchanged, "skipped": len(skipped), "requested_cells": len(codes) * len(dates)},
            "items": items, "skipped": skipped,
            "source_requests": snapshot.get("requests", []), "calendar": snapshot.get("calendar", {})}


def validate_plan(plan):
    if plan.get("version") != PLAN_VERSION or plan.get("policy", {}).get("selection") != "single_authoritative_row":
        raise RepairError("修复计划版本或策略无效")
    if not isinstance(plan["policy"].get("allow_clear_optional"), bool):
        raise RepairError("计划附加字段策略格式无效")
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
        recomputed = normalized_source_row(evidence["raw_values"], evidence["source"])
        if recomputed != new or state_hash(old) != item["old_hash"] or digest(new) != item["new_hash"]:
            raise RepairError("新旧值或标准化校验失败")
        changed = [f for f in VALUE_FIELDS if old is None or old[f] != new[f]]
        if not changed or changed != item["changed_fields"]:
            raise RepairError("字段差异清单不匹配")
        if _losses(old, new) and not plan["policy"].get("allow_clear_optional"):
            raise RepairError("计划会清空已有附加字段")


def _preflight(conn, items, expected, lock=True):
    conflicts = []
    for item in sorted(items, key=_key):
        current = _read(conn, _key(item), lock)
        if state_hash(current) != item[expected]:
            conflicts.append({"ts_code": item["ts_code"], "trade_date": item["trade_date"]})
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
    validate_plan(proof)


def apply_repair_plan(conn, plan, backup_manifest, *, approved_file_sha256=None):
    """Caller uses writer_connection; all data and audit writes share one transaction."""
    validate_plan(plan)
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
    if not plan["items"]:
        return {"batch_id": None, "status": "no_changes"}
    from app.services.source_identity import IDENTITY_POLICY
    if plan.get("source", {}).get("identity_policy") != IDENTITY_POLICY:
        raise RepairError("尚未应用的旧计划缺少原始身份强校验；请保留工件并重新采集生成计划")
    _backup_state(conn, backup_manifest)
    _preflight(conn, plan["items"], "old_hash")
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
    _preflight(conn, plan["items"], "new_hash")
    count = conn.execute(select(func.count()).select_from(Q)).scalar_one()
    if count != before_count + plan["summary"]["inserts"]:
        raise RepairError("修复后的行数不匹配")
    summary = {**plan["summary"], "row_count_before": before_count, "row_count_after": count,
               "plan_hash": plan_hash,
               "plan_id": plan["id"], "plan_version": plan["version"], "source": plan["source"],
               "snapshot_id": plan["snapshot_id"], "snapshot_hash": plan["snapshot_hash"],
               "approved_file_sha256": approved_file_sha256, "audit_hash": _audit_digest(audit_records),
               "affected_hash": digest([(i["ts_code"], i["trade_date"], i["new_hash"]) for i in plan["items"]])}
    conn.execute(update(B).where(B.c.id == batch_id).values(summary=summary))
    stored_batch = conn.execute(select(B).where(B.c.id == batch_id)).mappings().one()
    stored_audits = list(conn.execute(select(A).where(A.c.batch_id == batch_id).order_by(A.c.sequence)).mappings())
    _validate_audits(stored_batch, stored_audits)
    return {"batch_id": batch_id, "status": "applied", **summary}


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
    _preflight(conn, items, "new_hash")
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
    _preflight(conn, items, "old_hash")
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
    mismatches = [{"ts_code": i["ts_code"], "trade_date": i["trade_date"]} for i in items
                  if state_hash(_read(conn, _key(i))) != i[expected]]
    try:
        _validate_audits(batch, items)
        integrity = True
    except (ValueError, TypeError, KeyError):
        integrity = False
    return {"batch_id": batch_id, "status": batch["status"], "audit_rows": len(items),
            "plan_hash": batch["plan_hash"], "approved_file_sha256": batch["summary"].get("approved_file_sha256"),
            "audit_integrity": integrity, "matches": not mismatches and integrity, "mismatches": mismatches}
