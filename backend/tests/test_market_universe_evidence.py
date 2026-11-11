"""Synthetic fixtures test package structure only; they are not market evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.market_data_quality_service import load_universe
from app.services.market_universe_evidence_service import DENOMINATOR_BASIS


def write_synthetic_bundle(directory, universe, *, scope="full_market_point_in_time"):
    directory.mkdir(parents=True, exist_ok=True)
    u = directory / "universe.csv"
    c = directory / "counts.csv"
    u.write_text("trade_date,ts_code,security_type,is_listed,is_trading\n" + "".join(
        f"{day},{code},a_share,1,1\n" for day in sorted(universe) for code in sorted(universe[day])))
    c.write_text("trade_date,expected_count,source_url\n" + "".join(
        f"{day},{len(universe[day])},https://control.example.invalid/synthetic\n" for day in sorted(universe)))
    sources = []
    for identifier, host in (("universe", "universe"), ("control", "control")):
        original = directory / (identifier + ".txt")
        original.write_text("SYNTHETIC TEST ONLY: " + identifier)
        sources.append({"id": identifier, "url": f"https://{host}.example.invalid/synthetic",
            "path": original.name, "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            "observed_at": "2026-11-11T12:00:00+08:00", "locator": "synthetic test fixture only"})
    manifest = {"version": "market-universe-evidence-v1", "scope": scope,
        "temporal_basis": "retrospective", "dates": sorted(universe), "markets": ["SH", "SZ", "BJ"],
        "denominator_basis": DENOMINATOR_BASIS,
        "universe_sha256": hashlib.sha256(u.read_bytes()).hexdigest(),
        "counts_sha256": hashlib.sha256(c.read_bytes()).hexdigest(),
        "universe_source_ids": ["universe"], "control_source_ids": ["control"], "sources": sources}
    path = directory / "evidence.json"
    write_manifest(path, manifest)
    return u, c, path


def write_manifest(path, manifest):
    path.write_text(json.dumps(manifest, sort_keys=True))


def load_bundle(bundle, dates=None, *, pin=None):
    u, c, path = bundle
    if dates is None:
        dates = json.loads(path.read_text())["dates"]
    return load_universe(u, dates, c, evidence_manifest=path,
        evidence_sha256=pin or hashlib.sha256(path.read_bytes()).hexdigest())


def synthetic_universe(directory, universe, *, scope="full_market_point_in_time"):
    return load_bundle(write_synthetic_bundle(directory, universe, scope=scope))


@pytest.fixture
def bundle(tmp_path):
    return write_synthetic_bundle(tmp_path / "package", {"20261102": {"000001.SZ"}})


def test_synthetic_full_structure_and_subset_have_distinct_qualification(tmp_path):
    for scope, qualified in (("full_market_point_in_time", True), ("security_subset", False)):
        _, info = synthetic_universe(tmp_path / scope, {"20261102": {"000001.SZ"}}, scope=scope)
        assert info["counts_match"] is True
        assert info["evidence"]["bound"] is True
        assert info["control_totals_verified"] is qualified
        assert "不认证" in info["warning"] and "retrospective" in info["warning"]
        assert info["evidence"]["sources"][0]["locator"] == "synthetic test fixture only"


def test_legacy_counts_are_diagnostic_only(bundle):
    u, c, _ = bundle
    _, info = load_universe(u, ["20261102"], c)
    assert info["counts_match"] is True
    assert info["control_totals_verified"] is False
    assert info["status"] == "diagnostic_counts_matched"


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(scope="unknown"),
    lambda m: m.update(dates=["20261103"]),
    lambda m: m.update(dates=["20261102", "20261102"]),
    lambda m: m.update(markets=["SH", "SZ"]),
    lambda m: m.update(markets=["SH", "SZ", "BJ", "BJ"]),
    lambda m: m.update(temporal_basis="contemporaneous"),
    lambda m: m.update(denominator_basis="current_master"),
    lambda m: m.update(universe_sha256="0" * 64),
    lambda m: m.update(counts_sha256="0" * 64),
    lambda m: m.update(control_source_ids=["universe"]),
    lambda m: m.update(universe_source_ids=["missing"]),
    lambda m: m["sources"].append(dict(m["sources"][0])),
    lambda m: m["sources"][0].update(url="https://control.example.invalid/synthetic"),
    lambda m: m["sources"][0].update(url="https://CONTROL.example.invalid:443/synthetic#fragment"),
    lambda m: m["sources"][0].update(url="https://"),
    lambda m: m["sources"][0].update(url="https://user:secret@example.invalid/source"),
    lambda m: m["sources"][0].update(observed_at="2026-11-11T12:00:00"),
    lambda m: m["sources"][0].update(locator=" "),
    lambda m: m["sources"][0].update(path="../outside.txt"),
    lambda m: m["sources"][0].update(path="/tmp/outside.txt"),
    lambda m: m["sources"][0].update(path="missing.txt"),
    lambda m: m["sources"][0].update(sha256="0" * 64),
])
def test_manifest_rejects_unbound_or_invalid_evidence(bundle, mutation):
    path = bundle[2]
    manifest = json.loads(path.read_text())
    mutation(manifest)
    write_manifest(path, manifest)
    with pytest.raises(ValueError):
        load_bundle(bundle, ["20261102"])


def test_pin_and_duplicate_json_keys_are_strict(bundle):
    with pytest.raises(ValueError):
        load_bundle(bundle, pin="0" * 64)
    path = bundle[2]
    body = path.read_text()
    path.write_text('{"scope":"security_subset",' + body[1:])
    with pytest.raises(ValueError, match="重复JSON"):
        load_bundle(bundle, ["20261102"])


@pytest.mark.parametrize("kind", ["missing", "corrupt", "same_content", "symlink_escape", "directory"])
def test_originals_must_exist_be_regular_bound_and_separate(bundle, tmp_path, kind):
    path = bundle[2]
    manifest = json.loads(path.read_text())
    original = path.parent / "universe.txt"
    if kind == "missing":
        original.unlink()
    elif kind == "corrupt":
        original.write_text("changed")
    elif kind == "same_content":
        original.write_bytes((path.parent / "control.txt").read_bytes())
        manifest["sources"][0]["sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
    elif kind == "symlink_escape":
        outside = tmp_path / "outside.txt"
        outside.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(outside)
    else:
        original.unlink()
        original.mkdir()
    write_manifest(path, manifest)
    with pytest.raises(ValueError):
        load_bundle(bundle)


def test_counts_url_must_be_a_bound_control_source(bundle):
    _, c, path = bundle
    c.write_text(c.read_text().replace("control.example.invalid", "unbound.example.invalid"))
    manifest = json.loads(path.read_text())
    manifest["counts_sha256"] = hashlib.sha256(c.read_bytes()).hexdigest()
    write_manifest(path, manifest)
    with pytest.raises(ValueError, match="counts CSV"):
        load_bundle(bundle)


@pytest.mark.parametrize("url", ["https://", "https:///path", "https://u:p@host.invalid/x", "http://host.invalid", "https://bad host.invalid"])
def test_legacy_control_urls_also_require_valid_https_host(bundle, url):
    u, c, _ = bundle
    c.write_text("trade_date,expected_count,source_url\n20261102,1," + url + "\n")
    with pytest.raises(ValueError):
        load_universe(u, ["20261102"], c)


def test_evidence_requires_both_pin_and_input_files(bundle):
    u, c, path = bundle
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    for universe, controls, manifest, sha in ((u,c,path,None),(u,c,None,pin),
            (None,c,path,pin),(u,None,path,pin)):
        with pytest.raises(ValueError):
            load_universe(universe,["20261102"],controls,evidence_manifest=manifest,evidence_sha256=sha)


def test_manifest_and_original_hashes_use_the_same_read_bytes(bundle, monkeypatch):
    import app.services.market_universe_evidence_service as service
    original = service._read_regular
    calls = []
    def read_once(path):
        calls.append(path)
        body = original(path)
        # Simulate replacement after the one read; parsing must consume body.
        path.write_text("now invalid")
        return body
    monkeypatch.setattr(service, "_read_regular", read_once)
    _, info = load_bundle(bundle)
    assert len(calls) == 1
    assert info["evidence"]["bound"] is True
