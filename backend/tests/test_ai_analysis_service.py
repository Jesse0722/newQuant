from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.message import MessageSourceItem
from app.models.stock import DailyQuote, StockAiAnalysis
from app.services.ai_analysis_service import (
    _build_llm_snapshot,
    _build_prompt,
    _cache_hit_without_refresh,
    _collect_x_for_analysis,
    _fetch_external_official_context,
    _financial_abstract_latest_metrics,
    _financial_abstract_period_facts,
    _financial_balance_sheet_facts,
    _latest_financial_metrics,
    _query_messages,
    _sanitize_result,
)
from app.services.x_message_service import build_x_stock_analysis_query, x_payload_to_source_items


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return TestingSessionLocal()


def test_latest_financial_metrics_sorts_report_period_descending():
    df = pd.DataFrame(
        [
            {"日期": "2024-03-31", "营业总收入": 100, "净利润": 10},
            {"日期": "2026-03-31", "营业总收入": 260, "净利润": 32},
            {"日期": "2025-12-31", "营业总收入": 900, "净利润": 80},
        ]
    )

    metrics = _latest_financial_metrics(df)

    assert metrics["日期"] == "2026-03-31"
    assert metrics["营业总收入"] == 260
    assert metrics["净利润"] == 32


def test_financial_abstract_uses_newest_period_column():
    df = pd.DataFrame(
        [
            {"选项": "常用指标", "指标": "营业总收入", "20260331": 260, "20251231": 900, "20240331": 100},
            {"选项": "常用指标", "指标": "归母净利润", "20260331": 32, "20251231": 80, "20240331": 10},
        ]
    )

    metrics = _financial_abstract_latest_metrics(df)

    assert metrics["报告期"] == "20260331"
    assert metrics["营业总收入"] == 260
    assert metrics["归母净利润"] == 32


def test_financial_abstract_period_facts_include_yoy_and_cash_flow():
    df = pd.DataFrame(
        [
            {"选项": "常用指标", "指标": "营业总收入", "20260331": 997438300, "20250331": 704342000},
            {"选项": "常用指标", "指标": "归母净利润", "20260331": 271273000, "20250331": 29451510},
            {"选项": "常用指标", "指标": "扣非净利润", "20260331": 278232200, "20250331": 28975370},
            {"选项": "常用指标", "指标": "经营现金流量净额", "20260331": 606970700, "20250331": 192421300},
        ]
    )

    facts = _financial_abstract_period_facts(df)

    assert facts["period"] == "20260331"
    assert facts["compare_period"] == "20250331"
    assert facts["revenue_yi"] == 9.97
    assert facts["net_profit_yi"] == 2.71
    assert facts["net_profit_yoy_pct"] == 821.08
    assert facts["operating_cash_flow_yi"] == 6.07


def test_financial_balance_sheet_facts_include_contract_liabilities():
    df = pd.DataFrame(
        [
            {
                "REPORT_DATE": "2026-03-31 00:00:00",
                "REPORT_TYPE": "一季报",
                "CONTRACT_LIAB": 2171846557.61,
                "TOTAL_ASSETS": 9038141423.98,
                "TOTAL_LIABILITIES": 6787219083.79,
            },
            {
                "REPORT_DATE": "2025-12-31 00:00:00",
                "REPORT_TYPE": "年报",
                "CONTRACT_LIAB": 29447517.52,
                "TOTAL_ASSETS": 6299756773.63,
                "TOTAL_LIABILITIES": 4348444370.80,
            },
        ]
    )

    facts = _financial_balance_sheet_facts(df)

    assert facts["period"] == "20260331"
    assert facts["contract_liabilities_yi"] == 21.72
    assert facts["contract_liabilities_prev_yi"] == 0.29
    assert facts["debt_ratio_est_pct"] == 75.1


