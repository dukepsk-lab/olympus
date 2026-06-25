"""Pytest bootstrap: ensure the package root is importable as `xau`.

Putting this at the repo root means `pytest` works from anywhere with no manual
PYTHONPATH tweaking.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
