from __future__ import annotations

import json
import time
import uuid
import logging
import math
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy import func
from app.database import SessionLocal
from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchStock
from app.models.sync_log import SyncLog
from app.services.tushare_adapter import tushare_adapter
from app.services.provider_daily_normalization import normalize_provider_daily
from app.services.market_data_capabilities import configured_providers, provider_capabilities
from app.services.trading_session import shanghai_trade_date_str, latest_daily_k_trade_date_str
from app.tasks.background import task_registry

logger = logging.getLogger(__name__)
CORE_DAILY_FIELDS = ("open", "high", "low", "close", "pre_close", "pct_chg")


class MarketDataValidationError(ValueError):
    pass


def _validated_daily_rows(db: Session, frame, ts_code: str, start: str, end: str):
    """Reject incomplete/invalid bars before any normal quote write. Never repair old rows."""
    import pandas as pd
    reasons: dict[str, int] = {}
    unavailable: dict[str, int] = {}
    rows = []
    seen = set()
    columns = {column.name for column in DailyQuote.__table__.columns}
    for _, raw in frame.iterrows():
        data = raw.to_dict()
        reason = None
        code, day = str(data.get("ts_code", "")).strip().upper(), str(data.get("trade_date", "")).strip()
        try:
            if code != ts_code.upper():
                raise ValueError("security_mismatch")
            if len(day) != 8 or not day.isdigit() or not start <= day <= end:
                raise ValueError("date_out_of_range")
            try:
                datetime.strptime(day, "%Y%m%d")
            except ValueError:
                raise ValueError("invalid_date") from None
            values = {}
            for field in CORE_DAILY_FIELDS:
                try:
                    value = float(data[field])
                except (KeyError, ValueError, TypeError):
                    raise ValueError("missing_core_field") from None
                if not math.isfinite(value):
                    raise ValueError("nonfinite_core_field")
                values[field] = value
            if any(values[key] <= 0 for key in ("open", "high", "low", "close", "pre_close")):
                raise ValueError("nonpositive_price")
            if not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]:
                raise ValueError("invalid_ohlc")
            if (code, day) in seen:
                raise ValueError("duplicate_quote")
            data.update(values, ts_code=code, trade_date=day)
            for key in ("vol", "amount"):
                try:
                    value = float(data.get(key))
                    if not math.isfinite(value) or value < 0:
                        raise ValueError
                    data[key] = value
                except (TypeError, ValueError):
                    data[key] = None
                    unavailable[key] = unavailable.get(key, 0) + 1
            for key in ("change", "turnover_rate", "float_share"):
                if key not in data:
                    continue
                if data[key] is None or pd.isna(data[key]):
                    data[key] = None
                    continue
                try:
                    value = float(data[key])
                    if not math.isfinite(value) or (key != "change" and value < 0):
                        raise ValueError
                    data[key] = value
                except (ValueError, TypeError):
                    data[key] = None
                    if key != "change":
                        unavailable[key] = unavailable.get(key, 0) + 1
            rows.append({key: value for key, value in data.items() if key in columns})
            seen.add((code, day))
        except ValueError as exc:
            reason = str(exc)
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    quality = {"accepted_quote_count": len(rows), "rejected_quote_count": sum(reasons.values()),
               "rejected_reasons": reasons, "unavailable_fields": unavailable,
               "outcome": "partial" if reasons else "warning" if unavailable else "validated"}
    if hasattr(db, "info"):
        db.info["daily_sync_quality"] = quality
    if reasons:
        logger.warning("Rejected daily quotes for %s %s..%s: %s", ts_code, start, end, reasons)
    if not rows and not frame.empty:
        raise MarketDataValidationError("行情证据不足，全部返回行被拒绝：" + str(reasons))
    return rows