def test_official_context_extracts_announcements_news_and_verified_facts(monkeypatch):
    fake_akshare = SimpleNamespace(
        stock_balance_sheet_by_report_em=lambda symbol: pd.DataFrame(
            [
                {
                    "REPORT_DATE": "2026-03-31 00:00:00",
                    "REPORT_TYPE": "一季报",
                    "CONTRACT_LIAB": 2171846557.61,
                    "TOTAL_ASSETS": 9038141423.98,
                    "TOTAL_LIABILITIES": 6787219083.79,
                },
            ]
        ),
        stock_individual_notice_report=lambda **kwargs: pd.DataFrame(
            [
                {
                    "代码": "603629",
                    "名称": "利通电子",
                    "公告标题": "利通电子:2026年第一季度报告",
                    "公告类型": "财务报告",
                    "公告日期": "2026-04-28",
                    "网址": "https://example.test/q1",
                },
                {
                    "代码": "603629",
                    "名称": "利通电子",
                    "公告标题": "利通电子:无关公告",
                    "公告类型": "其他",
                    "公告日期": "2026-04-20",
                    "网址": "https://example.test/other",
                },
                {
                    "代码": "603629",
                    "名称": "利通电子",
                    "公告标题": "利通电子:2026年05月11日投资者关系活动记录表",
                    "公告类型": "调研活动",
                    "公告日期": "2026-05-11",
                    "网址": "https://data.eastmoney.com/notices/detail/603629/AN202605111822171421.html",
                },
            ]
        ),
        stock_news_em=lambda symbol: pd.DataFrame(
            [
                {
                    "关键词": symbol,
                    "新闻标题": "利通电子一季度净利润2.71亿元",
                    "新闻内容": "公司2026年第一季度营业收入9.97亿元，归母净利润2.71亿元，同比增长821.08%。",
                    "发布时间": "2026-04-28 10:00:00",
                    "文章来源": "上海证券报",
                    "新闻链接": "https://example.test/news",
                },
                {
                    "关键词": symbol,
                    "新闻标题": "利通电子：公司未量产PCM存储芯片",
                    "新闻内容": "公司表示目前未量产PCM存储芯片，主营仍为显示模组相关业务。",
                    "发布时间": "2026-05-20 12:45:00",
                    "文章来源": "证券时报网",
                    "新闻链接": "https://example.test/risk",
                }
            ]
        ),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    monkeypatch.setattr(
        "app.services.ai_analysis_service._fetch_eastmoney_notice_content",
        lambda url: {
            "title": "利通电子:2026年05月11日投资者关系活动记录表",
            "content": "企业级SSD固态硬盘模组研发已经完成工程样品研发，并进入核心测试阶段。",
            "pdf_url": "https://pdf.example.test/ir.pdf",
        },
    )
    financial_df = pd.DataFrame(
        [
            {"选项": "常用指标", "指标": "营业总收入", "20260331": 997438300, "20250331": 704342000},
            {"选项": "常用指标", "指标": "归母净利润", "20260331": 271273000, "20250331": 29451510},
        ]
    )

    context = _fetch_external_official_context("603629.SH", "deep", financial_df=financial_df)

    assert context["status"] == "ok"
    assert context["verified_facts"]["latest_financial_period"]["net_profit_yi"] == 2.71
    assert context["verified_facts"]["latest_balance_sheet"]["contract_liabilities_yi"] == 21.72
    assert context["announcements"][0]["source_confidence"] == "official_announcement"
    assert any("核心测试阶段" in item.get("summary", "") for item in context["announcements"])
    assert any(item["source_confidence"] == "major_financial_media" for item in context["market_news"])
    assert any("未量产PCM" in item["title"] for item in context["market_news"])
    assert any("大型财经媒体" in item["source_note"] for item in context["market_news"])


def test_query_messages_promotes_capacity_order_value_signals():
    db = _session()
    try:
        db.add_all(
            [
                MessageSourceItem(
                    trade_date="20260520",
                    channel="X",
                    title="普通热度",
                    content="公司所属行业讨论热度提升。",
                    theme="AI算力",
                    ts_code="300308.SZ",
                    stock_name="中际旭创",
                    heat_score=88,
                    credibility_score=60,
                    dedupe_key="normal",
                ),
                MessageSourceItem(
                    trade_date="20260521",
                    channel="X",
                    title="产能和订单量提升",
                    content="新产能爬坡，shipment volume 与在手订单继续增长，收入指引上修。",
                    theme="光模块",
                    ts_code="300308.SZ",
                    stock_name="中际旭创",
                    tags=["capacity", "shipment volume", "backlog"],
                    heat_score=70,
                    credibility_score=75,
                    dedupe_key="value",
                ),
            ]
        )
        db.commit()

        news = _query_messages(db, "300308.SZ")

        assert news["has_value_signal"] is True
        assert news["value_signal_count"] == 1
        assert news["items"][0]["title"] == "产能和订单量提升"
        assert news["items"][0]["source_confidence"] == "social_rumor"
        assert "小作文" in news["items"][0]["source_note"]
        assert {"capacity", "shipment volume", "backlog"} & set(news["value_signals"][0]["matched_keywords"])
    finally:
        db.close()


def test_stock_analysis_x_query_and_payload_include_value_catalysts():
    query = build_x_stock_analysis_query("300308.SZ", stock_name="中际旭创", industry="光模块", themes=["AI算力"])

    assert "capacity" in query
    assert "backlog" in query
    assert "guidance" in query

    payload = {
        "data": [
            {
                "id": "value-1",
                "author_id": "u1",
                "created_at": "2026-05-21T01:30:00Z",
                "text": "Optical module capacity expansion and shipment volume ramp are lifting revenue guidance.",
                "public_metrics": {"like_count": 20, "retweet_count": 3, "reply_count": 1, "quote_count": 0},
            }
        ],
        "includes": {"users": [{"id": "u1", "username": "supply_chain"}]},
    }

    items = x_payload_to_source_items(payload, "20260521")

    assert items
    assert {"capacity", "capacity expansion", "shipment volume", "guidance", "revenue"} & set(items[0].tags)


def test_cache_hit_without_refresh_requires_fresh_local_kline(monkeypatch):
    db = _session()
    try:
        monkeypatch.setattr("app.services.ai_analysis_service.latest_daily_k_trade_date_str", lambda: "20260522")
        db.add(DailyQuote(ts_code="603629.SH", trade_date="20260521", close=100))
        db.add(
            StockAiAnalysis(
                ts_code="603629.SH",
                model_provider="deepseek",
                model_name="deepseek-v4-pro",
                prompt_version="1.0",
                data_trade_date="20260521",
                analysis_json={"score": 1},
                snapshot_json={},
                status="success",
            )
        )
        db.commit()

        assert _cache_hit_without_refresh(db, "603629.SH") is None

        db.add(DailyQuote(ts_code="603629.SH", trade_date="20260522", close=101))
        db.add(
            StockAiAnalysis(
                ts_code="603629.SH",
                model_provider="deepseek",
                model_name="deepseek-v4-pro",
                prompt_version="1.0",
                data_trade_date="20260522",
                analysis_json={"score": 2},
                snapshot_json={},
                status="success",
            )
        )
        db.commit()

        cached = _cache_hit_without_refresh(db, "603629.SH")
        assert cached is not None
        assert cached.data_trade_date == "20260522"
    finally:
        db.close()


def test_x_collect_is_disabled_by_default(monkeypatch):
    db = _session()
    try:
        monkeypatch.delenv("AI_ANALYSIS_X_COLLECT_ENABLED", raising=False)
        result = _collect_x_for_analysis(db, "603629.SH", None)

        assert result == {"attempted": False, "status": "disabled"}
    finally:
        db.close()


def test_llm_snapshot_keeps_facts_but_drops_raw_heavy_payloads():
    snapshot = {
        "stock": {"ts_code": "603629.SH", "name": "利通电子", "industry": "电子元件"},
        "market": {"latest_trade_date": "20260522", "close": 195.65, "pct_chg": 8.5, "turnover_rate": 12.77, "amount": 1000},
        "technical": {
            "ma5": 180,
            "ma10": 160,
            "ma20": 120,
            "rsi14": 83.42,
            "volume_ratio_5d": 1.8,
            "position_20d": 100,
            "support_levels": [160, 150],
            "pressure_levels": [195.65],
            "recent_kline": [{"trade_date": f"202605{i:02d}", "close": i} for i in range(1, 9)],
        },
        "fundamental": {
            "profile": {"industry": "电子元件", "area": "江苏"},
            "scale_liquidity": {"float_market_cap_yi_est": 438.65, "turnover_rate": 12.77},
            "related_concepts": ["算力租赁"],
            "business": {
                "main_business": "液晶电视结构件与AI算力业务",
                "business_description_rows": [
                    {
                        "主营业务": "液晶电视精密金属结构件、电子元器件的研发、生产及销售、算力产品销售及算力云服务。",
                        "产品类型": "精密金属冲压结构件、电子元器件、模具、算力业务",
                        "经营范围": "这是一段很长的经营范围，应该不进入 prompt。",
                    }
                ],
                "business_composition": [
                    {
                        "报告日期": "2025-12-31",
                        "分类类型": "按行业分类",
                        "主营构成": "制造业",
                        "主营收入": 2066115755.26,
                        "收入比例": 0.624695,
                        "利润比例": 0.251397,
                        "毛利率": 0.099788,
                    },
                    {
                        "报告日期": "2025-12-31",
                        "分类类型": "按行业分类",
                        "主营构成": "算力业务",
                        "主营收入": 1199585316.9,
                        "收入比例": 0.362697,
                        "利润比例": 0.726758,
                        "毛利率": 0.496858,
                    },
                ],
                "financial_rows": [{"very": "heavy"}],
                "official_context": {
                    "verified_facts": {
                        "latest_financial_period": {
                            "period": "20260331",
                            "revenue_yi": 9.97,
                            "revenue_yoy_pct": 41.61,
                            "net_profit_yi": 2.71,
                            "net_profit_yoy_pct": 821.08,
                            "operating_cash_flow_yi": 6.07,
                            "operating_cash_flow_yoy_pct": 215.44,
                            "gross_margin_pct": 46.23,
                        },
                        "latest_balance_sheet": {
                            "period": "20260331",
                            "contract_liabilities_yi": 21.72,
                            "contract_liabilities_prev_yi": 0.29,
                            "debt_ratio_est_pct": 75.1,
                        },
                    },
                    "announcements": [
                        {
                            "date": "2026-04-28",
                            "title": "利通电子2026年第一季度报告",
                            "type": "财务报告",
                            "url": "https://example.test/q1",
                            "source_confidence": "official_announcement",
                            "source_note": "公司公告/财报来源：公司公告 / 财务报告",
                        }
                    ],
                    "market_news": [
                        {
                            "published_at": "2026-05-19",
                            "title": "公司再融资问询回复披露募投进展",
                            "summary": "再融资问询与回复披露新项目情况。",
                            "source": "交易所披露转载",
                            "source_confidence": "major_financial_media",
                            "source_note": "大型财经媒体来源：交易所披露转载",
                        },
                        {
                            "published_at": "2026-05-20",
                            "title": "公司未量产PCM存储芯片",
                            "summary": "公司表示目前未量产PCM存储芯片。",
                            "source": "证券时报网",
                            "source_confidence": "major_financial_media",
                            "source_note": "大型财经媒体来源：证券时报网",
                        },
                        {
                            "published_at": "2026-05-11",
                            "title": "投资者关系活动记录表披露SSD模组进展",
                            "summary": "企业级SSD固态硬盘模组完成工程样品研发，并进入核心测试阶段。",
                            "source": "公司公告",
                            "source_confidence": "official_announcement",
                            "source_note": "公司公告/财报来源：公司公告 / 调研活动",
                        }
                    ],
                },
            },
        },
        "news": {
                "official_context": {
                    "verified_facts": {
                        "latest_financial_period": {"period": "20260331", "net_profit_yi": 2.71, "net_profit_yoy_pct": 821.08},
                        "latest_balance_sheet": {"period": "20260331", "contract_liabilities_yi": 21.72},
                    },
                    "announcements": [],
                    "market_news": [
                        {
                            "published_at": "2026-05-20",
                            "title": "公司未量产PCM存储芯片",
                            "summary": "公司表示目前未量产PCM存储芯片。",
                            "source": "证券时报网",
                            "source_confidence": "major_financial_media",
                            "source_note": "大型财经媒体来源：证券时报网",
                        }
                    ],
                },
            "items": [
                {
                    "trade_date": "20260521",
                    "theme": "算力",
                    "title": "社媒传订单",
                    "content": "X小作文提到订单",
                    "source_confidence": "social_rumor",
                    "source_note": "X/社媒小作文线索，未按公告验证：X",
                    "value_keywords": ["订单"],
                }
            ],
            "value_signals": [
                {
                    "trade_date": "20260521",
                    "theme": "算力",
                    "title": "社媒传订单",
                    "content": "X小作文提到订单",
                    "matched_keywords": ["订单"],
                    "source_confidence": "social_rumor",
                    "source_note": "X/社媒小作文线索，未按公告验证：X",
                }
            ],
            "order_signals": [],
            "value_signal_count": 1,
            "order_signal_count": 0,
            "summary_metrics": {"message_count": 1, "theme_count": 1},
        },
        "user_context": {"pool_name": "观察池", "trades": []},
        "data_quality": {"score": 90, "warnings": []},
    }

    compact = _build_llm_snapshot(snapshot)
    prompt = _build_prompt(snapshot)
    prompt_json_part = prompt.split("输入 JSON：", 1)[1]

    assert compact["fundamental_facts"]["latest_financial_period"]["net_profit_yi"] == 2.71
    assert compact["fundamental_facts"]["latest_balance_sheet"]["contract_liabilities_yi"] == 21.72
    assert compact["technical_facts"]["recent_bar_count"] == 8
    assert compact["news_facts"]["social_rumors"][0]["source_note"].startswith("X/社媒小作文")
    assert compact["fundamental_facts"]["business_summary"]["main_business"] == "液晶电视结构件与AI算力业务"
    assert "算力业务" in compact["fundamental_facts"]["business_summary"]["business_tags"]
    assert any(
        item["segment"] == "算力业务" and item["gross_margin_pct"] == 49.69
        for item in compact["fundamental_facts"]["business_summary"]["top_segments"]
    )
    assert compact["fundamental_facts"]["business_summary"]["major_change_signals"][0]["title"] == "公司再融资问询回复披露募投进展"
    assert any(
        item["title"] == "投资者关系活动记录表披露SSD模组进展"
        for item in compact["fundamental_facts"]["business_summary"]["progress_signals"]
    )
    assert any(
        item["title"] == "公司未量产PCM存储芯片"
        for item in compact["fundamental_facts"]["business_summary"]["verification_risks"]
    )
    assert any(
        item["title"] == "公司未量产PCM存储芯片"
        for item in compact["news_facts"]["official_context"]["verification_risks"]
    )
    assert "精密金属冲压结构件、电子元器件、模具、算力业务" in prompt
    assert "financial_rows" not in prompt
    assert "business_composition" not in prompt
    assert "经营范围" not in prompt
    assert "recent_kline" not in prompt
    assert "https://example.test" not in prompt
    assert "\n  \"" not in prompt_json_part

    sanitized = _sanitize_result(
        {
            "sections": {
                "fundamental": {"score": 45, "conclusion": "财务承压", "evidence": ["2026Q1净利下降"], "risk": "利润下滑"}
            }
        },
        snapshot,
    )
    fundamental_evidence = sanitized["sections"]["fundamental"]["evidence"]
    assert fundamental_evidence[0].startswith("主营业务：")
    assert any("主营构成" in item for item in fundamental_evidence)
    assert any("重大变化线索" in item for item in fundamental_evidence)
    assert any("研发/量产进展" in item for item in fundamental_evidence)
    assert any("核验反证" in item for item in fundamental_evidence)
