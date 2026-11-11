from __future__ import annotations

import pandas as pd
import pytest

from app.models.stock import DailyQuote
from app.services import sync_service
from app.services.market_data_capabilities import ProviderCapabilities

CAPABILITIES = ProviderCapabilities(name="fixture", history_by_date=False, history_by_symbol=True,
    snapshot_by_date=False, markets=("SZ",), volume_unit="lot", amount_unit="thousand_cny",
    requires_credentials=False, enabled=True, reliable_pre_close=True)


class _FakeQuery:
    def __init__(self, scalar_value=None, first_value=None):
        self._scalar_value = scalar_value
        self._first_value = first_value

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_value

    def scalar(self):
        return self._scalar_value


class _FakeDb:
    def __init__(self):
        self.info = {}
        self.added: list[DailyQuote] = []
        self.query_calls = 0

    def query(self, *args, **kwargs):
        self.query_calls += 1
        if self.query_calls == 1:
            return _FakeQuery(scalar_value=100)
        if self.query_calls == 2:
            return _FakeQuery(first_value=("20260415",))
        return _FakeQuery(first_value=None)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def rollback(self):
        return None


def test_sync_daily_filters_invalid_ts_code_rows(monkeypatch):
    fake_db = _FakeDb()

    monkeypatch.setattr(sync_service, "_commit_with_retry", lambda db: None)
    monkeypatch.setattr(sync_service, "_backfill_turnover_rate", lambda *args, **kwargs: None)
    monkeypatch.setattr(sync_service, "latest_daily_k_trade_date_str", lambda: "20260428")

    class _Adapter:
        capabilities = CAPABILITIES
        def get_daily(self, ts_code, start_date=None, end_date=None):
            return pd.DataFrame([
                {"ts_code": "", "trade_date": "20260416", "open": 1, "high": 1, "low": 1, "close": 1},
                {"ts_code": "000062.SZ", "trade_date": "20260416", "open": 2, "high": 2, "low": 2, "close": 2,
                 "pre_close": 2, "pct_chg": 0, "vol": 100, "amount": 200},
                {"ts_code": "000062.SZ", "trade_date": "bad-date", "open": 3, "high": 3, "low": 3, "close": 3},
            ])

    monkeypatch.setattr(sync_service, "tushare_adapter", _Adapter())

    added = sync_service.sync_daily(fake_db, "000062.SZ", 250)

    assert added == 1
    assert len(fake_db.added) == 1
    assert fake_db.added[0].ts_code == "000062.SZ"
    assert fake_db.added[0].trade_date == "20260416"
    assert fake_db.info["daily_sync_quality"]["rejected_quote_count"] == 2


def full_bar(**changes):
    return {"ts_code": "000062.SZ", "trade_date": "20261110", "open": 10, "high": 11,
            "low": 9, "close": 10, "pre_close": 10, "pct_chg": 0, "vol": 100, "amount": 200, **changes}


