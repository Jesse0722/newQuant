from __future__ import annotations

import json
import logging
import gzip
import socket
import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib import parse, request

import pandas as pd
from sqlalchemy.orm import Session

from app.models.sector import SectorBasic, SectorDailyQuote, SectorQuoteSyncState, StockSectorMap
from app.utils import normalize_ts_code

logger = logging.getLogger(__name__)

SectorType = Literal["concept", "industry"]
SOURCE = "eastmoney_direct"

_CLIST_HOSTS = (
    "https://79.push2.eastmoney.com",
    "https://29.push2.eastmoney.com",
    "https://push2.eastmoney.com",
)
_KLINE_HOSTS = (
    "https://91.push2his.eastmoney.com",
    "https://push2his.eastmoney.com",
)
_FORCED_HOST_IPS = {
    "push2his.eastmoney.com": ("101.226.30.221", "61.129.129.199", "101.226.30.206", "47.112.165.11"),
    "91.push2his.eastmoney.com": ("101.226.30.221", "61.129.129.199", "101.226.30.206", "47.112.165.11"),
}
_DNS_PATCH_LOCK = threading.Lock()
_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Encoding": "identity",
    "Referer": "https://quote.eastmoney.com/center/boardlist.html",
}

_BOARD_FS = {
    "concept": "m:90 t:3 f:!50",
    "industry": "m:90 t:2 f:!50",
}
_F10_EXCLUDE_KEYWORDS = (
    "板块",
    "大盘股",
    "小盘股",
    "中盘股",
    "大盘价值",
    "行业龙头",
    "周期股",
    "近期新高",
    "百日新高",
    "昨日",
    "最近",
    "标准普尔",
    "富时罗素",
    "MSCI",
    "沪股通",
    "深股通",
    "融资融券",
    "HS300",
    "上证",
    "深证",
    "深成",
    "创业板综",
    "机构重仓",
    "东方财富热股",
)


class EastMoneyRequestError(RuntimeError):
    pass


@contextmanager
def _force_dns(hostname: str, ip: str):
    original_getaddrinfo = socket.getaddrinfo

    def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if host == hostname:
            return original_getaddrinfo(ip, port, family, type, proto, flags)
        return original_getaddrinfo(host, port, family, type, proto, flags)

    with _DNS_PATCH_LOCK:
        socket.getaddrinfo = patched_getaddrinfo
        try:
            yield
        finally:
            socket.getaddrinfo = original_getaddrinfo


def _eastmoney_f10_code(ts_code: str) -> str:
    code = str(ts_code).split(".")[0]
    suffix = str(ts_code).split(".")[-1].upper() if "." in str(ts_code) else ""
    if suffix == "SH":
        return f"SH{code}"
    if suffix == "BJ":
        return f"BJ{code}"
    return f"SZ{code}"


def _board_code(raw: Any) -> str | None:
    text = str(raw or "").strip().upper()
    if not text:
        return None
    if text.startswith("BK"):
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    return f"BK{int(digits):04d}"


