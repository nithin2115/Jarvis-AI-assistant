"""Pytest collection guard.

Several files in this directory are standalone diagnostic SCRIPTS: they execute
their checks at import time and call ``sys.exit()`` at the end (run via
``python -m tests.<name>``). Pytest imports every ``test_*.py`` during
collection, so those scripts crash the entire run with a ``SystemExit``.

To keep ``pytest tests/`` working while leaving the scripts runnable as-is, we
auto-ignore any ``test_*.py`` that does not define at least one ``def test_``
function. This is self-maintaining — new pytest modules are collected
automatically, and new diagnostic scripts are skipped automatically.
"""
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_HAS_PYTEST_FUNC = re.compile(r"(?m)^\s*def\s+test_")

collect_ignore = []
for _name in sorted(os.listdir(_HERE)):
    if not (_name.startswith("test_") and _name.endswith(".py")):
        continue
    try:
        with open(os.path.join(_HERE, _name), "r", encoding="utf-8") as _f:
            _src = _f.read()
    except OSError:
        continue
    if not _HAS_PYTEST_FUNC.search(_src):
        collect_ignore.append(_name)
