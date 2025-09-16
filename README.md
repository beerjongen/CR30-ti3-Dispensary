# CR30 ti3 Dispensary

This is a config-driven script that parses CHNSpec CR30 ColorQC 2 CSVs into ArgyllCMS compatible `.ti3` and optionally runs `colprof`.
Developed for the user "Pharmacist" of Printerknowledge.com with a specific use case, but may be adaptable.

## Requirements
- Python 3.x (tested with Python 3; no external Python packages required)
- ArgyllCMS installed and `colprof` available on your PATH (only needed if `[colprof].run = true`)
  - If for some reason don't have ArgyllCMS but still need a ti3, set `[colprof].run = false` in `src/profile_config.ini` to generate `.ti3` only.

## Key behaviors
- Spectral-only ti3 by default when spectral data is present
- Strict one-to-one by index: CSV measurement should match the set order defined with targen (default targen is ordered random)
  
## Quick start
Prefer using the builder; it orchestrates everything (CSV→TI3 and ICC creation) and resolves paths from `profile_config.ini`.

1) Drop inputs in `src/input/`
  - CSV (CR30 export)
  - ti1 (e.g., `228-target.ti1`)
2) Edit `src/profile_config.ini`
  - Set `[inputs].csv` and `[inputs].ti1`
  - Optionally adjust `[colprof]` 
3) Run the builder

```bash
# Linux/macOS
python3 src/build_profile.py

# Windows (choose the one that works on your system)
python3 src\build_profile.py
python src\build_profile.py
py -3 src\build_profile.py
```

Outputs land in `src/output/` by default:
- ti3: as `[outputs].ti3`
- icc: as `[outputs].icc` when `[colprof].run = true`

## Files & folders
- `src/input/` — put your input files here (CSV, ti1)
- `src/output/` — generated outputs (ti3, ICC) go here by default
- `src/profile_config.ini` — edit this to control inputs, outputs, and colprof options
- `src/build_profile.py` — MAIN entry point: reads the config, calls the converter, runs `colprof`
- `src/cr30_to_ti3.py` — standalone converter from CSV to TI3 (also invoked by `build_profile.py`)

## Config reference
See `src/profile_config.ini` — each option includes a brief description and maps to `colprof` flags. Paths:
- Bare filenames under `[inputs]` are resolved in `src/input/`
- Bare filenames under `[outputs]` are written into `src/output/`
- Paths with directories are resolved relative to the workspace root

- `[inputs]` csv/ti1
- `[outputs]` ti3/icc/description
- `[options]` prefer_spectral, prefer_lab
- `[colprof]` selections including:
  - quality (`-q`), b2a (`-b`)
  - illuminant (`-i`), observer (`-o`)
  - algorithm (`-a`), demphasis (`-V`), avgdev (`-r`)
  - FWA (`-f`), gamut mapping (`-s`, `-S`, `-g`, `-p`)
  - intents (`-t`, `-T`), viewing conditions (`-c`, `-d`)
  - VRML gamut (`-P`), identity strings (`-A`, `-M`, `-C`)
  - attributes/default intent (`-Z`), ink limits (`-l`, `-L`), black gen (`-k`, `-K`)
  - shaper/data toggles (`-ni`, `-np`, `-no`, `-nc`), input options (`-u`, `-ua`, `-uc`), `-R`, `-U`
  - threads env for OpenMP

If an option is left empty or false, it is omitted from the command without notice.

### Standalone converter (optional)
If you only need a `.ti3` and want to run the converter directly, you must provide explicit paths (there are no implicit defaults):

```bash
# Linux/macOS
python3 src/cr30_to_ti3.py --csv "src/input/your.csv" --ti1 "src/input/your.ti1" --out "src/output/your.ti3"

# Windows
python3 src\cr30_to_ti3.py --csv "src\input\your.csv" --ti1 "src\input\your.ti1" --out "src\output\your.ti3"
```
