import csv
import io
from fastapi import APIRouter, Depends, UploadFile, File, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.pool import WatchPool, WatchStock
from app.models.stock import StockBasic, DailyQuote
from app.schemas.pool import (
    PoolCreate, PoolUpdate, PoolOut,
    WatchStockCreate, WatchStockUpdate, WatchStockOut, WatchStockPagination,
    CSVImportResult, BatchAddStocks, BatchAddResult, QuickCreatePool,
    CoreWatchCodesOut, CoreWatchToggleBody, CoreWatchToggleOut,
)
from app.services.core_watch_service import list_core_watch_ts_codes, toggle_core_watch_star
from app.exceptions import AppError
from app.utils import normalize_ts_code
from app.services.sync_service import sync_single_stock
from app.tasks.background import submit_task

router = APIRouter(prefix="/api/pools", tags=["pools"])


def _enrich_stock(db: Session, stock: WatchStock) -> WatchStockOut:
    basic = db.query(StockBasic).filter(StockBasic.ts_code == stock.ts_code).first()
    latest = db.query(DailyQuote).filter(
        DailyQuote.ts_code == stock.ts_code
    ).order_by(DailyQuote.trade_date.desc()).first()
    out = WatchStockOut.model_validate(stock)
    out.stock_name = basic.name if basic else None
    out.industry = basic.industry if basic else None
    if latest:
        out.latest_price = latest.close
        out.pct_chg = latest.pct_chg
        out.trade_date = latest.trade_date
    return out


@router.get("", response_model=list[PoolOut])
def list_pools(db: Session = Depends(get_db)):
    pools = db.query(WatchPool).order_by(WatchPool.sort_order.asc(), WatchPool.created_at.desc()).all()
    result = []
    for p in pools:
        count = db.query(func.count(WatchStock.id)).filter(WatchStock.pool_id == p.id).scalar()
        out = PoolOut.model_validate(p)
        out.stock_count = count
        result.append(out)
    return result


@router.get("/all-stocks")
def list_all_stocks(
    keyword: str = Query(None),
    db: Session = Depends(get_db),
):
    """所有观察池股票（扁平列表），支持 keyword 按名称/代码模糊搜索"""
    q = db.query(WatchStock, WatchPool).join(WatchPool, WatchStock.pool_id == WatchPool.id)
    rows = q.order_by(WatchPool.name, WatchStock.ts_code).all()
    result = []
    for ws, pool in rows:
        basic = db.query(StockBasic).filter(StockBasic.ts_code == ws.ts_code).first()
        stock_name = basic.name if basic else None
        if keyword:
            kw = keyword.lower()
            if kw not in (ws.ts_code or "").lower() and kw not in (stock_name or "").lower():
                continue
        result.append({
            "ts_code": ws.ts_code,
            "stock_name": stock_name,
            "pool_id": pool.id,
            "pool_name": pool.name,
        })
    return result


@router.put("/reorder")
def reorder_pools(body: dict = Body(...), db: Session = Depends(get_db)):
    """拖拽排序：body 为 { "pool_ids": ["id1", "id2", ...] }"""
    pool_ids = body.get("pool_ids") or []
    if not pool_ids:
        return {"ok": True}
    for i, pid in enumerate(pool_ids):
        pool = db.query(WatchPool).filter(WatchPool.id == pid).first()
        if pool:
            pool.sort_order = i
    db.commit()
    return {"ok": True}


@router.get("/core-watch/codes", response_model=CoreWatchCodesOut)
def get_core_watch_codes(db: Session = Depends(get_db)):
    """买点雷达：获取「核心关注」池内股票代码（池不存在则 pool_id 为空）"""
    pool_id, ts_codes = list_core_watch_ts_codes(db)
    return CoreWatchCodesOut(pool_id=pool_id, ts_codes=ts_codes)


@router.post("/core-watch/toggle", response_model=CoreWatchToggleOut)
def core_watch_toggle(body: CoreWatchToggleBody, db: Session = Depends(get_db)):
    """买点雷达特别关注：加星加入核心关注池，取消星标则移除"""
    try:
        result = toggle_core_watch_star(
            db,
            body.ts_code,
            body.starred,
            limit_up_date=body.limit_up_date,
        )
        return CoreWatchToggleOut(**result)
    except ValueError as e:
        raise AppError(code=2003, message=str(e))


