"""Pytest configuration for agr-core tests.

Adds the agr-core package root to sys.path so that `policy_engine` can be
imported directly (the package has no setup.py / pyproject.toml install step).
"""

import sys
from pathlib import Path

# packages/agr-core/  (one level up from tests/)
sys.path.insert(0, str(Path(__file__).parent.parent))