def _fetch_validated_daily(db: Session, ts_code: str, start: str, end: str):
    """Try only configured leaves; select one source, never mix quote rows/units.

    A fallback must preserve all valid dates already returned by an earlier source.
    Missing volume/amount stays NULL and does not invalidate valid price evidence.
    """
    best, best_quality, attempts = [], {}, []
    last_error = None
    for source in configured_providers(tushare_adapter):
        try:
            caps = provider_capabilities(source)
            name = caps.name
            if not caps.enabled:
                continue
        except ValueError:
            name = type(source).__name__
        try:
            frame = normalize_provider_daily(source.get_daily(ts_code=ts_code, start_date=start, end_date=end), source)
            if frame.empty:
                attempts.append({"provider": name, "outcome": "no_data"})
                continue
            rows = _validated_daily_rows(db, frame, ts_code, start, end)
            quality = dict(getattr(db, "info", {}).get("daily_sync_quality", {}))
            quality["provider"] = name
            attempts.append({"provider": name, "outcome": quality.get("outcome", "validated")})
            dates, best_dates = {row["trade_date"] for row in rows}, {row["trade_date"] for row in best}
            if not best or (dates >= best_dates and (len(rows) > len(best) or
                quality.get("rejected_quote_count", 0) < best_quality.get("rejected_quote_count", 0))):
                best, best_quality = rows, quality
            if best and not best_quality.get("rejected_quote_count"):
                break
        except Exception as exc:
            last_error = exc
            attempts.append({"provider": name, "outcome": "failed", "error_type": type(exc).__name__})
    if best:
        if hasattr(db, "info"):
            db.info["daily_sync_quality"] = {**best_quality, "source_attempts": attempts}
        return best
    if hasattr(db, "info"):
        rejected = dict(db.info.get("daily_sync_quality", {})) if last_error else {}
        db.info["daily_sync_quality"] = {**rejected, "outcome": "rejected" if last_error else "no_data",
                                         "source_attempts": attempts}
    if last_error:
        if isinstance(last_error, MarketDataValidationError):
            raise last_error
        raise RuntimeError("配置行情源请求失败：" + type(last_error).__name__) from None
    return []


def _commit_with_retry(db: Session, retries: int = 3, wait_s: float = 0.6):
    """Commit once; after rollback the caller must rebuild the entire transaction.

    Keep the legacy arguments for callers, but never retry an empty transaction
    after a lock error: doing so would report rolled-back writes as successful.
    SQLite's busy_timeout already waits for transient lock contention.
    """
    try:
        db.commit()
    except OperationalError:
        db.rollback()
        raise


def _get_trade_dates(days: int = 60) -> list[str]:
    from app.services.full_market_history_service import resolve_history_dates
    return resolve_history_dates(tushare_adapter, days)[0]


def _stock_metadata(row, authoritative_fields=()):
    import pandas as pd
    fields = {column.name for column in StockBasic.__table__.columns}
    cleaned = {}
    for key, value in row.items():
        if key not in fields or value is None or pd.isna(value):
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value or value.lower() in {"nan", "none", "null"}:
                continue
        if key == "list_status" and (key not in authoritative_fields or value not in {"L", "D", "P"}):
            continue
        if key == "float_share":
            try:
                value = float(value)
                if not math.isfinite(value) or value <= 0:
                    continue
            except (TypeError, ValueError):
                continue
        if key == "list_date":
            try:
                value = str(value)
                if len(value) != 8 or not value.isdigit():
                    continue
                datetime.strptime(value, "%Y%m%d")
            except ValueError:
                continue
        cleaned[key] = value
    return cleaned


def _sync_stock_basic_full(db: Session) -> tuple[int, bool]:
    """同步全市场 stock_basic，返回 (新增数量, API 是否有返回数据)"""
    df = tushare_adapter.get_stock_basic()
    if df.empty:
        return 0, False
    count = 0
    authority = df.attrs.get("newquant_authoritative_fields", ())
    for _, row in df.iterrows():
        values = _stock_metadata(row, authority)
        if not values.get("ts_code"):
            continue
        existing = db.query(StockBasic).filter(StockBasic.ts_code == row["ts_code"]).first()
        if existing:
            for col, value in values.items():
                setattr(existing, col, value)
        else:
            db.add(StockBasic(**values))
            count += 1
    _commit_with_retry(db)
    return count, True


def sync_stock_info(db: Session, ts_code: str):
    """同步单只股票基础信息（upsert）"""
    df = tushare_adapter.get_stock_basic(ts_code=ts_code)
    if df.empty:
        return
    row = df.iloc[0]
    values = _stock_metadata(row, df.attrs.get("newquant_authoritative_fields", ()))
    if values.get("ts_code") != ts_code:
        raise ValueError("股票基础信息与请求标的不一致")
    existing = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    if existing:
        for col, value in values.items():
            setattr(existing, col, value)
    else:
        db.add(StockBasic(**values))
    _commit_with_retry(db)


