# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project adheres to Semantic Versioning.

## [v0.1.1] - 2025-09-16
### Changed
- Standalone converter `cr30_to_ti3.py` now requires explicit `--csv`, `--ti1`, and `--out` arguments (removed confusing example defaults).
- README clarified: `build_profile.py` is the MAIN entry point; added Windows/Linux run commands, and documented explicit standalone usage.
- `build_profile.py` now prints a friendly hint if `colprof` (ArgyllCMS) is not on PATH and suggests setting `[colprof].run=false` to skip ICC creation.
- Release packaging workflow made more robust; it now preserves the output folder README even if it is named `README_OUTPUTS.md`.

## [v0.1.0] - 2025-09-15
### Added
- First tagged release.
- Config-driven builder for converting CR30 CSV to .ti3 and running ArgyllCMS colprof.
- Docs for inputs/outputs and configuration.
