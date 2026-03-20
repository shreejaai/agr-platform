"""Cython compilation setup for AGR on-prem distribution builds.

Compiles all Python source files in app/ to native .so binaries,
making the business logic significantly harder to reverse-engineer.

Excluded from compilation (must remain as .py):
  - __init__.py  — package markers, must be importable as-is
  - main.py      — FastAPI app entry point, uvicorn loads it by name
  - config.py    — pydantic-settings reads source at import time
  - workers/     — Temporal worker entry points
  - workflows/   — Temporal workflow definitions (pickle/introspection-sensitive)
  - tests/       — not shipped in distribution image

Usage (called automatically by Dockerfile.onprem):
  pip install cython setuptools
  python setup_cython.py build_ext --inplace
"""

import glob
import os

from Cython.Build import cythonize
from setuptools import Extension, setup

# Directories and filenames to skip compilation for
EXCLUDE_DIRS = {"tests", "workers", "workflows", "__pycache__"}
EXCLUDE_FILES = {"__init__.py", "main.py", "config.py", "setup_cython.py"}

modules = []
for path in glob.glob("app/**/*.py", recursive=True):
    parts = path.replace("\\", "/").split("/")
    # Skip excluded directories
    if any(d in EXCLUDE_DIRS for d in parts):
        continue
    # Skip excluded filenames
    if os.path.basename(path) in EXCLUDE_FILES:
        continue
    modules.append(path)

extensions = [
    Extension(
        # Convert path to dotted module name: app/routes/foo.py → app.routes.foo
        path.replace("\\", "/").replace("/", ".")[:-3],
        [path],
    )
    for path in modules
]

setup(
    name="agr-api-onprem",
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "always_allow_keywords": True,
        },
        nthreads=4,
    ),
)
