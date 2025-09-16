# CR30 ti3 Dispensary

Python script to convert CHNSpec CR30 ColorQC 2 CSVs + ArgyllCMS TI2 into a TI3, and optionally build an ICC with ArgyllCMS colprof.
Developed for the user "Pharmacist" of Printerknowledge.com and generally adaptable.

## Requirements
- Python 3.x (no external Python packages required)
- ArgyllCMS installed and `colprof` on your PATH — only needed if `[colprof].run = true`.
  - If you only need a TI3, set `[colprof].run = false` in `src/profile_config.ini`.

## How it works (policy)
- Pass-through: spectral, XYZ, and/or Lab from the CSV are written as-is (no conversions).
- Strict pairing: CSV row N maps to TI2 SAMPLE_ID N (by index). No re-ordering.
- SAMPLE_LOC: copied from TI2 when present; if absent but TI2 headers define layout (STEPS_IN_PASS, PASSES_IN_STRIPS2, INDEX_ORDER), it is generated deterministically; otherwise omitted (no grid inference fallback).
- PCS columns and COLOR_REP:
  - We include only the PCS columns present in your CSV. If XYZ is present we write XYZ; else if Lab is present we write Lab; else (spectral-only) we write just spectral.
  - COLOR_REP reflects the PCS columns, not spectral presence. Example: iRGB_XYZ if XYZ present; iRGB_LAB if only Lab present; spectral-only defaults to iRGB_XYZ for compatibility.
- Spectral precedence: if spectral is present in the TI3, colprof will use it for the profile fit with the configured illuminant/observer. PCS columns remain for auditing.
  - To make colprof ignore spectral, omit spectral columns from the CSV.

## Quick start
1) Put inputs in `src/input/`
   - CSV (CR30 export)
   - TI2 (e.g., `228-target.ti2`)
2) Edit `src/profile_config.ini`
   - Set `[inputs].csv` and `[inputs].ti2`
   - Optionally adjust `[colprof]` (quality, gamut mapping, viewing conditions, etc.)
3) Run the script

```bash
# Linux/macOS
python3 src/build_profile.py

# Windows
python src\build_profile.py
# or
python3 src\build_profile.py
# or python launcher
py -3 src\build_profile.py
```

Outputs (by default) in `src/output/`:
- TI3: `[outputs].ti3`
- ICC: `[outputs].icc` (when `[colprof].run = true`)

Tip: If you reference a source ICC for gamut mapping (e.g., AdobeRGB1998.icc via `[colprof].gamut_map_both` or `[colprof].gamut_map_perceptual`), place it in `src/input/` or use an absolute path.

## Files & folders
- `src/input/` — your inputs (CSV, TI2, source ICCs)
- `src/output/` — generated TI3 and ICC
- `src/profile_config.ini` — edit to control inputs/outputs and colprof options
- `src/build_profile.py` — single entrypoint that converts and optionally builds the ICC

## Config reference (high level)
See `src/profile_config.ini` — each option includes comments and maps to colprof flags. Paths:
- Bare filenames under `[inputs]` resolve to `src/input/`
- Bare filenames under `[outputs]` write to `src/output/`
- Paths with directories are resolved relative to the workspace root

Sections and notable options:
- `[inputs]` csv, ti2
- `[outputs]` ti3, icc, description
- `[options]` device_class
- `[colprof]`
  - Profile quality (`quality` → `-q`), B2A detail (`b2a` → `-b`)
  - Illuminant/observer (`illuminant`/`observer` → `-i`/`-o`) — used only if TI3 has spectral
  - Algorithm/dark emphasis/avg dev (`-a`, `-V`, `-r`)
  - FWA (`fwa`/`fwa_illuminant` → `-f` and FWA illuminant) — requires spectral
  - Gamut mapping (`gamut_map_perceptual` → `-s`, `gamut_map_both` → `-S`, `source_gamut_file` → `-g`, `abstract_profiles` → `-p`)
  - Intents (`perceptual_intent` → `-t`, `saturation_intent` → `-T`)
  - Viewing conditions (`viewcond_in`/`viewcond_out` → `-c`/`-d`)
  - Diagnostics/identity (`-P`, `manufacturer`/`model`/`copyright` → `-A`/`-M`/`-C`)
  - Attributes/default intent (`attributes`/`default_intent` → `-Z`)
  - Ink/black generation (`total_ink_limit` → `-l`, `black_ink_limit` → `-L`, `black_generation` → `-k`, `k_locus` → `-K`)
  - Shaper/data toggles (`no_device_shaper` → `-ni`, `no_grid_position` → `-np`, `no_output_shaper` → `-no`, `no_embed_ti3` → `-nc`)
  - Input options (`input_auto_scale_wp` → `-u`, `input_force_absolute` → `-ua`, `input_clip_above_wp` → `-uc`), `restrict_positive` → `-R`, `whitepoint_scale` → `-U`
  - Threads (`threads` sets OMP_NUM_THREADS)
  - Extra args (`extra_args`) — for advanced flags not covered above; do not duplicate `-c`/`-d` here.

If an option is empty or false, it is omitted from the `colprof` command.

## Troubleshooting
- colprof not found: install ArgyllCMS and ensure `colprof` is on PATH, or set `[colprof].run = false` to create TI3 only.
- CSV/TI2 length mismatch: ensure the CSV rows equal the number of TI2 patches; pairing is by index with no re-ordering.
- SAMPLE_LOC missing: if TI2 provides no SAMPLE_LOC and lacks layout headers, SAMPLE_LOC will not be written — this is expected.
- Spectral not detected: CSV must include 400–700 nm at 10 nm bands to be treated as spectral.
- ICC not created: ensure `[colprof].run = true` and output path is writable.
- Source ICC for gamut mapping: place it in `src/input/` or provide an absolute path.


 