def _find_gap_repair_start(
    db: Session,
    ts_code: str,
    *,
    lookback_calendar_days: int = 160,
    max_check_days: int = 80,
) -> str | None:
    """
    检测近期交易日缺口，返回最早缺失交易日（YYYYMMDD）。
    仅用于确定补齐起点，避免“只追最新”导致中间断档长期存在。
    """
    if not hasattr(tushare_adapter, "get_sse_open_dates"):
        return None
    end_date = latest_daily_k_trade_date_str()
    open_dates = tushare_adapter.get_sse_open_dates(
        end_date=end_date,
        lookback_calendar_days=lookback_calendar_days,
    )
    if not open_dates:
        return None
    recent_open = open_dates[-max_check_days:]
    if not recent_open:
        return None

    rows = (
        db.query(DailyQuote.trade_date)
        .filter(
            DailyQuote.ts_code == ts_code,
            DailyQuote.trade_date >= recent_open[0],
            DailyQuote.trade_date <= recent_open[-1],
        )
        .all()
    )
    existing = {r[0] for r in rows if r and r[0]}
    missing = [d for d in recent_open if d not in existing]
    if not missing:
        return None
    return missing[0]


def sync_daily(db: Session, ts_code: str, days: int = 250):
    """增量同步日线行情"""
    if hasattr(db, "info"):
        db.info["daily_sync_quality"] = {}
    hist_count = (
        db.query(func.count(DailyQuote.trade_date))
        .filter(DailyQuote.ts_code == ts_code)
        .scalar()
        or 0
    )
    latest = db.query(DailyQuote.trade_date).filter(
        DailyQuote.ts_code == ts_code
    ).order_by(DailyQuote.trade_date.desc()).first()

    # 历史过稀（例如曾写入异常快照后被清理）时，改为回填窗口，避免只做“向前增量”导致K线长期缺失。
    sparse_threshold = max(20, min(80, days // 3))
    if latest and hist_count >= sparse_threshold:
        start_date = (datetime.strptime(latest[0], "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    else:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    gap_start = _find_gap_repair_start(db, ts_code)
    if gap_start and gap_start < start_date:
        start_date = gap_start

    end_date = latest_daily_k_trade_date_str()
    if start_date > end_date:
        if hasattr(db, "info"):
            db.info["daily_sync_quality"] = {"outcome": "up_to_date", "rejected_quote_count": 0}
        return 0

    rows = _fetch_validated_daily(db, ts_code, start_date, end_date)
    if not rows:
        return 0
    added_count = 0
    for row in rows:
        existing = db.query(DailyQuote).filter(
            DailyQuote.ts_code == row["ts_code"],
            DailyQuote.trade_date == row["trade_date"],
        ).first()
        if not existing:
            db.add(DailyQuote(**row))
            added_count += 1
    _commit_with_retry(db)

    _backfill_turnover_rate(db, ts_code, start_date, end_date)

    return added_count


def sync_daily_backward(db: Session, ts_code: str, target_min_rows: int) -> int:
    """
    从当前最早交易日向前增量拉取日线，直至本地条数 >= target_min_rows，或已无更早数据 / 触及上市日。
    用于 K 线周期选择（如 250 日）时本地历史不足的场景。
    """
    if hasattr(db, "info"):
        db.info["daily_sync_quality"] = {}
    total_added = 0
    max_rounds = 8
    for _ in range(max_rounds):
        cnt = db.query(DailyQuote).filter(DailyQuote.ts_code == ts_code).count()
        if cnt >= target_min_rows:
            break

        oldest_row = (
            db.query(DailyQuote.trade_date)
            .filter(DailyQuote.ts_code == ts_code)
            .order_by(DailyQuote.trade_date.asc())
            .first()
        )
        if not oldest_row:
            break
        oldest = str(oldest_row[0])
        if len(oldest) != 8:
            break

        basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
        list_date_str = (basic.list_date or "19900101") if basic else "19900101"
        if len(list_date_str) != 8:
            list_date_str = "19900101"
        try:
            list_dt = datetime.strptime(list_date_str, "%Y%m%d")
        except ValueError:
            list_dt = datetime(1990, 1, 1)

        missing = target_min_rows - cnt
        calendar_span = max(90, min(int(missing * 2.2) + 80, 1500))

        end_dt = datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)
        end_date = end_dt.strftime("%Y%m%d")
        start_dt = end_dt - timedelta(days=calendar_span)
        if start_dt < list_dt:
            start_dt = list_dt
        start_date = start_dt.strftime("%Y%m%d")

        if start_date > end_date:
            break

        rows = _fetch_validated_daily(db, ts_code, start_date, end_date)
        if not rows:
            break
        round_added = 0
        for row in rows:
            existing = db.query(DailyQuote).filter(
                DailyQuote.ts_code == row["ts_code"],
                DailyQuote.trade_date == row["trade_date"],
            ).first()
            if not existing:
                db.add(DailyQuote(**row))
                round_added += 1

        if round_added == 0:
            break

        _commit_with_retry(db)
        total_added += round_added
        _backfill_turnover_rate(db, ts_code, start_date, end_date)

    return total_added


def _backfill_turnover_rate(db: Session, ts_code: str, start_date: str, end_date: str):
    """补充换手率、流通股本到已存在的 DailyQuote；daily_basic 中的 float_share 回写 StockBasic。"""
    try:
        basic_df = tushare_adapter.get_daily_basic(
            ts_code=ts_code, start_date=start_date, end_date=end_date
        )
        if basic_df.empty:
            return
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
            quote = db.query(DailyQuote).filter(
                DailyQuote.ts_code == ts_code,
                DailyQuote.trade_date == td,
            ).first()
            if not quote:
                continue
            tr = row.get("turnover_rate")
            if tr is not None and not (isinstance(tr, float) and tr != tr) and quote.turnover_rate is None:
                quote.turnover_rate = float(tr)
            fs = row.get("float_share")
            if fs is not None and not (isinstance(fs, float) and fs != fs) and quote.float_share is None:
                quote.float_share = float(fs)
        if latest_fs is not None:
            basic_row = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
            if basic_row:
                basic_row.float_share = latest_fs
        _commit_with_retry(db)
    except Exception:
        db.rollback()
        logger.warning("Optional daily_basic enrichment failed for %s", ts_code, exc_info=True)


def sync_pool(task_id: str, pool_id: str, days: int = 250):
    """同步整个池子（后台线程调用）"""
    db = SessionLocal()
    success_count = 0
    failed_count = 0
    skipped_count = 0
    failed_items: list[dict] = []
    quote_quality: list[dict] = []
    try:
        # 持久化：创建同步记录
        log = SyncLog(
            id=task_id,
            task_type="pool",
            target=pool_id,
            status="running",
        )
        db.add(log)
        db.commit()

        stocks = db.query(WatchStock).filter(WatchStock.pool_id == pool_id).all()
        total = len(stocks)
        for i, ws in enumerate(stocks):
            try:
                sync_stock_info(db, ws.ts_code)
                added = sync_daily(db, ws.ts_code, days)
                quality = getattr(db, "info", {}).get("daily_sync_quality", {})
                if quality.get("rejected_quote_count") or quality.get("unavailable_fields") or quality.get("outcome") == "no_data":
                    quote_quality.append({"ts_code": ws.ts_code, **quality})
                success_count += 1
                if added == 0:
                    skipped_count += 1
            except Exception as e:
                db.rollback()
                failed_count += 1
                failed_items.append({"ts_code": ws.ts_code, "message": str(e)[:120]})
            task_registry[task_id].progress = (i + 1) / total if total else 1.0
            task_registry[task_id].message = f"已同步 {i+1}/{total}"

        task_registry[task_id].result = {
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "days_synced": days,
            "failed_items": failed_items[:50],
            "quote_quality": quote_quality[:100],
            "outcome": "partial" if failed_count or any(q.get("outcome") in {"partial", "no_data"} for q in quote_quality)
                       else "warning" if quote_quality else "completed",
            "message": f"池同步完成：成功 {success_count}，失败 {failed_count}，无新增 {skipped_count}，数据不足 {len(quote_quality)}",
        }

        # 持久化：更新同步记录
        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "failed" if task_registry[task_id].result["outcome"] == "partial" else "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task_registry[task_id].result, ensure_ascii=False)
            db.commit()
        price_incomplete = task_registry[task_id].result["outcome"] == "partial"
        if price_incomplete:
            task_registry[task_id].status = "failed"
            task_registry[task_id].message = task_registry[task_id].result["message"]

        # 同步完成后自动触发监控扫描
        from app.services.monitor_engine import scan_pool as _scan_pool
        from app.tasks.background import submit_task as _submit
        if not price_incomplete:
            _submit("scan", _scan_pool, pool_id)
    except Exception as e:
        task_registry[task_id].result = {
            "success_count": success_count,
            "failed_count": failed_count + 1,
            "skipped_count": skipped_count,
            "days_synced": days,
            "failed_items": failed_items[:50],
            "message": str(e),
        }
        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task_registry[task_id].result, ensure_ascii=False)
            db.commit()
        raise
    finally:
        db.close()


def sync_single_stock(task_id: str, ts_code: str, days: int = 250):
    """同步单只股票（后台线程调用）"""
    db = SessionLocal()
    try:
        # 持久化：创建同步记录
        log = SyncLog(
            id=task_id,
            task_type="stock",
            target=ts_code,
            status="running",
        )
        db.add(log)
        db.commit()

        try:
            sync_stock_info(db, ts_code)
        except Exception:
            db.rollback()
        added = sync_daily(db, ts_code, days)
        quality = getattr(db, "info", {}).get("daily_sync_quality", {})
        task_registry[task_id].progress = 1.0
        incomplete = quality.get("outcome") in {"partial", "no_data"}
        task_registry[task_id].message = f"{ts_code} 同步完成" if not incomplete else f"{ts_code} 行情证据不足，请检查数据质量"
        if incomplete:
            task_registry[task_id].status = "failed"
        task_registry[task_id].result = {
            "success_count": 1,
            "failed_count": 0,
            "skipped_count": 1 if added == 0 else 0,
            "days_synced": days,
            "quote_quality": quality,
            "outcome": "partial" if incomplete else "completed",
            "message": f"{ts_code} 新增 {added} 条；数据状态 {quality.get('outcome', 'unknown')}",
        }

        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "failed" if incomplete else "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task_registry[task_id].result, ensure_ascii=False)
            db.commit()
    except Exception as e:
        task_registry[task_id].result = {
            "success_count": 0,
            "failed_count": 1,
            "skipped_count": 0,
            "days_synced": days,
            "message": str(e),
        }
        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task_registry[task_id].result, ensure_ascii=False)
            db.commit()
        raise
    finally:
        db.close()


def sync_full_market(task_id: str, days: int = 60, end_date: str | None = None):
    """按来源能力回补缺失历史；失败抛出，避免任务包装器误报完成。"""
    from app.services.full_market_history_service import collect_full_market_history, resolve_history_dates
    from app.services.market_data_capabilities import capability_report, configured_providers
    from app.services.tushare_adapter import CompositeAdapter

    task = task_registry.get(task_id)
    if not task:
        return
    db = SessionLocal()
    try:
        log = SyncLog(id=task_id, task_type="full_market", target=None, status="running")
        db.add(log)
        db.commit()
        source = CompositeAdapter(list(configured_providers(tushare_adapter)))
        task.message = "解析交易日历与历史数据源能力..."
        dates, calendar = resolve_history_dates(source, days, end_date)

        def progress(value, message):
            task.progress, task.message = value, message

        result = collect_full_market_history(db, source, dates, progress)
        result.update(calendar=calendar, provider_capabilities=capability_report(source), requested_days=days)
        msg = (f"历史回补 {result['outcome']}：新增 {result['success_count']} 条，"
               f"已有 {result['skipped_count']} 条，有数据 {result['days_synced']}/{len(dates)} 日，"
               f"目标清单达标 {len(result['completed_dates'])} 日；真实市场覆盖率待验证")
        result["message"] = msg
        task.result = result
        successful = bool(result["data_dates"])
        task.status = "completed" if successful else "failed"
        task.progress = 1.0
        task.message = msg
        log.status = task.status
        log.completed_at = datetime.utcnow()
        log.result = json.dumps(result, ensure_ascii=False, allow_nan=False)
        db.commit()
        if not successful:
            raise RuntimeError(msg)
    except Exception:
        db.rollback()
        task.status = "failed"
        if task.result is None:
            task.message = "历史回补失败：检查交易日历、数据源能力、目标清单及数据库连接"
            task.result = {"outcome": "failed", "days_synced": 0, "requested_days": days,
                           "message": task.message, "market_coverage_ratio": None}
        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task.result, ensure_ascii=False)
            db.commit()
        raise RuntimeError(task.message) from None
    finally:
        db.close()