@pytest.fixture
def quote_db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    engine = create_engine(f"sqlite:///{tmp_path / 'quotes.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(sync_service, "_find_gap_repair_start", lambda *args: None)
    monkeypatch.setattr(sync_service, "_backfill_turnover_rate", lambda *args: None)
    monkeypatch.setattr(sync_service, "latest_daily_k_trade_date_str", lambda: "20261111")
    yield factory
    engine.dispose()


@pytest.mark.parametrize("bad", [
    {"pre_close": None}, {"pct_chg": float("nan")},
    {"low": 12}, {"high": 8}, {"close": 0}, {"ts_code": "000001.SZ"},
    {"trade_date": "20261112"}, {"trade_date": "20260230"},
])
def test_normal_sync_rejects_bad_bars_without_writes(quote_db, monkeypatch, bad):
    class Provider:
        capabilities = CAPABILITIES
        def get_daily(self, **kwargs):
            return pd.DataFrame([full_bar(**bad)])
    monkeypatch.setattr(sync_service, "tushare_adapter", Provider())
    with quote_db() as db:
        with pytest.raises(sync_service.MarketDataValidationError):
            sync_service.sync_daily(db, "000062.SZ", days=10000)
        assert db.query(DailyQuote).count() == 0
        assert db.info["daily_sync_quality"]["rejected_quote_count"] == 1


def test_backward_sync_validates_source_identity_and_preserves_existing(quote_db, monkeypatch):
    class Provider:
        capabilities = CAPABILITIES
        def get_daily(self, **kwargs):
            return pd.DataFrame([full_bar(trade_date="20261109"),
                                 full_bar(ts_code="000001.SZ", trade_date="20261108")])
    monkeypatch.setattr(sync_service, "tushare_adapter", Provider())
    with quote_db() as db:
        db.add(DailyQuote(**full_bar()))
        db.commit()
        assert sync_service.sync_daily_backward(db, "000062.SZ", 2) == 1
        assert db.query(DailyQuote).count() == 2
        assert db.get(DailyQuote, ("000062.SZ", "20261110")).close == 10
        assert db.info["daily_sync_quality"]["rejected_reasons"] == {"security_mismatch": 1}


def test_default_composite_keeps_price_evidence_when_amount_unavailable(quote_db, monkeypatch):
    from app.services.tushare_adapter import TencentAdapter, BaoStockAdapter, CompositeAdapter, ProviderRouter
    tencent, baostock = TencentAdapter(), BaoStockAdapter()
    monkeypatch.setattr(tencent, "get_daily", lambda **kwargs: pd.DataFrame([full_bar(amount=999)]))
    fallback_calls = []
    monkeypatch.setattr(baostock, "get_daily", lambda **kwargs: fallback_calls.append(1) or pd.DataFrame())
    router = ProviderRouter("tencent")
    router.provider = CompositeAdapter([tencent, baostock])
    monkeypatch.setattr(sync_service, "tushare_adapter", router)
    with quote_db() as db:
        assert sync_service.sync_daily(db, "000062.SZ", 10000) == 1
        quote = db.get(DailyQuote, ("000062.SZ", "20261110"))
        assert quote.close == 10 and quote.pre_close == 10
        assert quote.amount is None and quote.vol == 100
        assert db.info["daily_sync_quality"]["unavailable_fields"] == {"amount": 1}
        assert db.info["daily_sync_quality"]["outcome"] == "warning"
        assert fallback_calls == []


def test_composite_falls_back_for_incomplete_core_using_one_normalized_source(quote_db, monkeypatch):
    from app.services.tushare_adapter import TencentAdapter, BaoStockAdapter, CompositeAdapter, ProviderRouter
    tencent, baostock = TencentAdapter(), BaoStockAdapter()
    monkeypatch.setattr(tencent, "get_daily", lambda **kwargs: pd.DataFrame([
        full_bar(trade_date="20261109", pre_close=None), full_bar(amount=999)]))
    # BaoStock supplies shares/CNY; selected bars must be converted exactly once.
    monkeypatch.setattr(baostock, "get_daily", lambda **kwargs: pd.DataFrame([
        full_bar(trade_date="20261109", vol=10000, amount=200000), full_bar(vol=10000, amount=200000)]))
    router = ProviderRouter("tencent")
    router.provider = CompositeAdapter([tencent, baostock])
    monkeypatch.setattr(sync_service, "tushare_adapter", router)
    with quote_db() as db:
        assert sync_service.sync_daily(db, "000062.SZ", 10000) == 2
        quotes = db.query(DailyQuote).all()
        assert all(q.vol == 100 and q.amount == 200 for q in quotes)
        assert db.info["daily_sync_quality"]["provider"] == "baostock"
        assert db.info["daily_sync_quality"]["rejected_quote_count"] == 0
        assert [a["provider"] for a in db.info["daily_sync_quality"]["source_attempts"]] == ["tencent", "baostock"]


@pytest.mark.parametrize("field", ["turnover_rate", "float_share"])
def test_negative_optional_metrics_are_null_with_quality_warning(quote_db, monkeypatch, field):
    class Provider:
        capabilities = CAPABILITIES
        def get_daily(self, **kwargs):
            return pd.DataFrame([full_bar(**{field: -1}, change=-.5)])
    monkeypatch.setattr(sync_service, "tushare_adapter", Provider())
    with quote_db() as db:
        assert sync_service.sync_daily(db, "000062.SZ", 10000) == 1
        quote = db.get(DailyQuote, ("000062.SZ", "20261110"))
        assert getattr(quote, field) is None
        assert quote.change == -.5
        assert db.info["daily_sync_quality"]["unavailable_fields"] == {field: 1}


def test_source_attempt_errors_never_contain_proxy_credentials(quote_db, monkeypatch):
    from app.services.tushare_adapter import CompositeAdapter
    class Bad:
        capabilities = CAPABILITIES
        def get_daily(self, **kwargs):
            raise RuntimeError("https://private-user:private-password@proxy.invalid")
    class Good:
        capabilities = CAPABILITIES
        def get_daily(self, **kwargs):
            return pd.DataFrame([full_bar()])
    with quote_db() as db:
        monkeypatch.setattr(sync_service, "tushare_adapter", CompositeAdapter([Bad(), Good()]))
        assert sync_service.sync_daily(db, "000062.SZ", 10000) == 1
        attempts = db.info["daily_sync_quality"]["source_attempts"]
        assert attempts[0]["error_type"] == "RuntimeError"
        assert "private-password" not in repr(attempts)
        monkeypatch.setattr(sync_service, "tushare_adapter", CompositeAdapter([Bad()]))
        with pytest.raises(RuntimeError) as error:
            sync_service.sync_daily(db, "000062.SZ", 10000)
        assert "private-password" not in str(error.value)


@pytest.mark.parametrize("mode", ["single", "full"])
def test_sparse_metadata_never_clears_known_listing_industry_share(quote_db, monkeypatch, mode):
    from app.models.stock import StockBasic
    frame = pd.DataFrame([{"ts_code": "000062.SZ", "name": None, "industry": None,
                           "list_date": None, "float_share": float("nan"), "list_status": "L"}])
    class Provider:
        def get_stock_basic(self, **kwargs):
            return frame
    monkeypatch.setattr(sync_service, "tushare_adapter", Provider())
    with quote_db() as db:
        db.add(StockBasic(ts_code="000062.SZ", name="已知名称", industry="软件", list_date="20000101",
                          float_share=1000, list_status="D"))
        db.commit()
        if mode == "single":
            sync_service.sync_stock_info(db, "000062.SZ")
        else:
            sync_service._sync_stock_basic_full(db)
        current = db.get(StockBasic, "000062.SZ")
        assert (current.name, current.industry, current.list_date, current.float_share, current.list_status) == (
            "已知名称", "软件", "20000101", 1000, "D")
        frame.attrs["newquant_authoritative_fields"] = ("list_status",)
        sync_service.sync_stock_info(db, "000062.SZ")
        assert current.list_status == "L"
