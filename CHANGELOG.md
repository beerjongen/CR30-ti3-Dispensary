# Changelog
## [v0.2.0] - 2025-09-16
### Changed
- TI2-only workflow: use a TI2 target file with the CR30 CSV. TI2 defines device space (iRGB/iCMYK/…), patch order, and SAMPLE_IDs. CSV row N pairs strictly with TI2 SAMPLE_ID N.
- SAMPLE_LOC policy: copy from TI2; if missing, generate only when TI2 headers define layout (STEPS_IN_PASS, PASSES_IN_STRIPS2, INDEX_ORDER); otherwise omit (no grid inference fallback).
- PCS/COLOR_REP: write only the PCS columns present in the CSV; COLOR_REP mirrors those PCS columns (XYZ preferred, else Lab). Spectral is used by colprof when present; spectral-only keeps spectral and defaults COLOR_REP to XYZ for compatibility.
- Config defaults: viewing conditions moved to explicit options with sane defaults (`viewcond_in = mt`, `viewcond_out = pp`).

### Removed/Deprecated
- TI1 inputs for the main workflow — not required or consumed. Use TI2.
- CR30-to-TI3 standalone converter and batch wrappers as entrypoints; use `src/build_profile.py` with `src/profile_config.ini`.

## [v0.1.1] - 2025-09-16
### Changed
- Standalone converter `cr30_to_ti3.py` now requires explicit `--csv`, `--ti1`, and `--out` arguments (removed confusing example defaults).
- README clarified: `build_profile.py` is the MAIN entry point; added Windows/Linux run commands, and documented explicit standalone usage.
- `build_profile.py` now prints a friendly hint if `colprof` (ArgyllCMS) is not on PATH and suggests setting `[colprof].run=false` to skip ICC creation.
- Release packaging workflow made more robust; it now preserves the output folder README even if it is named `README_OUTPUTS.md`.
 - Documentation sweep:
	 - Clarified PCS column inclusion rules and COLOR_REP selection (XYZ preferred when present, otherwise Lab; spectral presence doesn’t override COLOR_REP).
	 - Clarified that spectral measurements, when present, are used by colprof for the fit; XYZ/Lab columns are retained for auditing only.
	 - Tightened SAMPLE_LOC policy: copy from TI2 or generate deterministically from TI2 headers; no grid inference fallback.
	 - Added note on placing source ICCs (e.g., AdobeRGB1998.icc) in `src/input/` for gamut mapping flags.

## [v0.1.0] - 2025-09-15
### Added
- First tagged release.
- Config-driven builder for converting CR30 CSV to .ti3 and running ArgyllCMS colprof.
- Docs for inputs/outputs and configuration.
