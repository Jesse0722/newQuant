import csv
import io
from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.pool import WatchPool, WatchStock
from app.models.stock import StockBasic
from app.schemas.pool import (
    PoolCreate, PoolUpdate, PoolOut,
    WatchStockCreate, WatchStockUpdate, WatchStockOut,
    CSVImportResult,
)
from app.exceptions import AppError

router = APIRouter(prefix="/api/pools", tags=["pools"])


@router.get("", response_model=list[PoolOut])
def list_pools(db: Session = Depends(get_db)):
    pools = db.query(WatchPool).order_by(WatchPool.created_at.desc()).all()
    result = []
    for p in pools:
        count = db.query(func.count(WatchStock.id)).filter(WatchStock.pool_id == p.id).scalar()
        out = PoolOut.model_validate(p)
        out.stock_count = count
        result.append(out)
    return result


@router.post("", response_model=PoolOut, status_code=201)
def create_pool(body: PoolCreate, db: Session = Depends(get_db)):
    pool = WatchPool(**body.model_dump())
    db.add(pool)
    db.commit()
    db.refresh(pool)
    out = PoolOut.model_validate(pool)
    out.stock_count = 0
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


@router.get("/{pool_id}/stocks", response_model=list[WatchStockOut])
def list_stocks(
    pool_id: str,
    keyword: str = Query(None),
    monitor_status: str = Query(None),
    db: Session = Depends(get_db),
):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    q = db.query(WatchStock).filter(WatchStock.pool_id == pool_id)
    if monitor_status:
        q = q.filter(WatchStock.monitor_status == monitor_status)
    stocks = q.order_by(WatchStock.created_at.desc()).all()
    result = []
    for s in stocks:
        basic = db.query(StockBasic).filter(StockBasic.ts_code == s.ts_code).first()
        out = WatchStockOut.model_validate(s)
        out.stock_name = basic.name if basic else None
        if keyword and keyword.lower() not in (s.ts_code + (out.stock_name or "")).lower():
            continue
        result.append(out)
    return result


@router.post("/{pool_id}/stocks", response_model=WatchStockOut, status_code=201)
def add_stock(pool_id: str, body: WatchStockCreate, db: Session = Depends(get_db)):
    pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    if not pool:
        raise AppError(code=2001, message="观察池不存在", status_code=404)
    existing = db.query(WatchStock).filter(
        WatchStock.pool_id == pool_id, WatchStock.ts_code == body.ts_code
    ).first()
    if existing:
        raise AppError(code=2002, message="股票已在观察池中")
    stock = WatchStock(pool_id=pool_id, **body.model_dump())
    db.add(stock)
    db.commit()
    db.refresh(stock)
    basic = db.query(StockBasic).filter(StockBasic.ts_code == stock.ts_code).first()
    out = WatchStockOut.model_validate(stock)
    out.stock_name = basic.name if basic else None
    return out


@router.put("/{pool_id}/stocks/{stock_id}", response_model=WatchStockOut)
def update_stock(pool_id: str, stock_id: str, body: WatchStockUpdate, db: Session = Depends(get_db)):
    stock = db.query(WatchStock).filter(WatchStock.id == stock_id, WatchStock.pool_id == pool_id).first()
    if not stock:
        raise AppError(code=2001, message="股票不存在", status_code=404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(stock, k, v)
    db.commit()
    db.refresh(stock)
    basic = db.query(StockBasic).filter(StockBasic.ts_code == stock.ts_code).first()
    out = WatchStockOut.model_validate(stock)
    out.stock_name = basic.name if basic else None
    return out


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
    for i, row in enumerate(reader):
        ts_code = row.get("ts_code") or row.get("股票代码") or row.get("code")
        if not ts_code:
            result.errors.append(f"第 {i+1} 行缺少股票代码")
            continue
        ts_code = ts_code.strip()
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
    db.commit()
    return result