def _is_useful_f10_concept(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    return not any(keyword in text for keyword in _F10_EXCLUDE_KEYWORDS)


def _safe_float(v: Any) -> float | None:
    try:
        if v is None or pd.isna(v):
            return None
        if isinstance(v, str) and v.strip() in {"", "-", "--"}:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    try:
        if v is None or pd.isna(v):
            return None
        if isinstance(v, str) and v.strip() in {"", "-", "--"}:
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _first_value(row: pd.Series, names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row.index:
            v = row.get(name)
            if v is not None and not pd.isna(v):
                return v
    return None


def _em_get_json(hosts: tuple[str, ...], path: str, params: dict[str, Any], *, timeout: int = 8) -> dict[str, Any]:
    query = parse.urlencode(params, safe=",:! ")
    last_error: Exception | None = None
    for host in hosts:
        url = f"{host}{path}?{query}"
        host_name = parse.urlparse(host).hostname or ""
        host_forced_ips = _FORCED_HOST_IPS.get(host_name, ())
        forced_ips = (*host_forced_ips, None) if host_forced_ips else (None,)
        for forced_ip in forced_ips:
            req = request.Request(url, headers=_EM_HEADERS)
            for attempt in range(2):
                try:
                    ctx = _force_dns(host_name, forced_ip) if forced_ip else nullcontext()
                    with ctx:
                        with request.urlopen(req, timeout=timeout) as resp:
                            raw = resp.read()
                            if raw.startswith(b"\x1f\x8b"):
                                raw = gzip.decompress(raw)
                            text = raw.decode("utf-8")
                    data = json.loads(text)
                    if isinstance(data, dict):
                        return data
                    raise EastMoneyRequestError("unexpected JSON payload")
                except Exception as e:
                    last_error = e
                    time.sleep(0.25 * (attempt + 1))
    raise EastMoneyRequestError(str(last_error)[:240] if last_error else "request failed")


def _clist_page(fs: str, *, page: int, page_size: int, fields: str, fid: str = "f12") -> list[dict[str, Any]]:
    payload = _em_get_json(
        _CLIST_HOSTS,
        "/api/qt/clist/get",
        {
            "pn": page,
            "pz": page_size,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": fid,
            "fs": fs,
            "fields": fields,
        },
    )
    diff = ((payload.get("data") or {}).get("diff") or [])
    return diff if isinstance(diff, list) else []


def _fetch_clist_all(fs: str, *, fields: str, fid: str = "f12", page_size: int = 100, max_pages: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        batch = _clist_page(fs, page=page, page_size=page_size, fields=fields, fid=fid)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
    return rows


def _normalize_board_list_rows(rows: list[dict[str, Any]], sector_type: SectorType) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        raw_code = str(row.get("f12") or "").strip()
        sector_name = str(row.get("f14") or "").strip()
        if not raw_code or not sector_name:
            continue
        out.append(
            {
                "sector_code": raw_code,
                "sector_name": sector_name,
                "sector_type": sector_type,
                "source": SOURCE,
                "raw_code": raw_code,
                "rank": idx,
                "latest_pct_chg": _safe_float(row.get("f3")),
                "latest_hot": _safe_float(row.get("f62")),
            }
        )
    return out


def _normalize_board_list(df: pd.DataFrame, sector_type: SectorType) -> list[dict[str, Any]]:
    """Compatibility helper for tests and old AkShare-shaped dataframes."""
    if df is None or df.empty:
        return []
    out: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        name = _first_value(row, ("板块名称", "名称", "name"))
        raw_code = _first_value(row, ("板块代码", "代码", "code"))
        if not name or not raw_code:
            continue
        raw = str(raw_code).strip()
        out.append(
            {
                "sector_code": raw,
                "sector_name": str(name).strip(),
                "sector_type": sector_type,
                "source": SOURCE,
                "raw_code": raw,
                "rank": _safe_int(_first_value(row, ("排名", "序号", "rank"))) or idx + 1,
                "latest_pct_chg": _safe_float(_first_value(row, ("涨跌幅", "涨跌幅%", "pct_chg"))),
                "latest_hot": _safe_float(_first_value(row, ("热度", "hot"))),
            }
        )
    return out


def fetch_sector_list(sector_type: SectorType) -> list[dict[str, Any]]:
    if sector_type not in _BOARD_FS:
        raise ValueError(f"不支持的板块类型: {sector_type}")
    fields = "f2,f3,f4,f8,f12,f14,f20,f21,f62,f104,f105"
    rows = _fetch_clist_all(_BOARD_FS[sector_type], fields=fields)
    return _normalize_board_list_rows(rows, sector_type)


def fetch_stock_concept_sectors(ts_code: str) -> list[dict[str, Any]]:
    em_code = _eastmoney_f10_code(ts_code)
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code={em_code}"
    req = request.Request(
        url,
        headers={
            **_EM_HEADERS,
            "Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/Index?type=web&code={em_code}",
        },
    )
    with request.urlopen(req, timeout=8) as resp:
        body = resp.read()
        if body.startswith(b"\x1f\x8b"):
            body = gzip.decompress(body)
        raw = json.loads(body.decode("utf-8"))
    boards = raw.get("ssbk") if isinstance(raw, dict) else []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(boards or [], start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("BOARD_NAME") or "").strip()
        code = _board_code(item.get("BOARD_CODE"))
        if not name or not code or not _is_useful_f10_concept(name):
            continue
        if code in seen:
            continue
        seen.add(code)
        rows.append(
            {
                "sector_code": code,
                "sector_name": name,
                "sector_type": "concept",
                "source": SOURCE,
                "raw_code": code,
                "rank": idx,
                "latest_pct_chg": None,
                "latest_hot": None,
            }
        )
    return rows


def _normalize_ts_code_from_em(code: str, market: Any = None) -> str | None:
    code = str(code or "").strip()
    if not code:
        return None
    try:
        return normalize_ts_code(code)
    except Exception:
        pass
    market_text = str(market or "").strip()
    if market_text == "1":
        return f"{code}.SH"
    if market_text == "0":
        return f"{code}.SZ"
    if market_text == "81":
        return f"{code}.BJ"
    return None


def _normalize_cons_rows(rows: list[dict[str, Any]], sector: SectorBasic) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        ts_code = _normalize_ts_code_from_em(str(row.get("f12") or ""), row.get("f13"))
        if not ts_code:
            continue
        out.append(
            {
                "ts_code": ts_code,
                "sector_code": sector.sector_code,
                "sector_name": sector.sector_name,
                "sector_type": sector.sector_type,
                "source": sector.source,
            }
        )
    return out


def _normalize_cons_df(df: pd.DataFrame, sector: SectorBasic) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        code = _first_value(row, ("代码", "股票代码", "symbol", "code"))
        if not code:
            continue
        try:
            ts_code = normalize_ts_code(str(code).strip())
        except Exception:
            continue
        out.append(
            {
                "ts_code": ts_code,
                "sector_code": sector.sector_code,
                "sector_name": sector.sector_name,
                "sector_type": sector.sector_type,
                "source": sector.source,
            }
        )
    return out


def fetch_sector_constituents(sector: SectorBasic) -> list[dict[str, Any]]:
    if not sector.raw_code:
        return []
    fields = "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f62"
    rows = _fetch_clist_all(f"b:{sector.raw_code} f:!50", fields=fields)
    return _normalize_cons_rows(rows, sector)


def _normalize_kline_rows(rows: list[str], sector: SectorBasic) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in rows:
        parts = str(item).split(",")
        if len(parts) < 11:
            continue
        trade_date = pd.to_datetime(parts[0], errors="coerce")
        if pd.isna(trade_date):
            continue
        out.append(
            {
                "sector_code": sector.sector_code,
                "trade_date": trade_date.strftime("%Y%m%d"),
                "sector_name": sector.sector_name,
                "sector_type": sector.sector_type,
                "source": sector.source,
                "open": _safe_float(parts[1]),
                "close": _safe_float(parts[2]),
                "high": _safe_float(parts[3]),
                "low": _safe_float(parts[4]),
                "vol": _safe_float(parts[5]),
                "amount": _safe_float(parts[6]),
                "turnover_rate": _safe_float(parts[10]),
                "pct_chg": _safe_float(parts[8]),
                "change": _safe_float(parts[9]),
            }
        )
    return out


def _normalize_hist_df(df: pd.DataFrame, sector: SectorBasic) -> list[dict[str, Any]]:
    """Compatibility helper for tests and old AkShare-shaped dataframes."""
    if df is None or df.empty:
        return []
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        date_val = _first_value(row, ("日期", "trade_date", "date"))
        if not date_val:
            continue
        trade_date = pd.to_datetime(date_val, errors="coerce")
        if pd.isna(trade_date):
            continue
        out.append(
            {
                "sector_code": sector.sector_code,
                "trade_date": trade_date.strftime("%Y%m%d"),
                "sector_name": sector.sector_name,
                "sector_type": sector.sector_type,
                "source": sector.source,
                "open": _safe_float(_first_value(row, ("开盘", "open"))),
                "high": _safe_float(_first_value(row, ("最高", "high"))),
                "low": _safe_float(_first_value(row, ("最低", "low"))),
                "close": _safe_float(_first_value(row, ("收盘", "close"))),
                "pct_chg": _safe_float(_first_value(row, ("涨跌幅", "pct_chg"))),
                "change": _safe_float(_first_value(row, ("涨跌额", "change"))),
                "vol": _safe_float(_first_value(row, ("成交量", "vol", "volume"))),
                "amount": _safe_float(_first_value(row, ("成交额", "amount"))),
                "turnover_rate": _safe_float(_first_value(row, ("换手率", "turnover_rate"))),
            }
        )
    return out


def fetch_sector_daily_quotes(sector: SectorBasic, start_date: str, end_date: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    raw_code = sector.raw_code or sector.sector_code
    if not raw_code:
        return []
    period_map = {"concept": "101", "industry": "101"}
    params = {
        "secid": f"90.{raw_code}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": period_map.get(str(sector.sector_type), "101"),
        "fqt": 1,
        "beg": start_date,
        "end": end_date,
        "lmt": limit or 1000000,
    }
    payload = _em_get_json(_KLINE_HOSTS, "/api/qt/stock/kline/get", params)
    klines = ((payload.get("data") or {}).get("klines") or [])
    rows = _normalize_kline_rows(klines, sector)
    if limit is not None and limit > 0:
        rows = rows[-limit:]
    return rows


def upsert_sector_basic(db: Session, rows: list[dict[str, Any]]) -> int:
    changed = 0
    now = datetime.utcnow()
    for item in rows:
        row = db.query(SectorBasic).filter(SectorBasic.sector_code == item["sector_code"]).first()
        if row:
            for key, value in item.items():
                setattr(row, key, value)
            row.updated_at = now
        else:
            row = SectorBasic(**item)
            db.add(row)
        changed += 1
    db.commit()
    return changed


def upsert_stock_sector_map(db: Session, rows: list[dict[str, Any]]) -> int:
    changed = 0
    now = datetime.utcnow()
    for item in rows:
        mapped = {
            "ts_code": item["ts_code"],
            "sector_code": item["sector_code"],
            "sector_name": item["sector_name"],
            "sector_type": item.get("sector_type", "concept"),
            "source": item.get("source", SOURCE),
            "weight": item.get("weight"),
        }
        row = (
            db.query(StockSectorMap)
            .filter(
                StockSectorMap.ts_code == mapped["ts_code"],
                StockSectorMap.sector_code == mapped["sector_code"],
                StockSectorMap.source == mapped["source"],
            )
            .first()
        )
        if row:
            row.sector_name = mapped["sector_name"]
            row.sector_type = mapped["sector_type"]
            row.weight = mapped.get("weight", row.weight)
            row.updated_at = now
        else:
            db.add(StockSectorMap(**mapped))
        changed += 1
    db.commit()
    return changed


def upsert_sector_daily_quotes(db: Session, rows: list[dict[str, Any]]) -> int:
    changed = 0
    now = datetime.utcnow()
    for item in rows:
        row = (
            db.query(SectorDailyQuote)
            .filter(
                SectorDailyQuote.sector_code == item["sector_code"],
                SectorDailyQuote.trade_date == item["trade_date"],
            )
            .first()
        )
        if row:
            for key, value in item.items():
                setattr(row, key, value)
            row.updated_at = now
        else:
            db.add(SectorDailyQuote(**item))
        changed += 1
    db.commit()
    return changed


def sector_quote_coverage(db: Session, sector_code: str) -> dict[str, Any]:
    rows = (
        db.query(SectorDailyQuote.trade_date)
        .filter(SectorDailyQuote.sector_code == sector_code)
        .order_by(SectorDailyQuote.trade_date.asc())
        .all()
    )
    dates = [r[0] for r in rows if r[0]]
    return {
        "quote_count": len(dates),
        "first_trade_date": dates[0] if dates else None,
        "last_trade_date": dates[-1] if dates else None,
    }


def get_or_create_quote_sync_state(db: Session, sector: SectorBasic, *, target_days: int | None = None) -> SectorQuoteSyncState:
    row = (
        db.query(SectorQuoteSyncState)
        .filter(
            SectorQuoteSyncState.sector_code == sector.sector_code,
            SectorQuoteSyncState.source == sector.source,
        )
        .first()
    )
    now = datetime.utcnow()
    if row is None:
        row = SectorQuoteSyncState(
            sector_code=sector.sector_code,
            sector_name=sector.sector_name,
            sector_type=sector.sector_type,
            source=sector.source,
            status="pending",
            target_days=target_days,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    else:
        row.sector_name = sector.sector_name
        row.sector_type = sector.sector_type
        row.target_days = target_days if target_days is not None else row.target_days
        row.updated_at = now
        db.commit()
        db.refresh(row)
    return row


def refresh_quote_sync_state(
    db: Session,
    sector: SectorBasic,
    *,
    status: str | None = None,
    target_days: int | None = None,
    last_error: str | None = None,
    next_retry_at: datetime | None = None,
    reset_attempts: bool = False,
    increment_attempts: bool = False,
) -> SectorQuoteSyncState:
    row = get_or_create_quote_sync_state(db, sector, target_days=target_days)
    coverage = sector_quote_coverage(db, sector.sector_code)
    row.quote_count = int(coverage["quote_count"])
    row.first_trade_date = coverage["first_trade_date"]
    row.last_trade_date = coverage["last_trade_date"]
    if status:
        row.status = status
    if target_days is not None:
        row.target_days = target_days
    if reset_attempts:
        row.attempts = 0
    if increment_attempts:
        row.attempts = int(row.attempts or 0) + 1
    if last_error is not None:
        row.last_error = last_error
    if next_retry_at is not None:
        row.next_retry_at = next_retry_at
    if status == "success":
        row.last_error = None
        row.next_retry_at = None
    if status == "success":
        row.last_success_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def sync_sector_data(
    db: Session,
    *,
    sector_types: list[SectorType] | None = None,
    sync_constituents: bool = True,
    sync_quotes: bool = True,
    days: int = 180,
    limit: int | None = 30,
) -> dict[str, Any]:
    types = sector_types or ["concept", "industry"]
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=max(days, 1) * 2)).strftime("%Y%m%d")
    result: dict[str, Any] = {
        "source": SOURCE,
        "sector_types": types,
        "sector_count": 0,
        "constituent_count": 0,
        "quote_count": 0,
        "failed": [],
    }

    for sector_type in types:
        try:
            result["sector_count"] += upsert_sector_basic(db, fetch_sector_list(sector_type))
        except Exception as e:
            msg = f"{sector_type} list: {str(e)[:160]}"
            logger.warning("sync_sector_data %s", msg)
            result["failed"].append(msg)

    sectors_q = db.query(SectorBasic).filter(SectorBasic.source == SOURCE)
    if types:
        sectors_q = sectors_q.filter(SectorBasic.sector_type.in_(types))
    sectors_q = sectors_q.order_by(SectorBasic.rank.asc().nullslast(), SectorBasic.sector_name.asc())
    if limit is not None and limit > 0:
        sectors_q = sectors_q.limit(limit)
    sectors = sectors_q.all()

    for sector in sectors:
        if sync_constituents:
            try:
                result["constituent_count"] += upsert_stock_sector_map(db, fetch_sector_constituents(sector))
            except Exception as e:
                msg = f"{sector.sector_name} constituents: {str(e)[:160]}"
                logger.warning("sync_sector_data %s", msg)
                result["failed"].append(msg)
        if sync_quotes:
            try:
                result["quote_count"] += upsert_sector_daily_quotes(
                    db,
                    fetch_sector_daily_quotes(sector, start_date=start_date, end_date=end_date),
                )
            except Exception as e:
                msg = f"{sector.sector_name} quotes: {str(e)[:160]}"
                logger.warning("sync_sector_data %s", msg)
                result["failed"].append(msg)

    return result
