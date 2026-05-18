"""Build script for the agr_core package.

Installs the contents of ``packages/agr-core`` as the top-level ``agr_core``
Python package so that callers can do ``from agr_core.policy_engine import ...``
without injecting ``sys.path`` entries at runtime.
"""

from setuptools import setup

setup(
    name="agr-core",
    version="0.1.0",
    description="AGR policy engine (Cedar CLI + Python fallback)",
    python_requires=">=3.10",
    packages=["agr_core"],
    package_dir={"agr_core": "."},
    package_data={"agr_core": ["policies/*.cedar"]},
    include_package_data=True,
)
