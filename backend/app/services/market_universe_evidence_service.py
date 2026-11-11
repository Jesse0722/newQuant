"""Pure offline binding of retrospective market-universe evidence packages.

Hashes verify bytes and references, not authority, independence or availability at
historical decision time. This module never imports application configuration,
connects to a database, or fetches a URL.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

VERSION = "market-universe-evidence-v1"
DENOMINATOR_BASIS = "listed_a_share_excluding_full_day_suspensions"
MARKETS = {"SH", "SZ", "BJ"}
WARNING = ("SHA-256仅校验文件字节与引用绑定，不认证来源权威性、实际独立性或全市场真实完整性；"
           "本证据为retrospective事后审计，不证明历史决策时已可得。")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + "必须为非空字符串")
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("SHA256必须为64位小写十六进制")
    return value


def validated_dates(values):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("日期grid不能为空")
    if any(not isinstance(day, str) or not re.fullmatch(r"[0-9]{8}", day) for day in values):
        raise ValueError("日期grid必须为YYYYMMDD字符串")
    for day in values:
        datetime.strptime(day, "%Y%m%d")
    if len(set(values)) != len(values):
        raise ValueError("日期grid重复")
    return sorted(values)


def normalized_universe_digest(universe):
    payload = [{"trade_date": day, "codes": sorted(universe[day])} for day in sorted(universe)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def validate_https_url(value):
    value = _text(value, "来源URL")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("来源URL包含空白或控制字符")
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        if (parsed.scheme != "https" or not host or parsed.username is not None or parsed.password is not None
                or "\\" in host or "%" in host or (port is not None and not 1 <= port <= 65535)):
            raise ValueError
        if ":" in host:
            ipaddress.IPv6Address(host)
        else:
            labels = host.rstrip(".").encode("idna").decode("ascii").split(".")
            if any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels):
                raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError("来源URL必须为有合法host且无userinfo的HTTPS地址") from None
    return value


def _url_identity(value):
    parsed = urlsplit(validate_https_url(value))
    host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    host = "[" + host + "]" if ":" in host else host
    authority = host if parsed.port in (None, 443) else host + ":" + str(parsed.port)
    return urlunsplit(("https", authority, parsed.path or "/", parsed.query, ""))


def _read_regular(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("证据必须是regular file")
        return handle.read()


def _package_bytes(base, relative):
    relative = Path(_text(relative, "来源path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("来源path必须为包内相对路径，禁止绝对或父目录路径")
    resolved = (base / relative).resolve(strict=True)
    if not resolved.is_relative_to(base) or not resolved.is_file():
        raise ValueError("来源path必须解析到包内regular file")
    # Resolve an in-package symlink once, then open canonical components through
    # directory descriptors without following replacement symlinks during I/O.
    descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = resolved.relative_to(base).parts
        for part in parts[:-1]:
            next_descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(file_descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("来源必须为regular file")
            body = handle.read()
    finally:
        os.close(descriptor)
    return body, str(resolved)


def _unique_strings(value, label):
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(label + "必须为非空字符串列表")
    if len(set(value)) != len(value):
        raise ValueError(label + "包含重复项")
    return value


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("manifest包含重复JSON key")
        result[key] = value
    return result


def validate_evidence_manifest(path, pinned_sha256, *, dates, markets, universe_sha256,
                               counts_sha256, universe_digest, control_urls):
    """Validate a pinned package and return provenance; no authority inference."""
    try:
        manifest_path = Path(path).resolve(strict=True)
        body = _read_regular(manifest_path)
        manifest_sha256 = hashlib.sha256(body).hexdigest()
        if manifest_sha256 != _sha(pinned_sha256):
            raise ValueError("manifest与pinned SHA256不匹配")
        def invalid_constant(_value):
            raise ValueError("manifest包含非法JSON数值")
        manifest = json.loads(body.decode("utf-8-sig"), object_pairs_hook=_json_object,
                              parse_constant=invalid_constant)
        if not isinstance(manifest, dict) or manifest.get("version") != VERSION:
            raise ValueError("manifest版本不支持")
        scope = manifest.get("scope")
        if scope not in {"full_market_point_in_time", "security_subset"}:
            raise ValueError("manifest scope无效")
        if manifest.get("temporal_basis") != "retrospective" or manifest.get("denominator_basis") != DENOMINATOR_BASIS:
            raise ValueError("manifest时间或分母口径不匹配")
        requested_dates = validated_dates(dates)
        manifest_dates = validated_dates(manifest.get("dates"))
        if not set(requested_dates) <= set(manifest_dates):
            raise ValueError("manifest日期未覆盖audit grid")
        declared_markets = set(_unique_strings(manifest.get("markets"), "markets"))
        if (not declared_markets <= MARKETS or not set(markets) <= declared_markets
                or (scope == "full_market_point_in_time" and declared_markets != MARKETS)):
            raise ValueError("manifest市场范围不匹配")
        if (_sha(manifest.get("universe_sha256")) != _sha(universe_sha256)
                or _sha(manifest.get("counts_sha256")) != _sha(counts_sha256)):
            raise ValueError("manifest与CSV输入字节不匹配")
        universe_ids = set(_unique_strings(manifest.get("universe_source_ids"), "universe_source_ids"))
        control_ids = set(_unique_strings(manifest.get("control_source_ids"), "control_source_ids"))
        if universe_ids & control_ids:
            raise ValueError("universe/control来源ID不能重用")
        sources = manifest.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError("manifest缺少原件来源")
        provenance = {}
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("原件来源格式错误")
            identifier = _text(source.get("id"), "来源ID")
            if identifier in provenance:
                raise ValueError("原件来源ID重复")
            url = validate_https_url(source.get("url"))
            observed_at = _text(source.get("observed_at"), "observed_at")
            observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise ValueError("observed_at必须带时区")
            locator = _text(source.get("locator"), "locator")
            original, resolved_path = _package_bytes(manifest_path.parent, source.get("path"))
            source_sha256 = hashlib.sha256(original).hexdigest()
            if source_sha256 != _sha(source.get("sha256")):
                raise ValueError("来源原件SHA256不匹配")
            provenance[identifier] = {"id": identifier, "url": url, "path": source["path"],
                "resolved_path": resolved_path, "sha256": source_sha256,
                "observed_at": observed_at, "locator": locator}
        if set(provenance) != universe_ids | control_ids:
            raise ValueError("来源引用缺失或存在未分组原件")
        universe_urls = {_url_identity(provenance[key]["url"]) for key in universe_ids}
        control_source_urls = {_url_identity(provenance[key]["url"]) for key in control_ids}
        universe_hashes = {provenance[key]["sha256"] for key in universe_ids}
        control_hashes = {provenance[key]["sha256"] for key in control_ids}
        if universe_urls & control_source_urls or universe_hashes & control_hashes:
            raise ValueError("universe/control来源URL或原件内容不能重用")
        if not {_url_identity(value) for value in control_urls} <= control_source_urls:
            raise ValueError("counts CSV来源URL不属于control sources")
        return {"status": "bound", "scope": scope, "bound": True, "inputs_bound": True,
            "originals_verified": True, "manifest_sha256": manifest_sha256, "manifest_file": str(manifest_path),
            "universe_sha256": universe_sha256, "counts_sha256": counts_sha256,
            "universe_digest": universe_digest, "audit_dates": requested_dates,
            "manifest_dates": manifest_dates, "markets": sorted(declared_markets),
            "temporal_basis": "retrospective", "denominator_basis": DENOMINATOR_BASIS,
            "universe_source_ids": sorted(universe_ids), "control_source_ids": sorted(control_ids),
            "sources": [provenance[key] for key in sorted(provenance)], "warning": WARNING}
    except (OSError, UnicodeError, TypeError, KeyError) as exc:
        raise ValueError("证据包读取或结构校验失败") from exc
