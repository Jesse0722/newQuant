"""Independent upstream identity evidence for audited historical quote repairs."""
from __future__ import annotations

import hashlib
import json

IDENTITY_ATTR = "newquant_source_identity"
IDENTITY_POLICY = "upstream-identity-v1"


def identity_code(provider, raw_code, raw_market=None):
    code = str(raw_code or "").strip()
    if provider == "baostock":
        parts = code.lower().split(".")
        if len(parts) == 2 and parts[0] in ("sh", "sz", "bj") and len(parts[1]) == 6 and parts[1].isdigit():
            return parts[1] + "." + parts[0].upper()
    elif provider == "tushare":
        return code.upper()
    elif provider == "akshare" and len(code) == 6 and code.isdigit():
        # Eastmoney uses market=0 for both Shenzhen and Beijing. Require the
        # upstream market plus a valid exchange-specific security-code family.
        market = str(raw_market)
        if market == "1" and code.startswith(("600", "601", "603", "605", "688", "689")):
            return code + ".SH"
        if market == "0" and code.startswith(("000", "001", "002", "003", "300", "301")):
            return code + ".SZ"
        if market == "0" and code.startswith(("43", "83", "87", "88", "92")):
            return code + ".BJ"
    raise ValueError("原始证券身份不完整或市场不匹配")


def attach_identity(frame, provider, identities, raw_payload):
    payload = json.dumps(raw_payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    response_hash = hashlib.sha256(payload.encode()).hexdigest()
    frame.attrs[IDENTITY_ATTR] = {
        "version": IDENTITY_POLICY, "provider": provider,
        "rows": [{**row, "response_sha256": response_hash} for row in identities],
    }
    return frame


def verify_row_identity(identity, provider, code, trade_date):
    if not isinstance(identity, dict) or identity.get("provider") != provider:
        raise ValueError("缺少原始来源身份")
    if identity_code(provider, identity.get("raw_code"), identity.get("raw_market")) != code:
        raise ValueError("原始证券身份与请求不一致")
    if identity.get("trade_date") != trade_date:
        raise ValueError("原始身份日期不一致")
    digest = identity.get("response_sha256", "")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("缺少原始响应指纹")
    return identity


def frame_identities(frame, provider, code):
    evidence = frame.attrs.get(IDENTITY_ATTR, {})
    if evidence.get("version") != IDENTITY_POLICY or evidence.get("provider") != provider:
        raise ValueError("来源未提供独立原始身份回显；禁止生成修复快照")
    rows = evidence.get("rows")
    if not isinstance(rows, list) or len(rows) != len(frame):
        raise ValueError("原始身份与行情行数不一致")
    result = {}
    for item in rows:
        day = item.get("trade_date")
        verify_row_identity(item, provider, code, day)
        if day in result:
            raise ValueError("原始身份存在重复日期")
        result[day] = item
    return result
