"""Unit tests for audit hash chain verification."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services.audit_service import compute_entry_hash


def test_hash_computation_deterministic() -> None:
    h1 = compute_entry_hash(1, "TOOL_ALLOW", {"key": "val"}, None)
    h2 = compute_entry_hash(1, "TOOL_ALLOW", {"key": "val"}, None)
    assert h1 == h2


def test_hash_changes_with_sequence() -> None:
    h1 = compute_entry_hash(1, "TOOL_ALLOW", {"key": "val"}, None)
    h2 = compute_entry_hash(2, "TOOL_ALLOW", {"key": "val"}, None)
    assert h1 != h2


def test_hash_changes_with_event_type() -> None:
    h1 = compute_entry_hash(1, "TOOL_ALLOW", {"key": "val"}, None)
    h2 = compute_entry_hash(1, "TOOL_DENY", {"key": "val"}, None)
    assert h1 != h2


def test_hash_changes_with_payload() -> None:
    h1 = compute_entry_hash(1, "TOOL_ALLOW", {"key": "val1"}, None)
    h2 = compute_entry_hash(1, "TOOL_ALLOW", {"key": "val2"}, None)
    assert h1 != h2


def test_hash_changes_with_prev_hash() -> None:
    h1 = compute_entry_hash(1, "TOOL_ALLOW", {"key": "val"}, None)
    h2 = compute_entry_hash(1, "TOOL_ALLOW", {"key": "val"}, "abc123")
    assert h1 != h2


def test_hash_is_valid_sha256() -> None:
    h = compute_entry_hash(1, "TOOL_ALLOW", {"key": "val"}, None)
    assert len(h) == 64
    int(h, 16)  # should not raise


def test_hash_chain_integrity() -> None:
    """Verify a 3-entry hash chain is correct."""
    h1 = compute_entry_hash(1, "TOOL_ALLOW", {"action": "deploy"}, None)

    h2 = compute_entry_hash(2, "TOOL_DENY", {"action": "db.drop"}, h1)

    h3 = compute_entry_hash(3, "APPROVAL_REQUESTED", {"action": "deploy"}, h2)

    # Manually verify h3
    data = f"3:APPROVAL_REQUESTED:{json.dumps({'action': 'deploy'}, sort_keys=True)}:{h2}"
    expected = hashlib.sha256(data.encode("utf-8")).hexdigest()
    assert h3 == expected


def test_hash_with_none_payload() -> None:
    h = compute_entry_hash(1, "TOOL_ALLOW", None, None)
    assert len(h) == 64


def test_hash_with_empty_payload() -> None:
    h = compute_entry_hash(1, "TOOL_ALLOW", {}, None)
    assert len(h) == 64
    h2 = compute_entry_hash(1, "TOOL_ALLOW", None, None)
    assert h != h2
