from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from app.config import X_API_BASE_URL, X_API_BEARER_TOKEN
from app.exceptions import AppError
from app.models.message import MessageKeywordSeed
from app.schemas.message import (
    MessageKeywordImportOut,
    MessageKeywordImportRequest,
    MessageSeedKeywordCreate,
    MessageSourceImportRequest,
    MessageSourceImportOut,
    MessageSourceItemCreate,
    MessageXAccountOut,
    MessageXCollectOut,
    MessageXCollectRequest,
    MessageXSeedSummaryOut,
    MessageSeedKeywordOut,
)
from app.services.message_service import import_source_items, today_yyyymmdd

SEED_DIR = Path(__file__).resolve().parent.parent / "seeds"
KEYWORDS_CSV = SEED_DIR / "message_keywords.csv"
X_ACCOUNTS_CSV = SEED_DIR / "message_x_accounts.csv"
X_STOCK_MAPPINGS_CSV = SEED_DIR / "message_x_stock_mappings.csv"

SPAM_PATTERNS = (
    "best trading decision",
    "steady, consistent profits",
    "join my discord",
    "telegram",
    "whatsapp",
    "giveaway",
    "airdrop",
    "free signals",
    "pump",
    "100x",
    "guaranteed profit",
)

LOW_VALUE_PATTERNS = (
    "follow me",
    "subscribe",
    "dm me",
)


@dataclass(frozen=True)
class KeywordSeed:
    keyword: str
    type: str
    theme: str
    priority: int
    language: str


@dataclass(frozen=True)
class XAccountSeed:
    handle: str
    platform: str
    category: str
    theme: str
    weight: float
    status: str


@dataclass(frozen=True)
class XStockMapping:
    trigger: str
    theme: str
    ts_code: str
    stock_name: str
    weight: float
    tags: list[str]


def load_keyword_csv_seeds() -> list[KeywordSeed]:
    with KEYWORDS_CSV.open("r", encoding="utf-8", newline="") as fp:
        return [
            KeywordSeed(
                keyword=row["keyword"].strip(),
                type=row["type"].strip(),
                theme=row["theme"].strip(),
                priority=int(row["priority"]),
                language=row["language"].strip(),
            )
            for row in csv.DictReader(fp)
            if row.get("keyword")
        ]


def _keyword_seed_from_model(row: MessageKeywordSeed) -> KeywordSeed:
    return KeywordSeed(
        keyword=row.keyword,
        type=row.type,
        theme=row.theme,
        priority=row.priority,
        language=row.language,
    )


def load_keyword_seeds(db: Session | None = None) -> list[KeywordSeed]:
    if db is not None:
        rows = (
            db.query(MessageKeywordSeed)
            .order_by(MessageKeywordSeed.priority.desc(), MessageKeywordSeed.theme.asc(), MessageKeywordSeed.keyword.asc())
            .all()
        )
        if rows:
            return [_keyword_seed_from_model(row) for row in rows if row.status == "active"]
    return load_keyword_csv_seeds()


def _keyword_out(row: MessageKeywordSeed) -> MessageSeedKeywordOut:
    return MessageSeedKeywordOut(
        id=row.id,
        keyword=row.keyword,
        type=row.type,
        theme=row.theme,
        priority=row.priority,
        language=row.language,
        status=row.status,
    )


def import_keyword_seeds(db: Session, body: MessageKeywordImportRequest) -> MessageKeywordImportOut:
    created = 0
    updated = 0
    skipped = 0
    rows: list[MessageKeywordSeed] = []
    for item in body.items:
        keyword = item.keyword.strip()
        keyword_type = item.type.strip()
        theme = item.theme.strip()
        language = item.language.strip().lower()
        status = item.status.strip().lower() or "active"
        if not keyword or not keyword_type or not theme or not language:
            skipped += 1
            continue

        row = (
            db.query(MessageKeywordSeed)
            .filter(
                MessageKeywordSeed.keyword == keyword,
                MessageKeywordSeed.type == keyword_type,
                MessageKeywordSeed.theme == theme,
                MessageKeywordSeed.language == language,
            )
            .first()
        )
        values = {
            "keyword": keyword,
            "type": keyword_type,
            "theme": theme,
            "priority": item.priority,
            "language": language,
            "status": status,
        }
        if row:
            changed = any(getattr(row, key) != value for key, value in values.items())
            for key, value in values.items():
                setattr(row, key, value)
            updated += 1 if changed else 0
            skipped += 0 if changed else 1
        else:
            row = MessageKeywordSeed(**values)
            db.add(row)
            created += 1
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)
    return MessageKeywordImportOut(
        created_count=created,
        updated_count=updated,
        skipped_count=skipped,
        items=[_keyword_out(row) for row in rows],
    )


