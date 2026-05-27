from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.message import MessageEntity, MessageRelation
from app.schemas.industry_report import (
    GraphEntityOut,
    GraphExtractOut,
    GraphExtractRequest,
    GraphPathOut,
    GraphRelationOut,
    GraphSeedImportOut,
)
from app.services.message_extraction_service import extract_source_items_for_date
from app.services.message_graph_service import find_paths, import_seed_graph

router = APIRouter(prefix="/api/message-graph", tags=["message-graph"])


@router.post("/import-seeds", response_model=GraphSeedImportOut)
def import_seeds(db: Session = Depends(get_db)):
    return import_seed_graph(db)


@router.post("/extract", response_model=GraphExtractOut)
def extract_relations(body: GraphExtractRequest, db: Session = Depends(get_db)):
    return extract_source_items_for_date(
        db,
        trade_date=body.trade_date,
        limit=body.limit,
        provider=body.provider,
        model=body.model,
    )


@router.get("/entities", response_model=list[GraphEntityOut])
def list_entities(
    q: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(MessageEntity).filter(MessageEntity.status == "active")
    if q:
        query = query.filter(MessageEntity.name.ilike(f"%{q}%"))
    if entity_type:
        query = query.filter(MessageEntity.entity_type == entity_type)
    return query.order_by(MessageEntity.entity_type.asc(), MessageEntity.name.asc()).limit(limit).all()


@router.get("/relations", response_model=list[GraphRelationOut])
def list_relations(
    relation_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db),
):
    query = db.query(MessageRelation).filter(MessageRelation.status == "active")
    if relation_type:
        query = query.filter(MessageRelation.relation_type == relation_type)
    return query.order_by(MessageRelation.updated_at.desc()).limit(limit).all()


@router.get("/paths", response_model=list[GraphPathOut])
def get_paths(
    entity: str = Query(..., min_length=1),
    max_depth: int = Query(default=3, ge=1, le=4),
    db: Session = Depends(get_db),
):
    return find_paths(db, entity, max_depth=max_depth)
