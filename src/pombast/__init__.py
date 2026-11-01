"""
Pombast: Validate that Bill-of-Materials components actually work together.

Pombast takes a Maven BOM (Bill of Materials) and verifies that all managed
components build and pass tests when used together at the declared versions.

Quick Start
-----------
>>> import pombast
>>> report = pombast.validate("org.scijava:pom-scijava:37.0.0")
>>> print(report.summary())

API
---
validate(bom, **kwargs) -> ValidationReport
    Validate all components in a BOM, returning a detailed report.
"""


def _get_version() -> str:
    """Get the pombast version from package metadata."""
    try:
        from importlib.metadata import version

        return version("pombast")
    except Exception:
        # Note: Fall back to reading pyproject.toml, e.g. in a bare source tree.
        try:
            import tomllib
            from pathlib import Path

            pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
            with open(pyproject, "rb") as f:
                return tomllib.load(f)["project"]["version"]
        except Exception:
            return "unknown"


__version__ = _get_version()

__all__ = ("__version__",)
