"""Static policy template library loader."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

TEMPLATES_PATH = Path(__file__).resolve().parents[1] / "policy_templates" / "templates.json"


@lru_cache(maxsize=1)
def load_policy_templates() -> list[dict[str, object]]:
    data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("Policy template library must be a list.")
    return data


def reset_policy_template_cache() -> None:
    load_policy_templates.cache_clear()
