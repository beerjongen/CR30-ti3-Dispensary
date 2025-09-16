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
1) Drop inputs in `src/input/`
  - CSV (CR30 export)
  - ti1 (e.g., `228-target.ti1`)
2) Edit `src/profile_config.ini`
  - Set `[inputs].csv` and `[inputs].ti1`
  - Optionally adjust `[colprof]` 
3) Run the builder

```bash
python3 src/build_profile.py
```

Outputs land in `src/output/` by default:
- ti3: as `[outputs].ti3`
- icc: as `[outputs].icc` when `[colprof].run = true`

## Files & folders
- `src/input/` — put your input files here (CSV, ti1)
- `src/output/` — generated outputs (ti3, ICC) go here by default
- `src/profile_config.ini` — edit this to control inputs, outputs, and colprof options
- `src/build_profile.py` — reads the config, writes the ti3, runs colprof
- `src/cr30_to_ti3.py` — converter from CSV to ti3 (used by `build_profile.py`)

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

## Windows usage notes
- Don’t call the script name without `python`; use one of:
  - `src\build_profile.bat` (double-click or run in cmd) to run with config
  - `python src\build_profile.py`
  - `python src\cr30_to_ti3.py --csv src\input\your.csv --ti1 src\input\your.ti1 --out src\output\your.ti3`
- Common errors explained:
  - "is not recognized as an internal or external command": You tried to run `cr30_to_ti3` directly. Use `python cr30_to_ti3.py` or `src\cr30_to_ti3.bat`.
  - `NameError: name 'cr30_to_ti3' is not defined`: You typed `cr30_to_ti3` inside the Python REPL. Exit the REPL and run `python cr30_to_ti3.py` in the shell.
  - `FileNotFoundError: 'testprofile v2.csv'`: Provide `--csv` and `--ti1` paths, or use the defaults by running from `src/` or using the provided examples. The script now defaults to `src/input/input_example.csv` and `src/input/input_example.ti1` and writes to `src/output/cr30_example.ti3`.

Tip: If you have the Python launcher on Windows, `py -3` works too: `py -3 src\build_profile.py`.
