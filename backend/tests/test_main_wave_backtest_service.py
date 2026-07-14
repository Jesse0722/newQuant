from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.pool import WatchPool, WatchStock
from app.models.stock import DailyQuote, StockBasic
from app.services.main_wave_backtest_service import _backtest_recommendations, run_main_wave_backtest


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _date_range(start: str, count: int) -> list[str]:
    base = datetime.strptime(start, "%Y%m%d")
    return [(base + timedelta(days=i)).strftime("%Y%m%d") for i in range(count)]


def test_run_main_wave_backtest_uses_historical_signals_and_future_returns():
    db = _session()
    pool = WatchPool(id="pool-main-wave", name="主升浪回测池")
    db.add(pool)
    db.add(WatchStock(pool_id=pool.id, ts_code="000001.SZ"))
    db.add(StockBasic(ts_code="000001.SZ", symbol="000001", name="回测股份", industry="软件开发"))

    price = 10.0
    for idx, trade_date in enumerate(_date_range("20260401", 110)):
        price *= 1.012 if idx < 95 else 1.004
        db.add(
            DailyQuote(
                ts_code="000001.SZ",
                trade_date=trade_date,
                open=price * 0.99,
                high=price * 1.02,
                low=price * 0.98,
                close=price,
                pct_chg=1.2 if idx < 95 else 0.4,
                vol=100000.0,
                amount=price * 100000.0,
            )
        )
    db.commit()

    result = run_main_wave_backtest(
        db,
        trade_date_from="20260610",
        trade_date_to="20260625",
        params={
            "scope": pool.id,
            "min_score": 35,
            "statuses": ["main_wave_confirmed", "breakout_tracking", "watching", "accelerating_hot"],
            "entry_stages": ["trend_hold", "pullback_entry_watch", "breakout_wait_pullback"],
            "exclude_overheat": False,
            "holding_days": [1, 3, 5],
        },
        max_signals_per_day=2,
        cooldown_days=3,
    )

    assert result["stock_count"] == 1
    assert result["date_count"] > 0
    assert result["total_signals"] > 0
    assert result["avg_return_1d"] > 0
    assert result["signals"][0]["trigger_date"] <= "20260625"
    assert result["signals"][0]["return_1d"] is not None
    assert result["stage_summary"]
    assert result["performance"]["quote_preload"]["enabled"] is True
    assert result["performance"]["quote_preload"]["loaded_codes"] == 1
    assert result["performance"]["quote_preload"]["row_count"] == 86
    assert result["performance"]["market_proxy_preload"]["enabled"] is True
    assert result["performance"]["market_proxy_preload"]["groups"] == ["sz_main"]
    assert result["quality_notes"]


def test_backtest_recommendations_flag_weak_entry_stage():
    recommendations = _backtest_recommendations(
        stage_summary=[
            {"group": "pullback_entry_watch", "total_signals": 8, "avg_return_5d": 3.2, "win_rate_5d": 62.5},
            {"group": "breakout_wait_pullback", "total_signals": 9, "avg_return_5d": -1.4, "win_rate_5d": 33.3},
        ],
        status_summary=[
            {"group": "main_wave_confirmed", "total_signals": 8, "avg_return_5d": 2.1, "win_rate_5d": 62.5},
            {"group": "divergence_warning", "total_signals": 6, "avg_return_5d": -2.0, "win_rate_5d": 33.3},
        ],
        score_summary=[
            {"group": "50-59", "total_signals": 8, "avg_return_5d": 2.0, "win_rate_5d": 60.0},
            {"group": "80-89", "total_signals": 8, "avg_return_5d": 1.0, "win_rate_5d": 50.0},
        ],
        holding_days=[1, 5, 10],
    )

    assert any(item["type"] == "entry_stage_focus" for item in recommendations)
    assert any(item["type"] == "entry_stage_tighten" for item in recommendations)
    assert any(item["type"] == "score_calibration" for item in recommendations)