@router.post("", response_model=PoolOut, status_code=201)
def create_pool(body: PoolCreate, db: Session = Depends(get_db)):
    max_order = db.query(func.max(WatchPool.sort_order)).scalar() or -1
    pool = WatchPool(**body.model_dump(), sort_order=max_order + 1)
    db.add(pool)
    db.commit()
    db.refresh(pool)
    out = PoolOut.model_validate(pool)
    out.stock_count = 0
    return out


@router.post("/quick-create", response_model=PoolOut, status_code=201)
def quick_create_pool(body: QuickCreatePool, db: Session = Depends(get_db)):
    """快捷创建观察池并批量添加股票"""
    max_order = db.query(func.max(WatchPool.sort_order)).scalar() or -1
    pool = WatchPool(name=body.name, description=body.description, sort_order=max_order + 1)
    db.add(pool)
    db.commit()
    db.refresh(pool)
    added = 0
    for ts_code in body.ts_codes:
        try:
            code = normalize_ts_code(ts_code)
        except ValueError:
            continue
        existing = db.query(WatchStock).filter(
            WatchStock.pool_id == pool.id, WatchStock.ts_code == code
        ).first()
        if existing:
            continue
        stock = WatchStock(pool_id=pool.id, ts_code=code, source="strategy")
        db.add(stock)
        added += 1
    db.commit()
    for ws in db.query(WatchStock).filter(WatchStock.pool_id == pool.id).all():
        submit_task("sync", sync_single_stock, ws.ts_code)
    count = db.query(func.count(WatchStock.id)).filter(WatchStock.pool_id == pool.id).scalar()
    out = PoolOut.model_validate(pool)
    out.stock_count = count
    return out


