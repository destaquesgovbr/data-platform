"""Conftest for script tests — adds scripts/ and scripts/migrations/ to sys.path."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
_MIGRATIONS_DIR = _SCRIPTS_DIR / "migrations"

for p in (_SCRIPTS_DIR, _MIGRATIONS_DIR):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)
