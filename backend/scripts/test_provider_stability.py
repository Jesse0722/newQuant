#!/usr/bin/env python3
"""
对各 MarketDataProvider 做端到端稳定性探测（需网络）。

用法（在 backend 目录、已激活 venv）:
  DATA_PROVIDER=baostock python scripts/test_provider_stability.py
  DATA_PROVIDER=akshare python scripts/test_provider_stability.py
  DATA_PROVIDER=tushare python scripts/test_provider_stability.py
  DATA_PROVIDER=composite python scripts/test_provider_stability.py

可选环境变量:
  PROVIDER_STABILITY_FULL=1  — 额外跑 AkShare/Tushare 单源与 Composite 直连层（耗时长）
  PROVIDER_STABILITY_SLOW=1 — 增加全市场快照 get_daily_by_date（很慢）
  PROVIDER_STABILITY_RT_K=1 — 探测 get_rt_k（composite 退回 Tushare 时可能极慢）

退出码：任一项失败为 1；全部通过为 0。
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

# 确保可 import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DATA_PROVIDER  # noqa: E402
from app.services.tushare_adapter import (  # noqa: E402
    AkshareAdapter,
    BaoStockAdapter,
    CompositeAdapter,
    ProviderRouter,
    TushareAdapter,
    _build_provider,
)


def _ok(name: str, cond: bool, detail: str = "") -> dict:
    return {"name": name, "ok": bool(cond), "detail": detail}


def probe_one(provider_label: str, router) -> list[dict]:
    cal_day = datetime.now().strftime("%Y%m%d")
    out: list[dict] = []
    t0 = time.perf_counter()

    try:
        dates = router.get_sse_open_dates(cal_day, lookback_calendar_days=40)
        out.append(_ok("get_sse_open_dates", len(dates) >= 3, f"n={len(dates)}"))
    except Exception as e:
        out.append(_ok("get_sse_open_dates", False, str(e)[:200]))

    try:
        df = router.get_daily("000001.SZ", start_date="20240101", end_date="20240110")
        out.append(_ok("get_daily", df is not None and not df.empty, f"rows={0 if df is None else len(df)}"))
    except Exception as e:
        out.append(_ok("get_daily", False, str(e)[:200]))

    try:
        bf = router.get_daily_basic("000001.SZ", start_date="20240101", end_date="20240110")
        out.append(_ok("get_daily_basic", bf is not None and not bf.empty, f"rows={0 if bf is None else len(bf)}"))
    except Exception as e:
        out.append(_ok("get_daily_basic", False, str(e)[:200]))

    include_slow = (os.environ.get("PROVIDER_STABILITY_SLOW") or "").strip() in ("1", "true", "yes")
    if include_slow:
        try:
            spot = router.get_daily_by_date(cal_day)
            rows = 0 if spot is None else len(spot)
            out.append(_ok("get_daily_by_date(全市场快照)", rows > 0, f"rows={rows}"))
        except Exception as e:
            out.append(_ok("get_daily_by_date(全市场快照)", False, str(e)[:200]))

    try:
        sb = router.get_stock_basic(ts_code="000001.SZ")
        out.append(_ok("get_stock_basic(单股)", sb is not None and len(sb) >= 1, f"rows={0 if sb is None else len(sb)}"))
    except Exception as e:
        out.append(_ok("get_stock_basic(单股)", False, str(e)[:200]))

    if (os.environ.get("PROVIDER_STABILITY_RT_K") or "").strip() in ("1", "true", "yes"):
        try:
            rtk = router.get_rt_k("000001.SZ,600000.SH")
            out.append(_ok("get_rt_k", rtk is not None and len(rtk) >= 1, f"rows={0 if rtk is None else len(rtk)}"))
        except Exception as e:
            out.append(_ok("get_rt_k", False, str(e)[:200]))
    else:
        out.append(_ok("get_rt_k", True, "skipped（设 PROVIDER_STABILITY_RT_K=1 启用）"))

    last_td = cal_day
    try:
        dlist = router.get_sse_open_dates(cal_day, lookback_calendar_days=400)
        if dlist:
            last_td = dlist[-1]
    except Exception:
        pass

    try:
        ls = router.get_limit_step(last_td)
        out.append(_ok("get_limit_step", True, f"trade_date={last_td} rows={0 if ls is None else len(ls)}"))
    except Exception as e:
        out.append(_ok("get_limit_step", False, str(e)[:200]))

    try:
        cp = router.get_limit_cpt_list(last_td)
        out.append(_ok("get_limit_cpt_list", True, f"rows={0 if cp is None else len(cp)}"))
    except Exception as e:
        out.append(_ok("get_limit_cpt_list", False, str(e)[:200]))

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    for row in out:
        row["provider"] = provider_label
        row["elapsed_ms_total"] = elapsed_ms
    return out


def main() -> int:
    name = (os.environ.get("DATA_PROVIDER") or DATA_PROVIDER or "composite").strip().lower()
    full_layers = (os.environ.get("PROVIDER_STABILITY_FULL") or "").strip() in ("1", "true", "yes")
    report: dict = {"provider_env": name, "full_layers": full_layers, "layers": {}}

    # 当前路由（与运行中 app 一致）
    router = ProviderRouter(name)
    report["layers"]["app_router"] = probe_one(f"ProviderRouter({router.provider_name})", router)

    if full_layers:
        for label, ctor in (
            ("BaoStockAdapter", lambda: BaoStockAdapter()),
            ("AkshareAdapter", lambda: AkshareAdapter()),
            ("TushareAdapter", lambda: TushareAdapter()),
        ):
            try:
                ad = ctor()
                key = label.split("Adapter")[0].lower()
                if name == "composite" or name == key or (name == "tushare" and key == "tushare"):
                    report["layers"][label] = probe_one(label, ad)
            except Exception as e:
                report["layers"][label] = [{"name": "init", "ok": False, "detail": str(e)[:200], "provider": label}]

        if name == "composite":
            try:
                comp = _build_provider("composite")
                if isinstance(comp, CompositeAdapter):
                    report["layers"]["CompositeAdapter_direct"] = probe_one("CompositeAdapter", comp)
            except Exception as e:
                report["layers"]["CompositeAdapter_direct"] = [{"name": "init", "ok": False, "detail": str(e)[:200]}]

    print(json.dumps(report, ensure_ascii=False, indent=2))

    failed = 0
    for layer, rows in report["layers"].items():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not r.get("ok"):
                failed += 1
                print(f"[FAIL] {layer} :: {r.get('name')}: {r.get('detail')}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
