#!/usr/bin/env python3
"""Export the OpenAPI schema to openapi.json at the repo root.

Usage (from repo root):
    python scripts/export_openapi.py

Run this after any schema or route change, then commit openapi.json.
CI checks that the committed file stays fresh.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "agr-api"))

from app.main import app  # noqa: E402

schema = app.openapi()
output_path = Path(__file__).parent.parent / "openapi.json"
output_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
print(f"Written: {output_path} ({len(schema['paths'])} paths)")
