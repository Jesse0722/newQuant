"""Pure offline retrospective SSE main-board subset derivation.

Dated membership is authoritative for inclusion in this *provider-observed*
subset. Current basic data supplies classification/lifecycle checks, never adds
members or supplies a historical trading state. No database/provider imports.
"""
from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat

from app.services.market_universe_evidence_service import (
    _json_object, _package_bytes, _read_regular, _sha, _text,
    validate_https_url, validated_dates,
)

VERSION = "historical-universe-build-v1"
MEMBERSHIP_FIELDS = {"code", "tradeStatus", "code_name"}
BASIC_FIELDS = {"code", "code_name", "ipoDate", "outDate", "type", "status"}
RAW_CODE = re.compile(r"(?:sh|sz|bj)\.[0-9]{6}")
MAIN_BOARD = re.compile(r"sh\.(?:600|601|603|605)[0-9]{3}")


def _json(body):
    def invalid_constant(_value):
        raise ValueError("JSON contains nonfinite number")
    value = json.loads(body.decode("utf-8-sig"), object_pairs_hook=_json_object,
                       parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("JSON must contain an object")
    return value


def _iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("source date must be YYYY-MM-DD")
    datetime.strptime(value, "%Y-%m-%d")
    return value


def _source(base, pointer):
    if not isinstance(pointer, dict):
        raise ValueError("source pointer must be an object")
    body, _ = _package_bytes(base, pointer.get("path"))
    digest = hashlib.sha256(body).hexdigest()
    if digest != _sha(pointer.get("sha256")):
        raise ValueError("source SHA256 mismatch")
    return body, {"path": pointer["path"], "sha256": digest}


def _raw_records(body, *, query, day=None):
    source = _json(body)
    if (source.get("provider") != "baostock" or source.get("sdk_version") != "0.9.1"
            or source.get("query") != query or source.get("error_code") != "0"):
        raise ValueError("unsupported or unsuccessful raw source")
    expected_request = {"code": "", "code_name": ""} if day is None else {"day": day}
    if source.get("request") != expected_request or source.get("response_day") != (day or ""):
        raise ValueError("source request/date echo mismatch")
    observed = datetime.fromisoformat(_text(source.get("observed_at"), "observed_at").replace("Z", "+00:00"))
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("observed_at must include timezone")
    fields = source.get("fields")
    required = BASIC_FIELDS if day is None else MEMBERSHIP_FIELDS
    if (not isinstance(fields, list) or any(not isinstance(f, str) for f in fields)
            or len(fields) != len(set(fields)) or set(fields) != required):
        raise ValueError("raw fields must be unique and match the source schema")
    rows = source.get("rows")
    if (not isinstance(rows, list) or not rows or type(source.get("row_count")) is not int
            or source["row_count"] != len(rows)):
        raise ValueError("raw actual row count missing or inconsistent")
    records = {}
    for number, row in enumerate(rows, 1):
        if not isinstance(row, list) or len(row) != len(fields) or any(not isinstance(cell, str) for cell in row):
            raise ValueError("raw row width or exact-string cells invalid")
        record = dict(zip(fields, row))
        code = record["code"]
        if RAW_CODE.fullmatch(code) is None or code in records or not record["code_name"].strip():
            raise ValueError("raw code/name invalid or duplicated")
        if day is not None:
            if record["tradeStatus"] not in ("0", "1"):
                raise ValueError("unknown historical tradeStatus")
        else:
            if record["type"] not in ("1", "2", "3", "4", "5") or record["status"] not in ("0", "1"):
                raise ValueError("unknown basic type/status")
            for field in ("ipoDate", "outDate"):
                if record[field]:
                    _iso_date(record[field])
            if record["ipoDate"] and record["outDate"] and record["ipoDate"] >= record["outDate"]:
                raise ValueError("basic lifecycle dates conflict")
        records[code] = {"row_number": number, "row_locator": f"rows[{number - 1}]", "raw_values": record}
    return source, records


def _excluded_reason(code, basic):
    if not code.startswith("sh."):
        return "other_market_" + code[:2]
    if code.startswith(("sh.688", "sh.689")):
        return "sh_science_technology_board"
    if code.startswith("sh.900"):
        return "sh_b_share"
    if basic and basic["raw_values"]["type"] in ("2", "3", "4", "5"):
        return "sh_non_stock_type_" + basic["raw_values"]["type"]
    raise ValueError("unknown Shanghai security/board classification")


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _prepare(input_package, input_sha256):
    package_path = Path(input_package).resolve(strict=True)
    body = _read_regular(package_path)
    package_sha = hashlib.sha256(body).hexdigest()
    if package_sha != _sha(input_sha256):
        raise ValueError("input package SHA256 mismatch")
    package = _json(body)
    if (package.get("version") != "historical-universe-input-v1"
            or package.get("selection") != "sse_main_board_a" or package.get("scope") != "security_subset"
            or package.get("temporal_basis") != "retrospective"):
        raise ValueError("unsupported historical selection/scope/version")
    dates = validated_dates(package.get("dates"))
    membership_pointers = package.get("membership_sources")
    if not isinstance(membership_pointers, list) or len(membership_pointers) != len(dates):
        raise ValueError("exactly one membership source per requested date required")
    pointers = {}
    for pointer in membership_pointers:
        if not isinstance(pointer, dict) or pointer.get("trade_date") not in dates or pointer["trade_date"] in pointers:
            raise ValueError("membership source date duplicated or out of scope")
        pointers[pointer["trade_date"]] = pointer
    docs = package.get("documentation_sources")
    if not isinstance(docs, list) or not docs:
        raise ValueError("provider documentation required")
    documentation, identifiers = [], set()
    for doc in docs:
        if not isinstance(doc, dict):
            raise ValueError("documentation pointer invalid")
        identifier = _text(doc.get("id"), "documentation id")
        if identifier in identifiers:
            raise ValueError("documentation id duplicated")
        identifiers.add(identifier)
        documentation_body, provenance = _source(package_path.parent, doc)
        if not documentation_body.strip():
            raise ValueError("provider documentation is empty")
        documentation.append({**provenance, "id": identifier, "url": validate_https_url(doc.get("url")),
                              "locator": _text(doc.get("locator"), "documentation locator")})
    basic_body, basic_provenance = _source(package_path.parent, package.get("basic_source"))
    basic_source, basics = _raw_records(basic_body, query="query_stock_basic")
    basic_provenance.update(query="query_stock_basic", observed_at=basic_source["observed_at"], actual_row_count=len(basics))
    csv_stream = io.StringIO(newline="")
    writer = csv.writer(csv_stream, lineterminator="\n")
    writer.writerow(["trade_date", "ts_code", "security_type", "is_listed", "is_trading", "name"])
    lineage, days, membership_provenance = [], [], []
    for date in dates:
        iso_day = date[:4] + "-" + date[4:6] + "-" + date[6:]
        raw_body, provenance = _source(package_path.parent, pointers[date])
        raw_source, records = _raw_records(raw_body, query="query_all_stock", day=iso_day)
        provenance.update(trade_date=date, query="query_all_stock", observed_at=raw_source["observed_at"], actual_row_count=len(records))
        membership_provenance.append(provenance)
        exclusions, trading, suspended = Counter(), 0, 0
        for code in sorted(records):
            member = records[code]
            basic = basics.get(code)
            if not MAIN_BOARD.fullmatch(code):
                exclusions[_excluded_reason(code, basic)] += 1
                continue
            if basic is None:
                raise ValueError("selected historical member lacks basic classification")
            values = basic["raw_values"]
            if (values["type"] != "1" or not values["ipoDate"] or values["ipoDate"] > iso_day
                    or (values["outDate"] and values["outDate"] <= iso_day)
                    or (values["status"] == "0" and not values["outDate"])):
                raise ValueError("selected member classification/lifecycle conflicts with dated membership")
            state = member["raw_values"]["tradeStatus"]
            ts_code = code[3:] + ".SH"
            name = member["raw_values"]["code_name"]
            writer.writerow([date, ts_code, "a_share", "1", state, name])
            trading += state == "1"
            suspended += state == "0"
            lineage.append({"trade_date": date, "ts_code": ts_code, "universe_csv_line": len(lineage) + 2,
                "membership": {**provenance, **member}, "basic": {**basic_provenance, **basic}})
        if trading + suspended == 0:
            raise ValueError("no observed SSE main-board members for requested date")
        days.append({"trade_date": date, "raw_observed_rows": len(records), "observed_listed": trading + suspended,
            "observed_trading": trading, "observed_suspended": suspended, "excluded_rows": sum(exclusions.values()),
            "exclusions": dict(sorted(exclusions.items()))})
    report = {"version": VERSION, "scope": "security_subset", "selection": "sse_main_board_a",
        "temporal_basis": "retrospective", "dates": dates, "days": days,
        "input_package": {"file": str(package_path), "sha256": package_sha},
        "membership_sources": membership_provenance, "basic_source": basic_provenance,
        "documentation_sources": documentation, "total_output_rows": len(lineage),
        "independent_control_totals": False, "full_market_qualification": False,
        "limitations": ["Provider-observed SSE main-board subset only; counts are not independent control totals.",
            "Historical membership/trading state comes only from dated query_all_stock raw rows; current basic status never filters historical members.",
            "Retrospective classification/lifecycle evidence does not prove data was available at historical decision time.",
            "Hashes bind source bytes and lineage, not provider authority or completeness; no full-market qualification is generated."]}
    artifacts = {"universe.csv": csv_stream.getvalue().encode("utf-8"),
        "row-lineage.jsonl": b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8") for row in lineage),
        "build-report.json": _json_bytes(report)}
    index = {"version": VERSION, "status": "complete", "scope": "security_subset", "selection": "sse_main_board_a",
        "temporal_basis": "retrospective", "dates": dates, "input_package_sha256": package_sha,
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in artifacts.items()},
        "publication_limit": "Requires normal CLI completion and all indexed files; not a SIGKILL/power-loss transaction."}
    artifacts["complete-index.json"] = _json_bytes(index)
    return artifacts, report


