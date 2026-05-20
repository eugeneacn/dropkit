"""pytest config for ai-adoption-report.

Puts ``scripts/`` on ``sys.path`` so tests can ``import ai_adoption_report``.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
