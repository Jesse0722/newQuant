from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Protocol

import pandas as pd
import tushare as ts
import akshare as ak

from app.config import (
    COMPOSITE_ORDER,
    DATA_PROVIDER,
    TUSHARE_API_URL,
    TUSHARE_TOKEN,
)
from app.utils import normalize_ts_code

logger = logging.getLogger(__name__)


def _call_with_retry(label: str, fn, retries: int = 2, base_sleep: float = 0.9):
    """网络类调用：失败时有限次重试（指数退避），最后一次异常向上抛出。"""
    last: BaseException | None = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            logger.warning("%s 第 %s/%s 次失败: %s", label, i + 1, retries, str(e)[:160])
            if i < retries - 1:
                time.sleep(base_sleep * (i + 1))
    assert last is not None
    raise last


class MarketDataProvider(Protocol):
    def get_stock_basic(self, ts_code: str | None = None) -> pd.DataFrame: ...
    def get_daily(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame: ...
    def get_daily_basic(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame: ...
    def get_daily_by_date(self, trade_date: str) -> pd.DataFrame: ...
    def get_rt_k(self, ts_code: str) -> pd.DataFrame: ...
    def get_sse_open_dates(self, end_date: str, lookback_calendar_days: int = 400) -> list[str]: ...
    def get_limit_cpt_list(self, trade_date: str) -> pd.DataFrame: ...
    def get_limit_step(self, trade_date: str) -> pd.DataFrame: ...


class TushareAdapter:
    def __init__(self):
        self._pro = None

    @property
    def pro(self):
        if self._pro is None:
            self._pro = ts.pro_api(TUSHARE_TOKEN)
            if TUSHARE_API_URL:
                self._pro._DataApi__token = TUSHARE_TOKEN
                self._pro._DataApi__http_url = TUSHARE_API_URL
        return self._pro

    def get_stock_basic(self, ts_code: str | None = None) -> pd.DataFrame:
        params = {
            "exchange": "",
            "list_status": "L",
            "fields": "ts_code,symbol,name,area,industry,market,list_date,list_status,float_share",
        }
        if ts_code:
            params["ts_code"] = ts_code
        return self.pro.stock_basic(**params)

    def get_daily(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        params = {"ts_code": ts_code}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self.pro.daily(**params)

    def get_daily_basic(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        params = {"ts_code": ts_code, "fields": "ts_code,trade_date,turnover_rate,float_share"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self.pro.daily_basic(**params)

    def get_daily_by_date(self, trade_date: str) -> pd.DataFrame:
        return self.pro.daily(trade_date=trade_date)

    def get_rt_k(self, ts_code: str) -> pd.DataFrame:
        return self.pro.rt_k(ts_code=ts_code)

    def get_sse_open_dates(self, end_date: str, lookback_calendar_days: int = 400) -> list[str]:
        ed = datetime.strptime(end_date, "%Y%m%d").date()
        sd = ed - timedelta(days=lookback_calendar_days)
        start_date = sd.strftime("%Y%m%d")
        df = self.pro.trade_cal(
            exchange="SSE",
            start_date=start_date,
            end_date=end_date,
            fields="cal_date,is_open",
        )
        if df is None or df.empty:
            return []
        open_mask = pd.to_numeric(df["is_open"], errors="coerce").eq(1)
        df = df.loc[open_mask]
        if df.empty:
            return []
        norm = pd.to_datetime(df["cal_date"], errors="coerce").dt.strftime("%Y%m%d")
        out = [x for x in norm.dropna().tolist() if x and len(x) == 8]
        return sorted(set(out))

    def get_limit_cpt_list(self, trade_date: str) -> pd.DataFrame:
        return self.pro.limit_cpt_list(trade_date=trade_date)

    def get_limit_step(self, trade_date: str) -> pd.DataFrame:
        return self.pro.limit_step(trade_date=trade_date)


class AkshareAdapter:
    REQUEST_TIMEOUT = 18.0

    @staticmethod
    def _to_ts_code(symbol: str) -> str:
        s = str(symbol).strip()
        if len(s) == 6 and s.startswith("9"):
            return f"{s}.BJ"
        try:
            return normalize_ts_code(s)
        except Exception:
            return ""

    @staticmethod
    def _empty_daily() -> pd.DataFrame:
        return pd.DataFrame(columns=["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"])

    def _spot_df(self) -> pd.DataFrame:
        def _em():
            return ak.stock_zh_a_spot_em()

        def _legacy():
            return ak.stock_zh_a_spot()

        for label, fn in (("ak.stock_zh_a_spot_em", _em), ("ak.stock_zh_a_spot", _legacy)):
            try:
                df = _call_with_retry(label, fn, retries=2)
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                logger.warning("AkShare 行情快照 %s: %s", label, str(e)[:120])
        return pd.DataFrame()

    def _zt_pool_df(self, trade_date: str) -> pd.DataFrame:
        if hasattr(ak, "stock_em_zt_pool"):
            try:
                return _call_with_retry(
                    "stock_em_zt_pool",
                    lambda: ak.stock_em_zt_pool(date=trade_date),
                    retries=2,
                )
            except Exception as e:
                logger.warning("stock_em_zt_pool: %s", str(e)[:120])
        if hasattr(ak, "stock_zt_pool_em"):
            try:
                return _call_with_retry(
                    "stock_zt_pool_em",
                    lambda: ak.stock_zt_pool_em(date=trade_date),
                    retries=2,
                )
            except Exception as e:
                logger.warning("stock_zt_pool_em: %s", str(e)[:120])
        return pd.DataFrame()

    def _stock_basic_single_em(self, ts_code: str) -> pd.DataFrame | None:
        """单股基础信息：东财 push2 接口，避免 stock_info_a_code_name 拉深交所全表。"""
        sym = (ts_code or "").split(".")[0]
        if not sym:
            return None
        sym6 = sym.zfill(6)

        def _fetch():
            try:
                return ak.stock_individual_info_em(symbol=sym6, timeout=self.REQUEST_TIMEOUT)
            except TypeError:
                return ak.stock_individual_info_em(symbol=sym6)

        try:
            raw = _call_with_retry(f"stock_individual_info_em({sym6})", _fetch, retries=2)
        except Exception as e:
            logger.warning("stock_individual_info_em %s: %s", ts_code, str(e)[:120])
            return None
        if raw is None or raw.empty or "item" not in raw.columns:
            return None
        m = dict(zip(raw["item"].astype(str), raw["value"]))
        name = m.get("股票简称")
        if name is None or (isinstance(name, float) and name != name):
            return None
        ind = m.get("行业")
        list_raw = m.get("上市时间")
        list_date = None
        if list_raw is not None and not (isinstance(list_raw, float) and list_raw != list_raw):
            try:
                d = pd.to_datetime(str(list_raw), errors="coerce")
                if pd.notna(d):
                    list_date = d.strftime("%Y%m%d")
            except Exception:
                list_date = None
        fs_raw = m.get("流通股")
        float_share = None
        if fs_raw is not None:
            try:
                v = float(fs_raw)
                if v == v:
                    float_share = v
            except (TypeError, ValueError):
                pass
        row = {
            "ts_code": ts_code,
            "symbol": sym6,
            "name": str(name).strip(),
            "area": None,
            "industry": None if ind is None or (isinstance(ind, float) and ind != ind) else str(ind).strip(),
            "market": None,
            "list_date": list_date,
            "list_status": "L",
            "float_share": float_share,
        }
        return pd.DataFrame([row])

    def get_stock_basic(self, ts_code: str | None = None) -> pd.DataFrame:
        cols = ["ts_code", "symbol", "name", "area", "industry", "market", "list_date", "list_status", "float_share"]
        if ts_code:
            single = self._stock_basic_single_em(ts_code)
            if single is not None and not single.empty:
                return single
            return pd.DataFrame(columns=cols)
        try:
            base = _call_with_retry(
                "stock_info_a_code_name",
                ak.stock_info_a_code_name,
                retries=2,
            )
        except Exception as e:
            logger.warning("get_stock_basic AkShare 全市场: %s", str(e)[:120])
            base = None
        if base is None or base.empty:
            return pd.DataFrame(columns=cols)
        base = base.rename(columns={"code": "symbol", "name": "name"})
        base["symbol"] = base["symbol"].astype(str).str.zfill(6)
        base["ts_code"] = base["symbol"].map(self._to_ts_code)
        base["area"] = None
        base["industry"] = None
        base["market"] = None
        base["list_date"] = None
        base["list_status"] = "L"
        base["float_share"] = None
        return base[cols].copy()

    def get_daily(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        symbol = (ts_code or "").split(".")[0]
        if not symbol:
            return self._empty_daily()
        def _fetch_hist():
            try:
                return ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date or "19700101",
                    end_date=end_date or "20500101",
                    adjust="",
                    timeout=self.REQUEST_TIMEOUT,
                )
            except TypeError:
                return ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date or "19700101",
                    end_date=end_date or "20500101",
                    adjust="",
                )

        try:
            df = _call_with_retry(f"stock_zh_a_hist({symbol})", _fetch_hist, retries=2)
        except Exception as e:
            logger.warning("AkShare get_daily %s: %s", ts_code, str(e)[:120])
            return self._empty_daily()
        if df is None or df.empty:
            return self._empty_daily()
        out = pd.DataFrame()
        out["ts_code"] = ts_code
        out["trade_date"] = pd.to_datetime(df["日期"], errors="coerce").dt.strftime("%Y%m%d")
        out["open"] = pd.to_numeric(df["开盘"], errors="coerce")
        out["high"] = pd.to_numeric(df["最高"], errors="coerce")
        out["low"] = pd.to_numeric(df["最低"], errors="coerce")
        out["close"] = pd.to_numeric(df["收盘"], errors="coerce")
        out["change"] = pd.to_numeric(df.get("涨跌额"), errors="coerce")
        out["pre_close"] = out["close"] - out["change"]
        out["pct_chg"] = pd.to_numeric(df.get("涨跌幅"), errors="coerce")
        out["vol"] = pd.to_numeric(df.get("成交量"), errors="coerce")
        out["amount"] = pd.to_numeric(df.get("成交额"), errors="coerce")
        return out.dropna(subset=["trade_date"]).sort_values("trade_date", ascending=False).reset_index(drop=True)

    def get_daily_basic(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        empty = pd.DataFrame(columns=["ts_code", "trade_date", "turnover_rate", "float_share"])
        symbol = (ts_code or "").split(".")[0]
        if not symbol:
            return empty
        def _fetch_hist():
            try:
                return ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date or "19700101",
                    end_date=end_date or "20500101",
                    adjust="",
                    timeout=self.REQUEST_TIMEOUT,
                )
            except TypeError:
                return ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date or "19700101",
                    end_date=end_date or "20500101",
                    adjust="",
                )

        try:
            df = _call_with_retry(f"stock_zh_a_hist_basic({symbol})", _fetch_hist, retries=2)
        except Exception as e:
            logger.warning("AkShare get_daily_basic %s: %s", ts_code, str(e)[:120])
            return empty
        if df is None or df.empty:
            return empty
        out = pd.DataFrame()
        out["ts_code"] = ts_code
        out["trade_date"] = pd.to_datetime(df["日期"], errors="coerce").dt.strftime("%Y%m%d")
        out["turnover_rate"] = pd.to_numeric(df.get("换手率"), errors="coerce")
        out["float_share"] = None
        return out.dropna(subset=["trade_date"]).sort_values("trade_date", ascending=False).reset_index(drop=True)

    def get_daily_by_date(self, trade_date: str) -> pd.DataFrame:
        # AkShare 无法像 Tushare 一样直接按历史日期返回“全市场日线”。
        # 这里若强行使用实时快照并打上历史 trade_date，会污染数据库（同一快照被写入多天）。
        today = datetime.now().strftime("%Y%m%d")
        if trade_date != today:
            logger.warning(
                "AkShare get_daily_by_date 不支持历史日期(%s)，返回空结果避免写入错误历史K线",
                trade_date,
            )
            return self._empty_daily()
        try:
            df = self._spot_df()
        except Exception as e:
            logger.warning("get_daily_by_date spot: %s", str(e)[:120])
            return self._empty_daily()
        if df is None or df.empty:
            return self._empty_daily()
        if "代码" not in df.columns:
            return self._empty_daily()
        out = pd.DataFrame()
        out["ts_code"] = df["代码"].astype(str).str.zfill(6).map(self._to_ts_code)
        out["trade_date"] = trade_date
        out["open"] = pd.to_numeric(df.get("今开"), errors="coerce")
        out["high"] = pd.to_numeric(df.get("最高"), errors="coerce")
        out["low"] = pd.to_numeric(df.get("最低"), errors="coerce")
        out["close"] = pd.to_numeric(df.get("最新价"), errors="coerce")
        out["pre_close"] = pd.to_numeric(df.get("昨收"), errors="coerce")
        out["change"] = out["close"] - out["pre_close"]
        out["pct_chg"] = pd.to_numeric(df.get("涨跌幅"), errors="coerce")
        # 与 Tushare 对齐：vol=手，amount=千元
        out["vol"] = pd.to_numeric(df.get("成交量"), errors="coerce") / 100.0
        out["amount"] = pd.to_numeric(df.get("成交额"), errors="coerce") / 1000.0

        # 过滤停牌/异常快照：AkShare spot 里存在 open/high/low=0、close 有值的行。
        # 若直接写入 daily_quote 会导致 K 线图严重失真（长时间贴地或畸形）。
        valid = (
            (out["ts_code"].notna())
            & (out["ts_code"] != "")
            & (out["close"] > 0)
            & (out["open"] > 0)
            & (out["high"] > 0)
            & (out["low"] > 0)
            & (out["high"] >= out["low"])
            & (out["high"] >= out["open"])
            & (out["high"] >= out["close"])
            & (out["low"] <= out["open"])
            & (out["low"] <= out["close"])
        )
        return out.loc[valid].reset_index(drop=True)

    def get_rt_k(self, ts_code: str) -> pd.DataFrame:
        try:
            df = self._spot_df()
        except Exception as e:
            logger.warning("get_rt_k spot: %s", str(e)[:120])
            return pd.DataFrame()
        if df is None or df.empty or "代码" not in df.columns:
            return pd.DataFrame()
        wanted = {c.strip() for c in ts_code.split(",") if c.strip()}
        df["ts_code"] = df["代码"].astype(str).str.zfill(6).map(self._to_ts_code)
        df = df[(df["ts_code"].notna()) & (df["ts_code"] != "")]
        df = df[df["ts_code"].isin(wanted)].copy()
        if df.empty:
            return pd.DataFrame()
        out = pd.DataFrame()
        out["ts_code"] = df["ts_code"]
        out["open"] = pd.to_numeric(df.get("今开"), errors="coerce")
        out["high"] = pd.to_numeric(df.get("最高"), errors="coerce")
        out["low"] = pd.to_numeric(df.get("最低"), errors="coerce")
        out["close"] = pd.to_numeric(df.get("最新价"), errors="coerce")
        out["pre_close"] = pd.to_numeric(df.get("昨收"), errors="coerce")
        out["vol"] = pd.to_numeric(df.get("成交量"), errors="coerce")
        out["amount"] = pd.to_numeric(df.get("成交额"), errors="coerce")
        return out

    def get_sse_open_dates(self, end_date: str, lookback_calendar_days: int = 400) -> list[str]:
        try:
            full = _call_with_retry("tool_trade_date_hist_sina", ak.tool_trade_date_hist_sina, retries=2)
        except Exception as e:
            logger.warning("get_sse_open_dates AkShare: %s", str(e)[:120])
            return []
        if full is None or full.empty or "trade_date" not in full.columns:
            return []
        norm = pd.to_datetime(full["trade_date"], errors="coerce").dt.strftime("%Y%m%d")
        out = sorted(x for x in norm.dropna().tolist() if x and len(x) == 8 and x <= end_date)
        if not out:
            return []
        return out[-lookback_calendar_days:]

    def get_limit_cpt_list(self, trade_date: str) -> pd.DataFrame:
        try:
            zt = self._zt_pool_df(trade_date)
            if zt is None or zt.empty or "所属行业" not in zt.columns or "代码" not in zt.columns:
                return pd.DataFrame()
            if "涨跌幅" not in zt.columns:
                zt = zt.copy()
                zt["涨跌幅"] = float("nan")
            g = zt.groupby("所属行业", dropna=False).agg(
                up_nums=("代码", "count"),
                pct_chg=("涨跌幅", "mean"),
            ).reset_index().rename(columns={"所属行业": "name"})
            g["trade_date"] = trade_date
            g["ts_code"] = None
            g["rank"] = g["up_nums"].rank(method="min", ascending=False).astype(int).astype(str)
            return g[["ts_code", "name", "trade_date", "up_nums", "pct_chg", "rank"]]
        except Exception as e:
            logger.warning("get_limit_cpt_list: %s", str(e)[:120])
            return pd.DataFrame()

    def get_limit_step(self, trade_date: str) -> pd.DataFrame:
        try:
            zt = self._zt_pool_df(trade_date)
            if zt is None or zt.empty or "代码" not in zt.columns:
                return pd.DataFrame()
            out = pd.DataFrame()
            out["ts_code"] = zt["代码"].astype(str).str.zfill(6).map(self._to_ts_code)
            out["name"] = zt.get("名称", "")
            out["trade_date"] = trade_date
            out["nums"] = pd.to_numeric(zt.get("连板数"), errors="coerce").fillna(0).astype(int).astype(str)
            return out[["ts_code", "name", "trade_date", "nums"]]
        except Exception as e:
            logger.warning("get_limit_step: %s", str(e)[:120])
            return pd.DataFrame()


class CompositeAdapter:
    def __init__(self, providers: list[MarketDataProvider]):
        self.providers = providers

    @staticmethod
    def _is_empty_result(method: str, result) -> bool:
        if isinstance(result, pd.DataFrame):
            return result.empty
        if method == "get_sse_open_dates" and isinstance(result, list):
            return len(result) == 0
        return False

    @staticmethod
    def _empty_for(method: str):
        if method == "get_sse_open_dates":
            return []
        return pd.DataFrame()

    def _run(self, method: str, *args, **kwargs):
        last_exc: Exception | None = None
        for p in self.providers:
            fn = getattr(p, method)
            try:
                result = fn(*args, **kwargs)
                if self._is_empty_result(method, result):
                    # 当前源无数据但不算错误，继续换源；避免前一个源已抛错却被误带回
                    last_exc = None
                    continue
                return result
            except Exception as e:
                last_exc = e
                continue
        if last_exc is not None:
            raise last_exc
        return self._empty_for(method)

    def get_stock_basic(self, ts_code: str | None = None) -> pd.DataFrame:
        return self._run("get_stock_basic", ts_code=ts_code)

    def get_daily(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        return self._run("get_daily", ts_code=ts_code, start_date=start_date, end_date=end_date)

    def get_daily_basic(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        return self._run("get_daily_basic", ts_code=ts_code, start_date=start_date, end_date=end_date)

    def get_daily_by_date(self, trade_date: str) -> pd.DataFrame:
        return self._run("get_daily_by_date", trade_date=trade_date)

    def get_rt_k(self, ts_code: str) -> pd.DataFrame:
        return self._run("get_rt_k", ts_code=ts_code)

    def get_sse_open_dates(self, end_date: str, lookback_calendar_days: int = 400) -> list[str]:
        return self._run("get_sse_open_dates", end_date=end_date, lookback_calendar_days=lookback_calendar_days)

    def get_limit_cpt_list(self, trade_date: str) -> pd.DataFrame:
        return self._run("get_limit_cpt_list", trade_date=trade_date)

    def get_limit_step(self, trade_date: str) -> pd.DataFrame:
        return self._run("get_limit_step", trade_date=trade_date)


def _provider_by_name(name: str) -> MarketDataProvider:
    if name == "akshare":
        return AkshareAdapter()
    if name == "tushare":
        return TushareAdapter()
    raise ValueError(f"未知数据源: {name}")


def _build_provider(provider_name: str) -> MarketDataProvider:
    if provider_name == "composite":
        providers: list[MarketDataProvider] = []
        for n in COMPOSITE_ORDER:
            try:
                providers.append(_provider_by_name(n))
            except Exception:
                continue
        if not providers:
            providers = [TushareAdapter()]
        return CompositeAdapter(providers)
    try:
        return _provider_by_name(provider_name)
    except Exception:
        return TushareAdapter()


class ProviderRouter:
    """保持单例引用不变，支持运行时切换底层 provider。"""

    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        self.provider = _build_provider(provider_name)

    def switch(self, provider_name: str) -> str:
        name = (provider_name or "").strip().lower()
        if name not in ("tushare", "akshare", "composite"):
            raise ValueError("provider 仅支持 tushare / akshare / composite")
        self.provider_name = name
        self.provider = _build_provider(name)
        return self.provider_name

    def get_stock_basic(self, ts_code: str | None = None) -> pd.DataFrame:
        return self.provider.get_stock_basic(ts_code=ts_code)

    def get_daily(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        return self.provider.get_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

    def get_daily_basic(self, ts_code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        return self.provider.get_daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date)

    def get_daily_by_date(self, trade_date: str) -> pd.DataFrame:
        return self.provider.get_daily_by_date(trade_date=trade_date)

    def get_rt_k(self, ts_code: str) -> pd.DataFrame:
        return self.provider.get_rt_k(ts_code=ts_code)

    def get_sse_open_dates(self, end_date: str, lookback_calendar_days: int = 400) -> list[str]:
        return self.provider.get_sse_open_dates(end_date=end_date, lookback_calendar_days=lookback_calendar_days)

    def get_limit_cpt_list(self, trade_date: str) -> pd.DataFrame:
        return self.provider.get_limit_cpt_list(trade_date=trade_date)

    def get_limit_step(self, trade_date: str) -> pd.DataFrame:
        return self.provider.get_limit_step(trade_date=trade_date)


tushare_adapter = ProviderRouter(DATA_PROVIDER)


def get_current_provider_name() -> str:
    return tushare_adapter.provider_name


def switch_provider(provider_name: str) -> str:
    return tushare_adapter.switch(provider_name)