def _identity(metadata):
    return metadata.st_dev, metadata.st_ino


def _owned_file(directory_fd, name, identity):
    try:
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return stat.S_ISREG(current.st_mode) and _identity(current) == identity


def _publish(output_dir, artifacts):
    """Exclusive new directory, with ownership-checked cleanup of own files only."""
    output = Path(output_dir)
    output.mkdir(mode=0o700)  # Parent must exist; never adopt an existing output directory.
    directory_identity = _identity(output.lstat())
    directory_fd, reserved = None, []
    try:
        directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if _identity(os.fstat(directory_fd)) != directory_identity:
            raise OSError("output directory replaced")
        os.fchmod(directory_fd, 0o700)
        for name, body in artifacts.items():
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            try:
                identity = _identity(os.fstat(fd))
            except BaseException:
                os.close(fd)
                raise
            reserved.append((name, fd, identity))
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                if stream.write(body) != len(body):
                    raise OSError("short artifact write")
                stream.flush()
                os.fsync(fd)
        if (_identity(output.lstat()) != directory_identity
                or not all(_owned_file(directory_fd, name, identity) for name, _, identity in reserved)):
            raise OSError("published artifact path replaced")
    except BaseException:
        if directory_fd is not None:
            for name, _, identity in reserved:
                try:
                    if _owned_file(directory_fd, name, identity):
                        os.unlink(name, dir_fd=directory_fd)
                except OSError:
                    pass  # Uncertain/replaced paths must remain untouched.
        try:
            if _identity(output.lstat()) == directory_identity:
                output.rmdir()  # Fails safely if a competing file remains.
        except OSError:
            pass
        raise
    finally:
        for _, fd, _ in reserved:
            os.close(fd)
        if directory_fd is not None:
            os.close(directory_fd)


def build_historical_universe(input_package, input_sha256, output_dir):
    """Validate and serialize completely before exclusively publishing artifacts."""
    try:
        artifacts, report = _prepare(input_package, input_sha256)
        _publish(output_dir, artifacts)
    except (OSError, UnicodeError, KeyError, TypeError) as exc:
        raise ValueError("historical universe input or output validation failed") from exc
    return {"scope": "security_subset", "dates": report["dates"], "total_output_rows": report["total_output_rows"],
        "output_dir": str(Path(output_dir).resolve()),
        "complete_index_sha256": hashlib.sha256(artifacts["complete-index.json"]).hexdigest(),
        "universe_sha256": hashlib.sha256(artifacts["universe.csv"]).hexdigest()}
