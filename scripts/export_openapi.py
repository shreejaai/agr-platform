#!/usr/bin/env python3
"""Export the OpenAPI schema to openapi.json at the repo root.

Usage (from repo root):
    python scripts/export_openapi.py            # write
    python scripts/export_openapi.py --check    # exit 1 if drifted

Run this after any schema or route change, then commit openapi.json.
CI runs `--check` to fail the build on uncommitted drift.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "agr-api"))

from app.main import app  # noqa: E402


def _render() -> str:
    return json.dumps(app.openapi(), indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare generated spec to openapi.json; exit 1 on drift instead of writing.",
    )
    args = parser.parse_args()

    output_path = Path(__file__).parent.parent / "openapi.json"
    fresh = _render()

    if args.check:
        if not output_path.exists():
            print(
                "openapi.json missing — run `python scripts/export_openapi.py` and commit.",
                file=sys.stderr,
            )
            return 1
        current = output_path.read_text(encoding="utf-8")
        if current != fresh:
            print(
                "openapi.json is out of date with the live FastAPI schema. "
                "Run `python scripts/export_openapi.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"openapi.json up to date ({len(app.openapi()['paths'])} paths).")
        return 0

    output_path.write_text(fresh, encoding="utf-8")
    print(f"Written: {output_path} ({len(app.openapi()['paths'])} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