@router.get("/{pool_id}", response_model=PoolOut)
def get_pool(pool_id: str, db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    count = db.query(func.count(WatchStock.id)).filter(WatchStock.pool_id == pool.id).scalar()
    out = PoolOut.model_validate(pool)
    out.stock_count = count
    return out


@router.put("/{pool_id}", response_model=PoolOut)
def update_pool(pool_id: str, body: PoolUpdate, db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(pool, k, v)
    db.commit()
    db.refresh(pool)
    count = db.query(func.count(WatchStock.id)).filter(WatchStock.pool_id == pool.id).scalar()
    out = PoolOut.model_validate(pool)
    out.stock_count = count
    return out


@router.delete("/{pool_id}", status_code=204)
def delete_pool(pool_id: str, db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    db.delete(pool)
    db.commit()


@router.get("/{pool_id}/stocks", response_model=WatchStockPagination)
def list_stocks(
    pool_id: str,
    keyword: str = Query(None),
    monitor_status: str = Query(None),
    limit_up_date_from: str = Query(None, description="涨停日期起 YYYYMMDD"),
    limit_up_date_to: str = Query(None, description="涨停日期止 YYYYMMDD"),
    sort_by: str = Query("created_at", description="排序字段: created_at | limit_up_date"),
    order: str = Query("desc", description="排序方向: asc | desc"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    q = db.query(WatchStock).filter(WatchStock.pool_id == pool_id)
    if monitor_status:
        q = q.filter(WatchStock.monitor_status == monitor_status)
    if limit_up_date_from:
        q = q.filter(WatchStock.limit_up_date >= limit_up_date_from)
    if limit_up_date_to:
        q = q.filter(WatchStock.limit_up_date <= limit_up_date_to)
    stocks = q.all()
    result = []
    for s in stocks:
        out = _enrich_stock(db, s)
        if keyword and keyword.lower() not in (s.ts_code + (out.stock_name or "")).lower():
            continue
        result.append(out)
    # 排序：置顶优先，再按指定字段
    rev = order == "desc"
    null_val = "00000000" if rev else "99999999"
    if sort_by == "limit_up_date":
        result.sort(key=lambda x: (x.limit_up_date or null_val), reverse=rev)
    else:
        result.sort(key=lambda x: str(x.created_at or ""), reverse=rev)
    result.sort(key=lambda x: x.pinned, reverse=True)  # 置顶优先，稳定排序
    total = len(result)
    offset = (page - 1) * size
    items = result[offset : offset + size]
    return WatchStockPagination(items=items, total=total)


@router.post("/{pool_id}/stocks", response_model=WatchStockOut, status_code=201)
def add_stock(pool_id: str, body: WatchStockCreate, db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    try:
        ts_code = normalize_ts_code(body.ts_code)
    except ValueError as e:
        raise AppError(code=2003, message=str(e))
    existing = db.query(WatchStock).filter(
        WatchStock.pool_id == pool_id, WatchStock.ts_code == ts_code
    ).first()
    if existing:
        raise AppError(code=2002, message="股票已在观察池中")
    data = body.model_dump()
    data["ts_code"] = ts_code
    stock = WatchStock(pool_id=pool_id, **data)
    db.add(stock)
    db.commit()
    db.refresh(stock)
    out = _enrich_stock(db, stock)
    submit_task("sync", sync_single_stock, ts_code)
    return out


@router.post("/{pool_id}/stocks/batch", response_model=BatchAddResult)
def batch_add_stocks(pool_id: str, body: BatchAddStocks, db: Session = Depends(get_db)):
    """批量添加股票到观察池（策略选股结果）"""
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    result = BatchAddResult()
    added_codes = []
    for ts_code in body.ts_codes:
        try:
            code = normalize_ts_code(ts_code)
        except ValueError as e:
            result.errors.append(f"{ts_code}: {e}")
            continue
        existing = db.query(WatchStock).filter(
            WatchStock.pool_id == pool_id, WatchStock.ts_code == code
        ).first()
        if existing:
            result.skipped += 1
            continue
        stock = WatchStock(
            pool_id=pool_id, ts_code=code, source="strategy",
            added_price=body.added_price, note=body.note,
        )
        db.add(stock)
        result.added += 1
        added_codes.append(code)
    db.commit()
    for code in added_codes:
        submit_task("sync", sync_single_stock, code)
    return result


@router.put("/{pool_id}/stocks/{stock_id}", response_model=WatchStockOut)
def update_stock(pool_id: str, stock_id: str, body: WatchStockUpdate, db: Session = Depends(get_db)):
    stock = db.query(WatchStock).filter(WatchStock.id == stock_id, WatchStock.pool_id == pool_id).first()
    if not stock:
        raise AppError(code=2001, message="股票不存在", status_code=404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(stock, k, v)
    db.commit()
    db.refresh(stock)
    return _enrich_stock(db, stock)


@router.delete("/{pool_id}/stocks/{stock_id}", status_code=204)
def delete_stock(pool_id: str, stock_id: str, db: Session = Depends(get_db)):
    stock = db.query(WatchStock).filter(WatchStock.id == stock_id, WatchStock.pool_id == pool_id).first()
    if not stock:
        raise AppError(code=2001, message="股票不存在", status_code=404)
    db.delete(stock)
    db.commit()


@router.post("/{pool_id}/stocks/import", response_model=CSVImportResult)
async def import_csv(pool_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("gbk")
    reader = csv.DictReader(io.StringIO(text))
    result = CSVImportResult()
    imported_codes: list[str] = []
    for i, raw_row in enumerate(reader):
        row = {k.strip(): v.strip() if v else v for k, v in raw_row.items() if k}
        ts_code = row.get("ts_code") or row.get("股票代码") or row.get("code")
        if not ts_code:
            result.errors.append(f"第 {i+1} 行缺少股票代码")
            continue
        try:
            ts_code = normalize_ts_code(ts_code)
        except ValueError:
            result.errors.append(f"第 {i+1} 行股票代码无效：{ts_code}")
            continue
        existing = db.query(WatchStock).filter(
            WatchStock.pool_id == pool_id, WatchStock.ts_code == ts_code
        ).first()
        if existing:
            result.skipped += 1
            continue
        added_price = None
        price_str = row.get("added_price") or row.get("加入价格") or row.get("price")
        if price_str:
            try:
                added_price = float(price_str)
            except ValueError:
                pass
        note = row.get("note") or row.get("备注") or ""
        stock = WatchStock(
            pool_id=pool_id, ts_code=ts_code,
            added_price=added_price, note=note or None,
            source="csv",
        )
        db.add(stock)
        result.imported += 1
        imported_codes.append(ts_code)
    db.commit()
    for code in imported_codes:
        submit_task("sync", sync_single_stock, code)
    return result