def save_keyword_seed(db: Session, body: MessageSeedKeywordCreate) -> MessageSeedKeywordOut:
    result = import_keyword_seeds(db, MessageKeywordImportRequest(items=[body]))
    if not result.items:
        raise AppError(code=5103, message="关键词保存失败", detail="没有生成可保存的关键词记录", status_code=400)
    return result.items[0]


def import_default_keyword_seeds(db: Session) -> MessageKeywordImportOut:
    return import_keyword_seeds(
        db,
        MessageKeywordImportRequest(
            items=[
                MessageSeedKeywordCreate(
                    keyword=seed.keyword,
                    type=seed.type,
                    theme=seed.theme,
                    priority=seed.priority,
                    language=seed.language,
                    status="active",
                )
                for seed in load_keyword_csv_seeds()
            ]
        ),
    )


def list_keyword_seed_rows(db: Session) -> list[MessageSeedKeywordOut]:
    rows = (
        db.query(MessageKeywordSeed)
        .order_by(MessageKeywordSeed.priority.desc(), MessageKeywordSeed.theme.asc(), MessageKeywordSeed.keyword.asc())
        .all()
    )
    return [_keyword_out(row) for row in rows]


def load_x_account_seeds() -> list[XAccountSeed]:
    with X_ACCOUNTS_CSV.open("r", encoding="utf-8", newline="") as fp:
        return [
            XAccountSeed(
                handle=row["handle"].strip(),
                platform=row["platform"].strip(),
                category=row["category"].strip(),
                theme=row["theme"].strip(),
                weight=float(row["weight"]),
                status=row["status"].strip(),
            )
            for row in csv.DictReader(fp)
            if row.get("handle")
        ]


def load_x_stock_mappings() -> list[XStockMapping]:
    with X_STOCK_MAPPINGS_CSV.open("r", encoding="utf-8", newline="") as fp:
        return [
            XStockMapping(
                trigger=row["trigger"].strip(),
                theme=row["theme"].strip(),
                ts_code=row["ts_code"].strip(),
                stock_name=row["stock_name"].strip(),
                weight=float(row["weight"]),
                tags=[item.strip() for item in (row.get("tags") or "").split("|") if item.strip()],
            )
            for row in csv.DictReader(fp)
            if row.get("trigger") and row.get("ts_code")
        ]


def get_x_seed_summary(db: Session | None = None) -> MessageXSeedSummaryOut:
    keywords = load_keyword_seeds(db)
    accounts = load_x_account_seeds()
    themes: list[str] = []
    for seed in sorted(keywords, key=lambda item: (-item.priority, item.theme, item.keyword)):
        if seed.theme not in themes:
            themes.append(seed.theme)
    return MessageXSeedSummaryOut(
        keyword_count=len(keywords),
        account_count=len(accounts),
        top_themes=themes[:12],
        keywords=[MessageSeedKeywordOut(**seed.__dict__) for seed in keywords],
        accounts=[MessageXAccountOut(**account.__dict__) for account in accounts],
    )


def build_x_recent_search_query(
    min_priority: int = 5,
    keyword_limit: int = 12,
    keyword_seeds: list[KeywordSeed] | None = None,
) -> str:
    seeds = [
        seed
        for seed in (keyword_seeds or load_keyword_seeds())
        if seed.priority >= min_priority and seed.language in {"en", "zh"}
    ]
    seeds = sorted(seeds, key=lambda item: (-item.priority, item.language, item.keyword))[:keyword_limit]
    terms = [f'"{seed.keyword}"' if " " in seed.keyword else seed.keyword for seed in seeds]
    # Keep the first X integration focused on original, text-bearing posts.
    return f"({' OR '.join(terms)}) -is:retweet -is:reply"


