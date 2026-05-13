from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.message import MessageOpportunity, MessageTopic
from app.models.stock import StockBasic
from app.schemas.message import MessageOpportunityCreate, MessageTopicCreate

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def today_yyyymmdd() -> str:
    return datetime.now(SHANGHAI_TZ).strftime("%Y%m%d")


def _list_value(value):
    return value if isinstance(value, list) else []


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


def ensure_seed_daily_messages(db: Session, trade_date: str) -> None:
    existing = db.query(MessageOpportunity.id).filter(MessageOpportunity.trade_date == trade_date).first()
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
        create_opportunity(db, opp)


def get_daily_messages(db: Session, trade_date: str, ensure_seed: bool = True) -> dict:
    if ensure_seed:
        ensure_seed_daily_messages(db, trade_date)

    topics = (
        db.query(MessageTopic)
        .filter(MessageTopic.trade_date == trade_date)
        .order_by(MessageTopic.heat_score.desc(), MessageTopic.credibility_score.desc())
        .all()
    )
    opportunities = (
        db.query(MessageOpportunity)
        .filter(MessageOpportunity.trade_date == trade_date, MessageOpportunity.status == "active")
        .order_by(MessageOpportunity.opportunity_score.desc(), MessageOpportunity.heat_score.desc())
        .all()
    )
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
