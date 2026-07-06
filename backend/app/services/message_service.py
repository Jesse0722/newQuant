from __future__ import annotations

import hashlib
from datetime import datetime
from statistics import mean
from time import perf_counter
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.message import MessageOpportunity, MessageSourceItem, MessageTopic
from app.models.stock import StockBasic
from app.schemas.message import (
    MessageAggregationResult,
    MessageConclusionOpportunity,
    MessageConclusionTopic,
    MessageDailyConclusionOut,
    MessageOpportunityCreate,
    MessageSourceImportRequest,
    MessageSourceImportOut,
    MessageSourceItemCreate,
    MessageTopicCreate,
)
from app.services.message_evidence_service import (
    ensure_rule_evidence_for_source_items,
    link_opportunity_evidence,
    record_rule_evidence_batch_run,
)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SEED_OPPORTUNITY_CODES = {
    "300308.SZ",
    "300475.SZ",
    "601138.SH",
    "300442.SZ",
    "300274.SZ",
    "002050.SZ",
}


def today_yyyymmdd() -> str:
    return datetime.now(SHANGHAI_TZ).strftime("%Y%m%d")


def _list_value(value):
    return value if isinstance(value, list) else []


def _dedupe_key(body: MessageSourceItemCreate, trade_date: str) -> str:
    identity = body.external_id or body.url or body.content
    raw = f"{trade_date}|{body.channel}|{identity}|{body.theme or ''}|{body.ts_code or ''}".strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _merge_unique(*groups: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            if item and item not in seen:
                result.append(item)
                seen.add(item)
    return result


def _source_links_by_channel(channels: list[str], items: list[MessageSourceItem]) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for channel in channels:
        link = next((item.url for item in items if item.channel == channel and item.url), "")
        if link and link not in seen:
            links.append(link)
            seen.add(link)
        else:
            links.append("")
    return links


def create_or_update_topic(db: Session, body: MessageTopicCreate) -> MessageTopic:
    trade_date = body.trade_date or today_yyyymmdd()
    topic = (
        db.query(MessageTopic)
        .filter(MessageTopic.trade_date == trade_date, MessageTopic.theme == body.theme)
        .first()
    )
    values = body.model_dump(exclude={"trade_date"})
    values["trade_date"] = trade_date
    if topic:
        for key, value in values.items():
            setattr(topic, key, value)
    else:
        topic = MessageTopic(**values)
        db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


def create_opportunity(db: Session, body: MessageOpportunityCreate) -> MessageOpportunity:
    trade_date = body.trade_date or today_yyyymmdd()
    stock_name = body.stock_name
    if not stock_name and body.ts_code:
        basic = db.query(StockBasic).filter(StockBasic.ts_code == body.ts_code).first()
        stock_name = basic.name if basic else None
    opp = MessageOpportunity(
        **body.model_dump(exclude={"trade_date", "stock_name"}),
        trade_date=trade_date,
        stock_name=stock_name,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def create_source_item(db: Session, body: MessageSourceItemCreate) -> tuple[MessageSourceItem, bool]:
    trade_date = body.trade_date or today_yyyymmdd()
    dedupe_key = _dedupe_key(body, trade_date)
    existing = db.query(MessageSourceItem).filter(MessageSourceItem.dedupe_key == dedupe_key).first()
    if existing:
        return existing, False

    stock_name = body.stock_name
    if not stock_name and body.ts_code:
        basic = db.query(StockBasic).filter(StockBasic.ts_code == body.ts_code).first()
        stock_name = basic.name if basic else None

    item = MessageSourceItem(
        **body.model_dump(exclude={"trade_date", "stock_name"}),
        trade_date=trade_date,
        stock_name=stock_name,
        dedupe_key=dedupe_key,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item, True


def _topic_summary(items: list[MessageSourceItem]) -> str:
    titles = [item.title for item in items if item.title]
    if titles:
        return "；".join(titles[:3])
    contents = [item.content[:60] for item in items if item.content]
    return "；".join(contents[:3])


def _topic_stage(item_count: int, channel_count: int, crowding_score: int) -> str:
    if crowding_score >= 75:
        return "climax"
    if item_count >= 3 or channel_count >= 2:
        return "spreading"
    return "early"


def _dominant_sentiment(items: list[MessageSourceItem]) -> str:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.sentiment] = counts.get(item.sentiment, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0] if counts else "neutral"


def _upsert_aggregated_opportunity(
    db: Session,
    *,
    trade_date: str,
    topic: MessageTopic,
    theme: str,
    ts_code: str,
    stock_name: str | None,
    items: list[MessageSourceItem],
) -> MessageOpportunity:
    channels = sorted({item.channel for item in items})
    channel_bonus = min(16, max(0, len(channels) - 1) * 8)
    item_bonus = min(15, len(items) * 3)
    avg_heat = mean([item.heat_score for item in items])
    avg_credibility = mean([item.credibility_score for item in items])
    heat_score = _clamp_score(avg_heat + channel_bonus + item_bonus)
    credibility_score = _clamp_score(avg_credibility + min(12, len(channels) * 4))
    risk_score = _clamp_score(30 + max(0, len(items) - 2) * 8 + max(0, heat_score - 80) * 0.5)
    evidence_score = credibility_score
    mapping_confidence = _clamp_score(55 + channel_bonus + min(20, len(items) * 4))
    opportunity_score = _clamp_score(heat_score * 0.55 + credibility_score * 0.35 - risk_score * 0.15 + channel_bonus)
    action_suggestion = "add_to_pool" if opportunity_score >= 80 and risk_score < 70 else "watch"
    if risk_score >= 70:
        action_suggestion = "risk_watch"

    source_links = _source_links_by_channel(channels, items)
    catalysts = _merge_unique(*[item.tags for item in items])
    reason = f"{theme} 在 {len(channels)} 个渠道出现共振，近 {len(items)} 条消息提及 {stock_name or ts_code}。"
    if any(source_links):
        reason += " 已保留来源链接便于复盘。"

    existing = (
        db.query(MessageOpportunity)
        .filter(
            MessageOpportunity.trade_date == trade_date,
            MessageOpportunity.theme == theme,
            MessageOpportunity.ts_code == ts_code,
            MessageOpportunity.status != "demo",
        )
        .first()
    )
    values = {
        "topic_id": topic.id,
        "trade_date": trade_date,
        "theme": theme,
        "ts_code": ts_code,
        "stock_name": stock_name,
        "opportunity_score": opportunity_score,
        "heat_score": heat_score,
        "credibility_score": credibility_score,
        "risk_score": risk_score,
        "evidence_score": evidence_score,
        "mapping_confidence": mapping_confidence,
        "action_suggestion": action_suggestion,
        "reason": reason,
        "catalysts": catalysts,
        "risks": ["消息热度变化快，需等待买点雷达确认"],
        "source_platforms": channels,
        "source_links": source_links,
        "review_status": "reviewed",
        "generated_by": "rule",
    }
    if existing:
        if existing.review_status in {"accepted", "dismissed"}:
            return existing
        for key, value in values.items():
            if key == "review_status" and existing.review_status:
                continue
            setattr(existing, key, value)
        return existing

    opp = MessageOpportunity(**values)
    db.add(opp)
    return opp


def aggregate_source_items(db: Session, trade_date: str) -> MessageAggregationResult:
    started_at = datetime.utcnow()
    elapsed_start = perf_counter()
    items = (
        db.query(MessageSourceItem)
        .filter(
            MessageSourceItem.trade_date == trade_date,
            MessageSourceItem.status != "ignored",
            MessageSourceItem.theme.isnot(None),
        )
        .all()
    )
    grouped_by_theme: dict[str, list[MessageSourceItem]] = {}
    for item in items:
        if item.theme:
            grouped_by_theme.setdefault(item.theme, []).append(item)
    evidence_rows = ensure_rule_evidence_for_source_items(db, items)
    evidence_by_source_id: dict[str, list] = {}
    for evidence in evidence_rows:
        evidence_by_source_id.setdefault(evidence.source_item_id, []).append(evidence)

    topics: dict[str, MessageTopic] = {}
    for theme, theme_items in grouped_by_theme.items():
        channels = sorted({item.channel for item in theme_items})
        heat_score = _clamp_score(mean([item.heat_score for item in theme_items]) + len(channels) * 8 + len(theme_items) * 2)
        credibility_score = _clamp_score(mean([item.credibility_score for item in theme_items]) + len(channels) * 4)
        crowding_score = _clamp_score(20 + len(theme_items) * 8 + max(0, len(channels) - 1) * 10)
        topic = create_or_update_topic(
            db,
            MessageTopicCreate(
                trade_date=trade_date,
                theme=theme,
                summary=_topic_summary(theme_items),
                lifecycle_stage=_topic_stage(len(theme_items), len(channels), crowding_score),
                sentiment=_dominant_sentiment(theme_items),
                heat_score=heat_score,
                credibility_score=credibility_score,
                crowding_score=crowding_score,
                source_platforms=channels,
                tags=_merge_unique(*[item.tags for item in theme_items]),
            ),
        )
        topics[theme] = topic

    opportunity_groups: dict[tuple[str, str], list[MessageSourceItem]] = {}
    for item in items:
        if item.theme and item.ts_code:
            opportunity_groups.setdefault((item.theme, item.ts_code), []).append(item)

    opportunities: list[MessageOpportunity] = []
    for (theme, ts_code), opp_items in opportunity_groups.items():
        topic = topics.get(theme)
        if not topic:
            continue
        opportunity = _upsert_aggregated_opportunity(
            db,
            trade_date=trade_date,
            topic=topic,
            theme=theme,
            ts_code=ts_code,
            stock_name=opp_items[0].stock_name,
            items=opp_items,
        )
        db.flush()
        opportunity_evidence = [
            evidence
            for item in opp_items
            for evidence in evidence_by_source_id.get(item.id, [])
        ]
        link_opportunity_evidence(db, opportunity, opportunity_evidence)
        opportunities.append(opportunity)

    for item in items:
        item.status = "processed"
    if items:
        record_rule_evidence_batch_run(
            db,
            trade_date=trade_date,
            source_item_count=len(items),
            evidence_count=len(evidence_rows),
            started_at=started_at,
            elapsed_start=elapsed_start,
        )
    db.commit()
    return MessageAggregationResult(
        trade_date=trade_date,
        topic_count=len(topics),
        opportunity_count=len(opportunities),
        source_item_count=len(items),
    )


def import_source_items(db: Session, body: MessageSourceImportRequest) -> MessageSourceImportOut:
    imported: list[MessageSourceItem] = []
    skipped = 0
    trade_dates: set[str] = set()
    for item_body in body.items:
        item, created = create_source_item(db, item_body)
        imported.append(item)
        trade_dates.add(item.trade_date)
        if not created:
            skipped += 1

    aggregation = None
    if body.aggregate and len(trade_dates) == 1:
        aggregation = aggregate_source_items(db, next(iter(trade_dates)))

    return MessageSourceImportOut(
        created_count=len(imported) - skipped,
        skipped_count=skipped,
        items=imported,
        aggregation=aggregation,
    )


def ensure_seed_daily_messages(db: Session, trade_date: str) -> None:
    existing = (
        db.query(MessageOpportunity.id)
        .filter(MessageOpportunity.trade_date == trade_date, MessageOpportunity.status == "demo")
        .first()
    )
    if existing:
        return

    seed_topics = [
        MessageTopicCreate(
            trade_date=trade_date,
            theme="AI算力",
            summary="海外 AI capex 与国产算力链继续被反复讨论，资金关注服务器、GPU、光模块和电源配套。",
            lifecycle_stage="spreading",
            sentiment="positive",
            heat_score=92,
            credibility_score=78,
            crowding_score=58,
            source_platforms=["Twitter", "雪球", "淘股吧"],
            tags=["AI", "算力", "数据中心"],
        ),
        MessageTopicCreate(
            trade_date=trade_date,
            theme="HBM与存储",
            summary="HBM 供需、DRAM 周期和存储涨价叙事升温，适合跟踪产业链映射与价格催化。",
            lifecycle_stage="early",
            sentiment="positive",
            heat_score=86,
            credibility_score=74,
            crowding_score=42,
            source_platforms=["Twitter", "雪球"],
            tags=["HBM", "存储", "涨价"],
        ),
        MessageTopicCreate(
            trade_date=trade_date,
            theme="液冷与电力",
            summary="AI 数据中心功耗提升带动液冷、电源、电网侧配套讨论，属于算力链外溢方向。",
            lifecycle_stage="spreading",
            sentiment="positive",
            heat_score=81,
            credibility_score=70,
            crowding_score=46,
            source_platforms=["雪球", "淘股吧", "小红书"],
            tags=["液冷", "电力", "数据中心"],
        ),
        MessageTopicCreate(
            trade_date=trade_date,
            theme="机器人",
            summary="机器人仍处在高关注赛道，需区分产业进展和短线题材情绪，避免追高拥挤。",
            lifecycle_stage="climax",
            sentiment="neutral",
            heat_score=76,
            credibility_score=62,
            crowding_score=72,
            source_platforms=["雪球", "淘股吧", "小红书"],
            tags=["机器人", "具身智能"],
        ),
    ]

    topic_by_theme = {t.theme: create_or_update_topic(db, t) for t in seed_topics}
    seed_opportunities = [
        MessageOpportunityCreate(
            trade_date=trade_date,
            topic_id=topic_by_theme["AI算力"].id,
            theme="AI算力",
            ts_code="300308.SZ",
            stock_name="中际旭创",
            opportunity_score=92,
            heat_score=92,
            credibility_score=82,
            risk_score=48,
            action_suggestion="add_to_pool",
            reason="光模块作为 AI 数据中心扩容的高弹性方向，海外算力叙事升温时通常会被优先映射。",
            catalysts=["AI capex 上修", "高速光模块需求", "海外科技链情绪扩散"],
            risks=["短期涨幅过大", "业绩兑现节奏不及预期"],
            source_platforms=["Twitter", "雪球"],
        ),
        MessageOpportunityCreate(
            trade_date=trade_date,
            topic_id=topic_by_theme["HBM与存储"].id,
            theme="HBM与存储",
            ts_code="300475.SZ",
            stock_name="香农芯创",
            opportunity_score=88,
            heat_score=86,
            credibility_score=76,
            risk_score=55,
            action_suggestion="watch",
            reason="HBM 与存储涨价叙事容易向 A股存储分销和模组方向映射，适合先进入观察池等待买点。",
            catalysts=["HBM 供需紧张", "DRAM 周期修复", "存储涨价预期"],
            risks=["题材波动大", "基本面兑现需要继续验证"],
            source_platforms=["Twitter", "雪球"],
        ),
        MessageOpportunityCreate(
            trade_date=trade_date,
            topic_id=topic_by_theme["AI算力"].id,
            theme="AI算力",
            ts_code="601138.SH",
            stock_name="工业富联",
            opportunity_score=84,
            heat_score=82,
            credibility_score=80,
            risk_score=42,
            action_suggestion="watch",
            reason="AI 服务器是算力链核心映射之一，适合作为较高确定性的中军标的观察。",
            catalysts=["AI服务器出货", "云厂商资本开支", "产业链订单预期"],
            risks=["弹性弱于小市值标的", "海外需求节奏变化"],
            source_platforms=["Twitter", "雪球"],
        ),
        MessageOpportunityCreate(
            trade_date=trade_date,
            topic_id=topic_by_theme["液冷与电力"].id,
            theme="液冷与电力",
            ts_code="300442.SZ",
            stock_name="润泽科技",
            opportunity_score=80,
            heat_score=80,
            credibility_score=70,
            risk_score=50,
            action_suggestion="watch",
            reason="数据中心与算力基础设施扩张带动液冷、电力和机房资源方向反复活跃。",
            catalysts=["数据中心扩容", "液冷渗透率提升", "算力基础设施投资"],
            risks=["估值偏高", "政策和项目进度扰动"],
            source_platforms=["雪球", "淘股吧"],
        ),
        MessageOpportunityCreate(
            trade_date=trade_date,
            topic_id=topic_by_theme["液冷与电力"].id,
            theme="液冷与电力",
            ts_code="300274.SZ",
            stock_name="阳光电源",
            opportunity_score=76,
            heat_score=73,
            credibility_score=72,
            risk_score=44,
            action_suggestion="watch",
            reason="AI 数据中心功耗提升让电源和电力设备成为算力链外溢方向，可跟踪是否形成多平台共振。",
            catalysts=["电源需求提升", "数据中心功耗上行", "海外电力链映射"],
            risks=["主业因素干扰", "题材映射强度需验证"],
            source_platforms=["Twitter", "雪球"],
        ),
        MessageOpportunityCreate(
            trade_date=trade_date,
            topic_id=topic_by_theme["机器人"].id,
            theme="机器人",
            ts_code="002050.SZ",
            stock_name="三花智控",
            opportunity_score=72,
            heat_score=76,
            credibility_score=66,
            risk_score=68,
            action_suggestion="risk_watch",
            reason="机器人题材传播面较广，但小红书和短线社区热度偏高，需要重点观察拥挤度。",
            catalysts=["具身智能进展", "海外机器人产业链讨论", "短线题材轮动"],
            risks=["大众扩散过热", "短线追高风险"],
            source_platforms=["雪球", "淘股吧", "小红书"],
        ),
    ]
    for opp in seed_opportunities:
        create_opportunity(db, MessageOpportunityCreate(**{**opp.model_dump(), "status": "demo"}))


def _is_legacy_seed_opportunity(opp: MessageOpportunity) -> bool:
    if opp.status != "active" or opp.ts_code not in SEED_OPPORTUNITY_CODES:
        return False
    if _list_value(opp.source_links):
        return False
    reason = opp.reason or ""
    return (
        "光模块作为 AI 数据中心扩容" in reason
        or "HBM 与存储涨价叙事" in reason
        or "AI 服务器是算力链核心映射" in reason
        or "数据中心与算力基础设施扩张" in reason
        or "AI 数据中心功耗提升" in reason
        or "机器人题材传播面较广" in reason
    )


def demote_legacy_seed_daily_messages(db: Session, trade_date: str) -> None:
    rows = (
        db.query(MessageOpportunity)
        .filter(MessageOpportunity.trade_date == trade_date, MessageOpportunity.status == "active")
        .all()
    )
    changed = False
    for row in rows:
        if _is_legacy_seed_opportunity(row):
            row.status = "demo"
            changed = True
    if changed:
        db.commit()


def get_daily_messages(db: Session, trade_date: str, ensure_seed: bool = True) -> dict:
    if ensure_seed:
        ensure_seed_daily_messages(db, trade_date)

    topic_rows = (
        db.query(MessageTopic)
        .filter(MessageTopic.trade_date == trade_date)
        .order_by(MessageTopic.heat_score.desc(), MessageTopic.credibility_score.desc())
        .all()
    )
    status_filter = ["active", "demo"] if ensure_seed else ["active"]
    opportunities = (
        db.query(MessageOpportunity)
        .filter(MessageOpportunity.trade_date == trade_date, MessageOpportunity.status.in_(status_filter))
        .order_by(MessageOpportunity.opportunity_score.desc(), MessageOpportunity.heat_score.desc())
        .all()
    )
    if ensure_seed:
        topics = topic_rows
    else:
        active_themes = {opp.theme for opp in opportunities}
        active_themes.update(
            theme
            for (theme,) in db.query(MessageSourceItem.theme)
            .filter(
                MessageSourceItem.trade_date == trade_date,
                MessageSourceItem.status != "ignored",
                MessageSourceItem.theme.isnot(None),
            )
            .distinct()
            .all()
        )
        topics = [topic for topic in topic_rows if topic.theme in active_themes]
    top = opportunities[0] if opportunities else None
    leading_topic = topics[0] if topics else None
    return {
        "trade_date": trade_date,
        "generated_at": datetime.now(SHANGHAI_TZ),
        "stats": {
            "topic_count": len(topics),
            "opportunity_count": len(opportunities),
            "top_score": top.opportunity_score if top else None,
            "leading_theme": leading_topic.theme if leading_topic else None,
        },
        "topics": topics,
        "opportunities": opportunities,
    }


def _topic_conclusion(topic: MessageTopic) -> str:
    stage_map = {
        "early": "处于早期观察阶段",
        "spreading": "正在扩散",
        "climax": "热度偏高潮，注意拥挤",
        "cooling": "有退潮迹象",
    }
    stage = stage_map.get(topic.lifecycle_stage, topic.lifecycle_stage)
    sources = "、".join(_list_value(topic.source_platforms)) or "单一来源"
    return f"{topic.theme}{stage}，热度{topic.heat_score}，可信度{topic.credibility_score}，来源：{sources}。"


def _opportunity_conclusion(opp: MessageOpportunity) -> str:
    target = opp.stock_name or opp.ts_code or "主题机会"
    if opp.action_suggestion == "add_to_pool":
        action = "可优先加入观察池等待买点确认"
    elif opp.action_suggestion == "risk_watch":
        action = "热度或风险偏高，只适合风险观察"
    else:
        action = "先观察，等待更多共振或买点确认"
    return f"{target} 关联 {opp.theme}，机会分{opp.opportunity_score}，风险分{opp.risk_score}，{action}。"


def get_daily_conclusion(
    db: Session,
    trade_date: str,
    ensure_seed: bool = False,
    limit: int = 5,
) -> MessageDailyConclusionOut:
    daily = get_daily_messages(db, trade_date, ensure_seed=ensure_seed)
    topics: list[MessageTopic] = daily["topics"][:limit]
    opportunities: list[MessageOpportunity] = daily["opportunities"][:limit]

    if not topics and not opportunities:
        return MessageDailyConclusionOut(
            trade_date=trade_date,
            generated_at=datetime.now(SHANGHAI_TZ),
            headline="暂无可分析的舆情机会",
            conclusion="当前日期没有题材或个股机会数据。请先导入关键词并执行采集，或导入原始消息。",
            next_action="先执行关键词导入和 X 小批量采集，再回到消息中心查看结论。",
            top_topics=[],
            top_opportunities=[],
        )

    leading_topic = topics[0] if topics else None
    top_opp = opportunities[0] if opportunities else None
    headline_parts: list[str] = []
    if leading_topic:
        headline_parts.append(f"强势题材：{leading_topic.theme}")
    if top_opp:
        headline_parts.append(f"首要候选：{top_opp.stock_name or top_opp.ts_code}")
    headline = "；".join(headline_parts) or "今日舆情结论"

    high_risk_count = len([opp for opp in opportunities if opp.risk_score >= 70])
    add_pool_count = len([opp for opp in opportunities if opp.action_suggestion == "add_to_pool"])
    if add_pool_count:
        next_action = "优先把高分且风险不过热的候选加入核心关注，再用买点雷达确认。"
    elif high_risk_count:
        next_action = "当前机会热度偏拥挤，先做风险观察，避免直接追高。"
    else:
        next_action = "维持观察，等待多渠道共振或技术买点确认。"

    conclusion = (
        f"今日共识别 {len(topics)} 个重点题材、{len(opportunities)} 个候选机会。"
        f"{headline}。{next_action}"
    )

    return MessageDailyConclusionOut(
        trade_date=trade_date,
        generated_at=datetime.now(SHANGHAI_TZ),
        headline=headline,
        conclusion=conclusion,
        next_action=next_action,
        top_topics=[
            MessageConclusionTopic(
                theme=topic.theme,
                heat_score=topic.heat_score,
                credibility_score=topic.credibility_score,
                crowding_score=topic.crowding_score,
                lifecycle_stage=topic.lifecycle_stage,
                source_platforms=_list_value(topic.source_platforms),
                conclusion=_topic_conclusion(topic),
            )
            for topic in topics
        ],
        top_opportunities=[
            MessageConclusionOpportunity(
                theme=opp.theme,
                ts_code=opp.ts_code,
                stock_name=opp.stock_name,
                opportunity_score=opp.opportunity_score,
                risk_score=opp.risk_score,
                action_suggestion=opp.action_suggestion,
                source_links=_list_value(opp.source_links),
                conclusion=_opportunity_conclusion(opp),
            )
            for opp in opportunities
        ],
    )
