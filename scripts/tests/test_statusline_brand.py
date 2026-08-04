"""MeoLoom statusline branding compatibility."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import statusline


def test_meoloom_context_limit_takes_precedence(monkeypatch):
    monkeypatch.setenv("MEOLOOM_CTX_LIMIT", "300000")
    monkeypatch.setenv("DATKIT_CTX_LIMIT", "100000")

    assert importlib.reload(statusline).CTX_LIMIT == 300000


def test_legacy_context_limit_remains_a_fallback(monkeypatch):
    monkeypatch.delenv("MEOLOOM_CTX_LIMIT", raising=False)
    monkeypatch.setenv("DATKIT_CTX_LIMIT", "100000")

    assert importlib.reload(statusline).CTX_LIMIT == 100000