def _fetch_x_recent_search(query: str, max_results: int) -> dict[str, Any]:
    if not X_API_BEARER_TOKEN:
        raise AppError(
            code=5101,
            message="X_API_BEARER_TOKEN 未配置",
            detail="请在 backend/.env 设置 X_API_BEARER_TOKEN 后再执行 X 采集。",
            status_code=400,
        )

    params = {
        "query": query,
        "max_results": max_results,
        "tweet.fields": "created_at,lang,public_metrics,author_id",
        "expansions": "author_id",
        "user.fields": "username,name,verified",
    }
    url = f"{X_API_BASE_URL}/2/tweets/search/recent?{urlencode(params)}"
    request = Request(url, headers={"Authorization": f"Bearer {X_API_BEARER_TOKEN}"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise AppError(code=5102, message="X 采集失败", detail=str(exc), status_code=502) from exc


def _match_keyword(text: str, keyword_seeds: list[KeywordSeed] | None = None) -> KeywordSeed | None:
    lower_text = text.lower()
    candidates = sorted(keyword_seeds or load_keyword_seeds(), key=lambda item: (-item.priority, -len(item.keyword)))
    for seed in candidates:
        if seed.keyword.lower() in lower_text:
            return seed
    return None


def _match_stock_mappings(text: str) -> list[XStockMapping]:
    lower_text = text.lower()
    matches: list[XStockMapping] = []
    seen: set[tuple[str, str]] = set()
    for mapping in sorted(load_x_stock_mappings(), key=lambda item: (-item.weight, -len(item.trigger))):
        if mapping.trigger.lower() not in lower_text:
            continue
        key = (mapping.theme, mapping.ts_code)
        if key in seen:
            continue
        matches.append(mapping)
        seen.add(key)
    return matches[:3]


def _text_quality_score(text: str, metrics: dict[str, Any] | None) -> int:
    normalized = " ".join(text.split())
    lower_text = normalized.lower()
    score = 60
    word_count = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", normalized))
    url_count = len(re.findall(r"https?://|t\.co/", lower_text))
    hashtag_count = lower_text.count("#")
    cashtag_count = lower_text.count("$")

    if word_count < 6:
        score -= 35
    elif word_count < 12:
        score -= 12
    if len(normalized) >= 120:
        score += 10
    if len(normalized) >= 220:
        score += 8

    if any(pattern in lower_text for pattern in SPAM_PATTERNS):
        score -= 60
    if any(pattern in lower_text for pattern in LOW_VALUE_PATTERNS):
        score -= 20
    if url_count >= 2:
        score -= 12
    if hashtag_count >= 4:
        score -= 20
    if cashtag_count >= 5:
        score -= 15
    if re.search(r"(.)\1{5,}", normalized):
        score -= 12

    metrics = metrics or {}
    engagement = (
        int(metrics.get("like_count") or 0)
        + int(metrics.get("retweet_count") or 0) * 2
        + int(metrics.get("reply_count") or 0)
        + int(metrics.get("quote_count") or 0) * 2
    )
    if engagement >= 20:
        score += 8
    if engagement >= 100:
        score += 8

    return max(0, min(100, score))


def _is_low_quality_post(text: str, metrics: dict[str, Any] | None) -> bool:
    return _text_quality_score(text, metrics) < 35


def _author_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    users = payload.get("includes", {}).get("users") or []
    return {str(user.get("id")): user for user in users}


def _score_from_metrics(priority: int, metrics: dict[str, Any] | None) -> int:
    metrics = metrics or {}
    engagement = (
        int(metrics.get("like_count") or 0)
        + int(metrics.get("retweet_count") or 0) * 2
        + int(metrics.get("reply_count") or 0)
        + int(metrics.get("quote_count") or 0) * 2
    )
    return max(30, min(100, 45 + priority * 8 + min(20, engagement // 50)))


def _mapping_heat_bonus(weight: float) -> int:
    return max(0, min(12, int(round(weight * 10))))


def x_payload_to_source_items(
    payload: dict[str, Any],
    trade_date: str,
    keyword_seeds: list[KeywordSeed] | None = None,
) -> list[MessageSourceItemCreate]:
    users = _author_lookup(payload)
    items: list[MessageSourceItemCreate] = []
    for post in payload.get("data") or []:
        text = post.get("text") or ""
        matched = _match_keyword(text, keyword_seeds)
        mappings = _match_stock_mappings(text)
        if not matched and not mappings:
            continue
        author = users.get(str(post.get("author_id")), {})
        username = author.get("username") or str(post.get("author_id") or "")
        metrics = post.get("public_metrics") or {}
        if _is_low_quality_post(text, metrics):
            continue
        quality_score = _text_quality_score(text, metrics)
        priority = matched.priority if matched else 3
        base_theme = matched.theme if matched else mappings[0].theme
        base_tags = [matched.keyword, matched.type] if matched else []
        base_heat = _score_from_metrics(priority, metrics)
        if not mappings:
            mappings = [
                XStockMapping(
                    trigger=matched.keyword if matched else "",
                    theme=base_theme,
                    ts_code="",
                    stock_name="",
                    weight=0,
                    tags=[],
                )
            ]
        for mapping in mappings:
            ts_code = mapping.ts_code or None
            stock_name = mapping.stock_name or None
            theme = mapping.theme or base_theme
            tags = list(dict.fromkeys(base_tags + mapping.tags))
            heat_score = min(100, base_heat + _mapping_heat_bonus(mapping.weight))
            credibility_score = min(100, max(35, 45 + quality_score // 3 + _mapping_heat_bonus(mapping.weight)))
            item = MessageSourceItemCreate(
                trade_date=trade_date,
                channel="X",
                source_name=username,
                external_id=str(post.get("id")),
                content=text,
                url=f"https://x.com/{username}/status/{post.get('id')}" if username and post.get("id") else None,
                published_at=_parse_x_datetime(post.get("created_at")),
                theme=theme,
                ts_code=ts_code,
                stock_name=stock_name,
                tags=list(dict.fromkeys(tags + [f"quality:{quality_score}"])),
                sentiment="neutral",
                heat_score=heat_score,
                credibility_score=credibility_score,
                raw_payload=post,
            )
            items.append(item)
    return items


def _parse_x_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def collect_x_recent_posts(db: Session, body: MessageXCollectRequest) -> MessageXCollectOut:
    trade_date = body.trade_date or today_yyyymmdd()
    keyword_seeds = load_keyword_seeds(db)
    query = body.query or build_x_recent_search_query(body.min_priority, body.keyword_limit, keyword_seeds)
    payload = _fetch_x_recent_search(query, body.max_results)
    items = x_payload_to_source_items(payload, trade_date, keyword_seeds)
    if not items:
        return MessageXCollectOut(
            query=query,
            raw_count=len(payload.get("data") or []),
            imported=MessageSourceImportOut(created_count=0, skipped_count=0, items=[], aggregation=None),
        )
    imported = import_source_items(
        db,
        MessageSourceImportRequest(items=items, aggregate=body.aggregate),
    )
    return MessageXCollectOut(query=query, raw_count=len(payload.get("data") or []), imported=imported)


def build_x_stock_analysis_query(
    ts_code: str,
    stock_name: str | None = None,
    industry: str | None = None,
    themes: list[str] | None = None,
) -> str:
    symbol = ts_code.split(".")[0] if ts_code else ""
    use_plain_symbol = bool(symbol and not symbol.isdigit())
    stock_terms = [
        item
        for item in (stock_name, ts_code, symbol if use_plain_symbol else None, industry, *(themes or [])[:4])
        if item and len(str(item).strip()) >= 2
    ]
    seen: set[str] = set()
    normalized_terms: list[str] = []
    for term in stock_terms:
        text = str(term).strip()
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized_terms.append(f'"{text}"' if " " in text else text)

    hard_catalysts = [
        "订单",
        "合同",
        "中标",
        "采购",
        "供货",
        "出货",
        "交付",
        "量产",
        "order",
        "contract",
        '"purchase order"',
        '"supply agreement"',
        "shipment",
        "delivery",
        "tender",
        "award",
    ]
    if not normalized_terms:
        normalized_terms = [ts_code]
    stock_part = " OR ".join(normalized_terms[:10])
    catalyst_part = " OR ".join(hard_catalysts)
    return f"(({stock_part}) ({catalyst_part})) -is:retweet -is:reply"


def collect_x_stock_analysis_posts(
    db: Session,
    ts_code: str,
    stock_name: str | None = None,
    industry: str | None = None,
    themes: list[str] | None = None,
    trade_date: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    trade_date = trade_date or today_yyyymmdd()
    query = build_x_stock_analysis_query(ts_code, stock_name=stock_name, industry=industry, themes=themes)
    payload = _fetch_x_recent_search(query, max_results)
    users = _author_lookup(payload)
    source_items: list[MessageSourceItemCreate] = []

    for post in payload.get("data") or []:
        text = post.get("text") or ""
        metrics = post.get("public_metrics") or {}
        if _is_low_quality_post(text, metrics):
            continue
        author = users.get(str(post.get("author_id")), {})
        username = author.get("username") or str(post.get("author_id") or "")
        quality_score = _text_quality_score(text, metrics)
        theme = (themes or [None])[0] or industry or "个股消息"
        heat_score = _score_from_metrics(4, metrics)
        credibility_score = min(100, max(35, 45 + quality_score // 3))
        source_items.append(
            MessageSourceItemCreate(
                trade_date=trade_date,
                channel="X",
                source_name=username,
                external_id=str(post.get("id")),
                content=text,
                url=f"https://x.com/{username}/status/{post.get('id')}" if username and post.get("id") else None,
                published_at=_parse_x_datetime(post.get("created_at")),
                theme=theme,
                ts_code=ts_code,
                stock_name=stock_name,
                tags=["stock_ai_analysis", f"quality:{quality_score}"],
                sentiment="neutral",
                heat_score=heat_score,
                credibility_score=credibility_score,
                raw_payload=post,
            )
        )

    if not source_items:
        return {
            "query": query,
            "raw_count": len(payload.get("data") or []),
            "created_count": 0,
            "skipped_count": 0,
            "aggregation": None,
        }

    imported = import_source_items(
        db,
        MessageSourceImportRequest(items=source_items, aggregate=True),
    )
    return {
        "query": query,
        "raw_count": len(payload.get("data") or []),
        "created_count": imported.created_count,
        "skipped_count": imported.skipped_count,
        "aggregation": imported.aggregation.model_dump() if imported.aggregation else None,
    }
