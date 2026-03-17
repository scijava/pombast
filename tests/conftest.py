"""Shared test fixtures for bombast."""

from __future__ import annotations

from pathlib import Path

import pytest

from bombast.core import Component

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def sample_components() -> list[Component]:
    """A small set of components for testing."""
    return [
        Component(group="org.scijava", name="scijava-common", version="2.99.0"),
        Component(group="net.imagej", name="imagej-common", version="2.0.2"),
        Component(group="net.imagej", name="ij", version="1.54f"),
        Component(group="net.imglib2", name="imglib2", version="7.1.3"),
        Component(group="sc.fiji", name="fiji-lib", version="3.1.2"),
        Component(group="org.openjfx", name="javafx-base", version="21"),
        Component(group="com.google.guava", name="guava", version="33.0.0-jre"),
    ]
