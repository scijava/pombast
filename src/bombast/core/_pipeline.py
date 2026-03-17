"""Main orchestrator for BOM validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bombast.config._settings import PipelineConfig
    from bombast.core._component import ValidationReport


class Pipeline:
    """Orchestrates the full BOM validation workflow."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def run(self) -> ValidationReport:
        """Execute the full validation pipeline.

        Steps:
        1. Load BOM and extract managed components
        2. Filter components by include/exclude patterns
        3. Generate version pins (Maven settings.xml)
        4. Resolve source code for each component
        5. Build and test each component
        6. Generate validation report
        """
        raise NotImplementedError("Pipeline not yet implemented")
