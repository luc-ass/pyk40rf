"""Shared fixture loading for the test suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict[str, Any]:
    """Load one curated device response by file name (without .json)."""
    payload: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return payload


@pytest.fixture(name="fixture")
def fixture_loader() -> Any:
    """Expose :func:`load` as a fixture."""
    return load
