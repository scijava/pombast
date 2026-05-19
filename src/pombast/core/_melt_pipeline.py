"""Orchestrator for mega-melt BOM validation (melt)."""

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

from pombast.core._component import MeltResult
from pombast.core._filter import ComponentFilter
from pombast.maven._bom import load_bom
from pombast.maven._builder import locate_java
from pombast.maven._mega_melt import prepare_mega_melt, run_mega_melt_validation

if TYPE_CHECKING:
    from pombast.config._settings import MeltConfig

_log = logging.getLogger(__name__)


class MeltPipeline:
    """Validates the holistic BOM classpath via a mega-melt POM."""

    def __init__(self, config: MeltConfig) -> None:
        self.config = config

    def run(self) -> MeltResult:
        """Execute mega-melt validation.

        Steps:
        1. Load BOM and extract managed components
        2. Filter components by include/exclude patterns
        3. Generate mega-melt POM and run validation
        """
        output_dir = self.config.output_dir
        if output_dir.exists() and self.config.force:
            _log.info("Wiping output directory: %s", output_dir)
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        repositories = self._build_repo_map()
        _log.info("Loading BOM: %s", self.config.bom)
        bom_data = load_bom(self.config.bom, repositories=repositories)
        _log.info("Found %d components in BOM", len(bom_data.components))

        components = self._build_filter().filter(bom_data.components)
        _log.info("Mega-melt: %d components after filtering", len(components))

        effective_java = (
            self.config.config.mega_melt.java_version or self.config.default_java
        )
        java_home = locate_java(effective_java) if effective_java else None

        template_path = self.config.config.mega_melt.template

        mega_melt_dir = output_dir / "mega-melt"
        try:
            prepare_mega_melt(
                bom_data.pom_path,
                mega_melt_dir,
                components,
                repositories,
                template_path=template_path,
            )
            success, tree_log, build_log = run_mega_melt_validation(
                mega_melt_dir, java_home=java_home
            )
        except Exception as e:
            _log.error("Mega-melt failed: %s", e)
            return MeltResult(bom=self.config.bom, success=False)

        return MeltResult(
            bom=self.config.bom,
            success=success,
            tree_log=tree_log,
            build_log=build_log,
        )

    def _build_filter(self) -> ComponentFilter:
        includes = (
            list(self.config.includes) or self.config.config.mega_melt.filter.includes
        )
        excludes = (
            list(self.config.excludes) + self.config.config.mega_melt.filter.excludes
        )
        return ComponentFilter(includes=includes, excludes=excludes)

    def _build_repo_map(self) -> dict[str, str]:
        return {"central": "https://repo1.maven.org/maven2", **self.config.repositories}
