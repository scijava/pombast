"""
Bombast: Validate that Bill-of-Materials components actually work together.

Bombast takes a Maven BOM (Bill of Materials) and verifies that all managed
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

__version__ = "0.1.0.dev0"

__all__ = ("__version__",)
