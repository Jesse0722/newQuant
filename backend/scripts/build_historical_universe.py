#!/usr/bin/env python3
"""Build a retrospective historical security subset from a pinned offline package."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.historical_universe_service import build_historical_universe


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-package", required=True, type=Path)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="new directory under an existing parent; never overwrite")
    args = parser.parse_args(argv)
    try:
        result = build_historical_universe(args.input_package, args.input_sha256, args.output_dir)
    except Exception as exc:
        print(f"Historical subset build failed ({type(exc).__name__}); check input integrity and output ownership.", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
