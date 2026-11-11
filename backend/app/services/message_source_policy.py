"""Shared deterministic provenance and counterevidence rules."""
from __future__ import annotations

import hashlib

OFFICIAL_CHANNELS = {"announcement", "official", "exchange", "company_announcement", "exchange_announcement", "公告", "交易所", "公司公告"}
SOCIAL_CHANNELS = {"x", "twitter", "雪球", "xueqiu", "淘股吧", "weibo", "微博", "小红书", "social"}


def source_policy(evidence: list[dict]) -> dict:
    # Multiple extractors and syndicated copies are not independent sources.
    groups: dict[str, list[dict]] = {}
    for row in evidence:
        if row.get("extraction_method") == "seed":
            continue
        key = row.get("url") or row.get("external_id") or row.get("source_item_id")
        if not key:
            key = hashlib.sha256(str(row.get("evidence_text", "")).encode()).hexdigest()
        groups.setdefault(key, []).append(row)
    priority = {"contradiction": 3, "risk": 2, "support": 1, "neutral": 0}
    sources = []
    support_confidences = []
    for key, rows in groups.items():
        def channel(row):
            return str(row.get("channel") or row.get("source") or "").casefold()
        official = [row for row in rows if channel(row) in OFFICIAL_CHANNELS]
        non_social = [row for row in rows if channel(row) not in SOCIAL_CHANNELS]
        authoritative = official or non_social or rows
        stance = max((row.get("stance", "neutral") for row in rows), key=lambda value: priority.get(value, 0))
        # Preserve all provenance flags before deduplication. A repost's higher
        # confidence cannot erase an official refutation or become another source.
        source = {"source_key": key, "channels": sorted({channel(row) for row in rows}), "stance": stance,
                  "official_stances": sorted({row.get("stance", "neutral") for row in official}),
                  "official_contradiction": any(row.get("stance") == "contradiction" for row in official),
                  "social_only": all(channel(row) in SOCIAL_CHANNELS for row in rows)}
        sources.append(source)
        supports = [row.get("confidence", 0) for row in authoritative if row.get("stance") == "support"]
        if stance == "support" and supports:
            support_confidences.append(max(supports))
    return {
        "independent_sources": len(sources), "seed_only": not sources,
        "social_only": bool(sources) and all(source["social_only"] for source in sources),
        "official_contradiction": any(source["official_contradiction"] for source in sources),
        "contradiction_count": sum(source["stance"] == "contradiction" for source in sources),
        "risk_count": sum(source["stance"] == "risk" for source in sources),
        "support_confidences": support_confidences,
        "source_groups": sources,
    }
