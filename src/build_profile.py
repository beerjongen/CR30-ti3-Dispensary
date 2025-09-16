#!/usr/bin/env python3
"""
CR30 → TI3 builder (single entry point)

Purpose
-------
This script converts CHNSpec CR30 ColorQC 2 CSV measurements into an ArgyllCMS-compatible
CGATS .ti3 file using a target layout (.ti2) as the authoritative source for device values
and layout, and then (optionally) runs `colprof` to create an ICC profile. It is the single
entry point for the project; all converter logic lives here.

Workflow overview
-----------------
1) Read configuration from `src/profile_config.ini`.
2) Resolve input/output paths:
     - Bare filenames are resolved under `src/input` (inputs) and `src/output` (outputs).
     - Relative paths with directories are resolved relative to the workspace root.
3) Convert CSV + TI2 → TI3:
     - TI2 is authoritative for device space/values and patch order.
     - Pairing is strictly by index: CSV row N ↔ TI2 SAMPLE_ID N.
     - SAMPLE_LOC is copied from TI2 when present. If absent, it is deterministically
         generated from TI2 header (STEPS_IN_PASS, PASSES_IN_STRIPS2, INDEX_ORDER). If not
         resolvable from TI2 data, SAMPLE_LOC is omitted.
     - Available data are passed through without conversion or suppression: XYZ, Lab, spectral.
     - Select TI2 header keys are promoted into the TI3 header for familiarity; additional
         TI2 header lines are preserved in comments for provenance.
4) Optionally run `colprof` based on the `[colprof]` section of the config, mapping
     options to ArgyllCMS flags and skipping spectral-only flags if no spectral data exists.

Key behaviors
-------------
- Pass-through: If CSV contains spectral, XYZ, or Lab, they are written as provided (no conversions).
- Deterministic SAMPLE_LOC from TI2 header data when missing, else omitted if not resolvable.

Configuration
-------------
See `src/profile_config.ini` for all options. Highlights:
- [inputs] csv, ti2
- [outputs] ti3, icc, description
- [options] device_class
- [colprof] run, quality, b2a, illuminant, observer, and many advanced options.

CLI
---
Run this script directly:
        python3 src/build_profile.py

Inputs/outputs come from the config. Use bare filenames or relative paths as described above.

Data contracts (internal)
-------------------------
- parse_cr30_csv(path) -> dict:
    { rows: [ { L,a,b,X,Y,Z, spectral{nm->val}, ... }, ... ], illum_code: str|None, observer_deg: int|None }
    - rows length determines how many measurement rows are paired.
    - spectral reflectance values are expected in 0–100 units.

- parse_ti2(path) -> dict:
    { device_fields: [str], device_values: [(sid, [floats])], sample_locs: [(sid, loc)]|[],
        color_rep_device: str|None, header_lines: [str] }
    - SAMPLE_IDs are expected to be 1..N and used strictly in order.
    - If SAMPLE_LOC is not present, deterministic generation uses TI2 header.

- write_ti3(out_path, device_fields, device_values, cr30, sample_locs, device_class,
                        prefer_spectral, prefer_xyz_over_lab, ti2_header_lines) -> None
    - Builds fields: SAMPLE_ID, optional SAMPLE_LOC, device fields, XYZ, Lab, SPEC_XXX.
    - COLOR_REP derives from device fields and chosen PCS (XYZ or Lab).
    - Promotes selected TI2 header keys into TI3 header and preserves others as provenance.

Edge cases & errors
-------------------
- Missing CSV/TI2: preflight checks fail fast with clear messages.
- Mismatched lengths: TI3 writes exactly min(len(device_values), len(csv_rows)).
- Spectral: if rows disagree on wavelengths, only the common set is written.
- Index order: Assumes CSV row order matches TI2 SAMPLE_ID order; we do not try to reindex.

License & attribution
---------------------
See LICENSE. Based on community needs; originally created to support a Pharmacist workflow.
"""
import configparser
import os
import re
import shlex
import subprocess
import sys
import shutil
from datetime import datetime
from typing import Optional, List, Dict, Tuple

HERE = os.path.dirname(__file__)
CFG_PATH = os.path.join(HERE, 'profile_config.ini')
WS_ROOT = os.path.abspath(os.path.join(HERE, '..'))
IN_DIR = os.path.join(HERE, 'input')
OUT_DIR = os.path.join(HERE, 'output')

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

# --------------------- Converter helpers & functions ---------------------

def _to_float(val: str):
    if val is None:
        return None
    s = val.strip().replace(',', '.')
    if s == '' or s.lower() in ('nan', 'null'):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def _read_text_with_fallback(path: str) -> str:
    for enc in ('utf-8', 'utf-8-sig', 'cp1252', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, 'rb') as f:
        return f.read().decode('latin-1', errors='replace')

def parse_cr30_csv(path: str) -> Dict:
    """Parse a CHNSpec CR30 CSV export.

    Returns a dict with:
        - rows: list of per-patch dicts containing optional L,a,b,X,Y,Z and a spectral map
        - illum_code: e.g., 'D50' or 'D65' if derivable from the Light Source/Angle column
        - observer_deg: 2 or 10 if derivable

    Notes:
        - CSV is expected semicolon-separated; decimal comma is handled.
        - Non-measurement rows lacking both Lab and XYZ are skipped.
        - Spectral wavelengths are discovered by trailing 3-digit patterns (e.g., 400, 730nm).
    """
    text = _read_text_with_fallback(path)
    lines = [ln.rstrip('\r') for ln in text.split('\n')]
    if not lines:
        raise ValueError('Empty CSV file')
    header = [h.strip() for h in lines[0].split(';')]
    norm = lambda s: re.sub(r'[^a-z0-9_]+', '', s.strip().lower())
    hmap: Dict[str, int] = {norm(h): i for i, h in enumerate(header)}

    idx_name = hmap.get('name')
    idx_date = hmap.get('date')
    idx_mode = hmap.get('testmode')
    idx_lsag = hmap.get('lightsourceangle')
    idx_L = hmap.get('l') or hmap.get('l*') or hmap.get('lstar')
    idx_a = hmap.get('a') or hmap.get('a*') or hmap.get('astar')
    idx_b = hmap.get('b') or hmap.get('b*') or hmap.get('bstar')
    idx_X = hmap.get('x')
    idx_Y = hmap.get('y')
    idx_Z = hmap.get('z')

    spec_cols: List[Tuple[int, int]] = []
    for key, i in hmap.items():
        m = re.search(r'(\d{3})(?:nm)?$', key)
        if m:
            wl = int(m.group(1))
            if 300 <= wl <= 1100:
                spec_cols.append((i, wl))
    spec_cols.sort(key=lambda t: t[1])

    rows = []
    illum_code = None
    observer = None
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(';')
        name = parts[idx_name] if idx_name is not None and idx_name < len(parts) else ''
        L = _to_float(parts[idx_L]) if idx_L is not None and idx_L < len(parts) else None
        a = _to_float(parts[idx_a]) if idx_a is not None and idx_a < len(parts) else None
        b = _to_float(parts[idx_b]) if idx_b is not None and idx_b < len(parts) else None
        X = _to_float(parts[idx_X]) if idx_X is not None and idx_X < len(parts) else None
        Y = _to_float(parts[idx_Y]) if idx_Y is not None and idx_Y < len(parts) else None
        Z = _to_float(parts[idx_Z]) if idx_Z is not None and idx_Z < len(parts) else None
        if L is None and X is None:
            continue
        lsag = parts[idx_lsag] if idx_lsag is not None and idx_lsag < len(parts) else ''
        test_mode = parts[idx_mode] if idx_mode is not None and idx_mode < len(parts) else ''
        date = parts[idx_date] if idx_date is not None and idx_date < len(parts) else ''
        spectral: Dict[int, float] = {}
        if spec_cols:
            for ci, wl in spec_cols:
                if ci < len(parts):
                    v = _to_float(parts[ci])
                    if v is not None:
                        spectral[wl] = v
        if illum_code is None and lsag:
            m = re.match(r'([A-Za-z0-9]+)\s*/\s*(\d+)\s*°?', lsag)
            if m:
                illum_code = m.group(1).upper()
                try:
                    observer = int(m.group(2))
                except ValueError:
                    observer = None
        rows.append({
            'name': name,
            'date': date,
            'test_mode': test_mode,
            'light_source_angle': lsag,
            'L': L, 'a': a, 'b': b,
            'X': X, 'Y': Y, 'Z': Z,
            'spectral': spectral
        })
    return {
        'rows': rows,
        'illum_code': illum_code,
        'observer_deg': observer
    }

def parse_ti2(path: str) -> Dict:
    """Parse an Argyll/CGATS TI2 file.

    Returns a dict with:
        - device_fields: list of device channel field names (e.g., RGB_R, CMYK_C, ...)
        - device_values: list of (SAMPLE_ID, [values]) sorted by SAMPLE_ID
        - sample_locs: list of (SAMPLE_ID, 'A1'..) if present or generated; else empty
        - color_rep_device: COLOR_REP value from TI2 if present
        - header_lines: lines before BEGIN_DATA_FORMAT for provenance

    Behavior:
        - If SAMPLE_LOC is not present in TI2 data, we try to generate deterministically using
            STEPS_IN_PASS, PASSES_IN_STRIPS2, INDEX_ORDER.
    """
    device_fields: List[str] = []
    device_values: List[Tuple[int, List[float]]] = []
    sample_locs: List[Tuple[int, str]] = []
    color_rep_device = None
    with open(path, 'r', encoding='utf-8') as f:
        lines = [ln.rstrip('\n') for ln in f]
    for ln in lines[:80]:
        m = re.match(r'^COLOR_REP\s+"([^"]+)"', ln)
        if m:
            color_rep_device = m.group(1)
            break
    fmt_start = None
    fmt_end = None
    for i, ln in enumerate(lines):
        if ln.strip() == 'BEGIN_DATA_FORMAT':
            fmt_start = i + 1
        elif ln.strip() == 'END_DATA_FORMAT':
            fmt_end = i
            break
    if fmt_start is None or fmt_end is None:
        raise ValueError('ti2 missing data format block')
    header_lines: List[str] = []
    header_end_idx = None
    for i in range(fmt_start - 1, -1, -1):
        if lines[i].strip().startswith('NUMBER_OF_FIELDS'):
            header_end_idx = i
            break
    if header_end_idx is None:
        header_end_idx = fmt_start - 1
    for ln in lines[:header_end_idx]:
        s = ln.strip()
        if not s:
            continue
        if s.startswith('CTI'):
            continue
        header_lines.append(ln)
    header_map: Dict[str, str] = {}
    for hl in header_lines:
        m = re.match(r'^([A-Z0-9_]+)\s+"?([^"]+)"?\s*$', hl.strip())
        if m:
            header_map[m.group(1)] = m.group(2)
    fmt_tokens: List[str] = []
    for ln in lines[fmt_start:fmt_end]:
        fmt_tokens.extend(ln.split())
    fields = fmt_tokens
    allowed_prefixes = ("RGB_", "CMYK_", "GRAY_", "K_")
    device_fields = [f for f in fields if any(f.startswith(p) for p in allowed_prefixes)]
    if not device_fields:
        for f in ("RGB_R","RGB_G","RGB_B","CMYK_C","CMYK_M","CMYK_Y","CMYK_K"):
            if f in fields:
                device_fields.append(f)
    loc_index: Optional[int] = None
    if 'SAMPLE_LOC' in fields:
        loc_index = fields.index('SAMPLE_LOC')
    in_data = False
    for ln in lines:
        s = ln.strip()
        if s == 'BEGIN_DATA':
            in_data = True
            continue
        if s == 'END_DATA':
            break
        if in_data and s:
            parts = s.split()
            try:
                sid = int(parts[0])
            except ValueError:
                continue
            if loc_index is not None and loc_index < len(fields):
                pidx = loc_index
                if pidx < len(parts):
                    raw = parts[pidx]
                    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
                        loc = raw[1:-1]
                    else:
                        loc = raw
                    sample_locs.append((sid, loc))
            vals: List[float] = []
            for f in device_fields:
                try:
                    idx = fields.index(f)
                except ValueError:
                    vals.append(0.0)
                    continue
                pidx = idx
                if pidx < len(parts):
                    v = _to_float(parts[pidx])
                    vals.append(v if v is not None else 0.0)
                else:
                    vals.append(0.0)
            device_values.append((sid, vals))
    device_values.sort(key=lambda t: t[0])
    if sample_locs:
        sample_locs.sort(key=lambda t: t[0])
    else:
        try:
            sp = header_map.get('STEPS_IN_PASS')
            ps2 = header_map.get('PASSES_IN_STRIPS2')
            cols = int(float(sp.strip())) if isinstance(sp, str) and sp.strip() else None
            rows = int(float(ps2.strip())) if isinstance(ps2, str) and ps2.strip() else None
        except Exception:
            cols = rows = None
        index_order = header_map.get('INDEX_ORDER', '').strip().upper()
        if cols and rows and cols > 0 and rows > 0 and len(device_values) == cols * rows:
            def row_label(idx0: int) -> str:
                s = ''
                i = idx0
                while True:
                    s = chr(ord('A') + (i % 26)) + s
                    i = i // 26 - 1
                    if i < 0:
                        break
                return s
            N = len(device_values)
            if index_order == 'STRIP_THEN_PATCH':
                for i in range(N):
                    r = i // cols
                    c = i % cols + 1
                    sid = device_values[i][0]
                    sample_locs.append((sid, f"{row_label(r)}{c}"))
            elif index_order == 'PATCH_THEN_STRIP':
                for i in range(N):
                    c = i // rows + 1
                    r = i % rows
                    sid = device_values[i][0]
                    sample_locs.append((sid, f"{row_label(r)}{c}"))
            else:
                for i in range(N):
                    r = i // cols
                    c = i % cols + 1
                    sid = device_values[i][0]
                    sample_locs.append((sid, f"{row_label(r)}{c}"))
            sample_locs.sort(key=lambda t: t[0])
    return {
        'device_fields': device_fields,
        'device_values': device_values,
        'sample_locs': sample_locs,
        'color_rep_device': color_rep_device,
        'header_lines': header_lines
    }

def write_ti3(out_path: str,
              device_fields: List[str],
              device_values: List[Tuple[int, List[float]]],
              cr30: Dict,
              sample_locs: Optional[List[Tuple[int, str]]] = None,
              device_class: str = 'OUTPUT',
              ti2_header_lines: Optional[List[str]] = None) -> None:
    """Write an Argyll CGATS TI3 file.

    - device_fields: list of device channel field names
    - device_values: (SAMPLE_ID, [values]) list sorted by SAMPLE_ID
    - cr30: dict from parse_cr30_csv
    - sample_locs: optional (SAMPLE_ID, 'A1') list; if not provided, SAMPLE_LOC is omitted
    - device_class: DEVICE_CLASS header value (e.g., OUTPUT)
    - Data pass-through: write spectral/XYZ/Lab only if present in CSV; no conversions
    - ti2_header_lines: TI2 header lines for promoting select keys and recording provenance
    """
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    has_lab = any(r.get('L') is not None for r in cr30['rows'])
    has_xyz = any(r.get('X') is not None for r in cr30['rows'])
    has_spec = any(bool(r.get('spectral')) for r in cr30['rows'])
    include_xyz = has_xyz
    include_lab = has_lab
    dev_tag = 'RGB' if any(df.startswith('RGB_') for df in device_fields) else (
               'CMYK' if any(df.startswith('CMYK_') for df in device_fields) else 'DEV')
    # COLOR_REP reflects the included CIE columns: prefer XYZ if present, else LAB; for spectral-only, default to XYZ
    pcs = 'XYZ' if include_xyz else ('LAB' if include_lab else 'XYZ')
    color_rep = f"i{dev_tag}_{pcs}"
    N = min(len(device_values), len(cr30['rows']))
    loc_by_index: Optional[List[str]] = None
    if sample_locs and len(sample_locs) >= N:
        loc_by_index = [loc for (_sid, loc) in sample_locs[:N]]
    fields: List[str] = ['SAMPLE_ID']
    if loc_by_index is not None:
        fields.append('SAMPLE_LOC')
    fields.extend(device_fields)
    if include_xyz:
        fields.extend(['XYZ_X','XYZ_Y','XYZ_Z'])
    if include_lab:
        fields.extend(['LAB_L','LAB_A','LAB_B'])
    spec_wls_sorted: List[int] = []
    if has_spec:
        all_sets = [set(r['spectral'].keys()) for r in cr30['rows'] if r['spectral']]
        common = set.intersection(*all_sets) if all_sets else set()
        spec_wls_sorted = sorted(common)
        for wl in spec_wls_sorted:
            fields.append(f'SPEC_{wl:03d}')
    ordered_rows: List[Dict] = cr30['rows'][:N]
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('CTI3   \n\n')
        f.write('DESCRIPTOR "CR30 converted measurements"\n')
        f.write('ORIGINATOR "build_profile.py"\n')
        f.write(f'CREATED "{datetime.now().strftime("%a %b %d %H:%M:%S %Y")}"\n')
        f.write(f'DEVICE_CLASS "{device_class}"\n')
        f.write(f'COLOR_REP "{color_rep}"\n')
        if has_spec:
            f.write('INSTRUMENT_TYPE_SPECTRAL "YES"\n')
            if spec_wls_sorted:
                f.write(f'SPECTRAL_BANDS "{len(spec_wls_sorted)}"\n')
                f.write(f'SPECTRAL_START_NM "{float(spec_wls_sorted[0]):.6f}"\n')
                f.write(f'SPECTRAL_END_NM "{float(spec_wls_sorted[-1]):.6f}"\n')
        else:
            f.write('INSTRUMENT_TYPE_SPECTRAL "NO"\n')
        if ti2_header_lines:
            whitelist = {
                'COMP_GREY_STEPS', 'PAPER_SIZE', 'CHART_ID'
            }
            for hl in ti2_header_lines:
                s = hl.strip()
                if not s:
                    continue
                m = re.match(r'^([A-Z0-9_]+)\s+(.*)$', s)
                if not m:
                    continue
                key, rest = m.group(1), m.group(2)
                if key in whitelist:
                    f.write(f'{key} {rest}\n')
        f.write(f'\nNUMBER_OF_FIELDS {len(fields)}\n')
        f.write('BEGIN_DATA_FORMAT\n')
        f.write(' '.join(fields) + ' \n')
        f.write('END_DATA_FORMAT\n\n')
        f.write(f'NUMBER_OF_SETS {N}\n')
        f.write('BEGIN_DATA\n')
        for i in range(N):
            sid, dev = device_values[i]
            row = ordered_rows[i]
            line_parts: List[str] = [str(sid)]
            if loc_by_index is not None:
                line_parts.append(f'"{loc_by_index[i]}"')
            line_parts.extend([f'{v:.5f}' for v in dev])
            if include_xyz:
                if row.get('X') is not None and row.get('Y') is not None and row.get('Z') is not None:
                    line_parts.extend([f'{row["X"]:.6f}', f'{row["Y"]:.6f}', f'{row["Z"]:.6f}'])
                else:
                    line_parts.extend(['0.000000','0.000000','0.000000'])
            if include_lab:
                L = row.get('L'); a = row.get('a'); b = row.get('b')
                if L is not None and a is not None and b is not None:
                    line_parts.extend([f'{L:.2f}', f'{a:.2f}', f'{b:.2f}'])
                else:
                    line_parts.extend(['0.00','0.00','0.00'])
            if spec_wls_sorted:
                spec = row.get('spectral', {})
                for wl in spec_wls_sorted:
                    v = spec.get(wl)
                    line_parts.append(f'{(v if v is not None else 0.0):.6f}')
            f.write(' '.join(line_parts) + ' \n')
        f.write('END_DATA\n')

def resolve_input(p: str) -> str:
    if not p:
        return p
    if os.path.isabs(p):
        return p
    # If user gave a relative path with directories, respect it from workspace root
    if os.path.sep in p:
        return os.path.normpath(os.path.join(WS_ROOT, p))
    # Otherwise assume files live in src/input
    return os.path.join(IN_DIR, p)

def resolve_output(p: str) -> str:
    if not p:
        return p
    if os.path.isabs(p):
        _ensure_dir(os.path.dirname(p) or '.')
        return p
    # If user gave a relative path with directories, treat relative to workspace root
    if os.path.sep in p:
        out_path = os.path.normpath(os.path.join(WS_ROOT, p))
        _ensure_dir(os.path.dirname(out_path))
        return out_path
    # Otherwise write into src/output
    _ensure_dir(OUT_DIR)
    return os.path.join(OUT_DIR, p)

def run(cmd, env=None):
    print('> ' + ' '.join(cmd))
    try:
        res = subprocess.run(cmd, env=env)
    except FileNotFoundError as e:
        missing = cmd[0]
        print(f"Error: command not found: {missing}")
        if missing == 'colprof':
            print("Hint: Install ArgyllCMS and ensure 'colprof' is on your PATH, or set [colprof].run = false in src/profile_config.ini to skip profile generation.")
        sys.exit(127)
    if res.returncode != 0:
        print(f"Command failed with code {res.returncode}")
        sys.exit(res.returncode)

def main():
    cfg = configparser.ConfigParser()
    with open(CFG_PATH, 'r', encoding='utf-8') as f:
        cfg.read_file(f)

    csv = resolve_input(cfg.get('inputs', 'csv'))
    ti2 = resolve_input(cfg.get('inputs', 'ti2'))
    # Ordered workflow: we pair CSV row N with ti2 SAMPLE_ID N. SAMPLE_LOC is
    # copied from ti2 when present; if absent and resolvable from ti2 headers, it's generated deterministically; otherwise omitted.

    out_ti3 = resolve_output(cfg.get('outputs', 'ti3'))
    out_icc = resolve_output(cfg.get('outputs', 'icc'))
    desc = cfg.get('outputs', 'description', fallback='profile')

    device_class = cfg.get('options', 'device_class', fallback='OUTPUT')
    # No preference toggles: we pass through whatever the CSV contains

    # Preflight checks
    missing = False
    if not csv or not os.path.isfile(csv):
        print(f"Error: CSV not found -> {csv!r}. Edit inputs.csv in {CFG_PATH} or place the file under src/input.")
        missing = True
    if not ti2 or not os.path.isfile(ti2):
        print(f"Error: ti2 not found -> {ti2!r}. Edit inputs.ti2 in {CFG_PATH} or place the file under src/input.")
        missing = True
    if missing:
        sys.exit(2)
    # Warn early if colprof won't be available
    if cfg.getboolean('colprof', 'run', fallback=True) and shutil.which('colprof') is None:
        print("Warning: 'colprof' not found on PATH. ICC creation will fail. Either install ArgyllCMS or set [colprof].run = false in profile_config.ini to skip.")

    print(f"CSV: {csv}\nTI2: {ti2}\nTI3(out): {out_ti3}\n")
    # In-process conversion (single entry point)
    cr30 = parse_cr30_csv(csv)
    ti2_parsed = parse_ti2(ti2)
    write_ti3(
        out_path=out_ti3,
        device_fields=ti2_parsed['device_fields'],
        device_values=ti2_parsed['device_values'],
        cr30=cr30,
        sample_locs=ti2_parsed.get('sample_locs'),
        device_class=device_class,
        ti2_header_lines=ti2_parsed.get('header_lines')
    )
    print(f"✓ Wrote {out_ti3}")

    # Optionally run colprof
    if cfg.getboolean('colprof', 'run', fallback=True):
        # Common options
        quality = cfg.get('colprof', 'quality', fallback='m')  # l/m/h/u
        b2a = cfg.get('colprof', 'b2a', fallback='m')          # n/l/m/h/u
        illum = cfg.get('colprof', 'illuminant', fallback='D50')
        observer = cfg.get('colprof', 'observer', fallback='1931_2')
        threads = cfg.get('colprof', 'threads', fallback='1')

        # Advanced options
        algorithm = cfg.get('colprof', 'algorithm', fallback='')  # l,x,X,Y,g,s,m,G,S
        demphasis = cfg.get('colprof', 'demphasis', fallback='')  # float 1.0-4.0
        avgdev = cfg.get('colprof', 'avgdev', fallback='')        # -r avg %
        fwa_enable = cfg.getboolean('colprof', 'fwa', fallback=False)
        fwa_illum = cfg.get('colprof', 'fwa_illuminant', fallback='')
        source_map_perc = cfg.get('colprof', 'gamut_map_perceptual', fallback='')  # -s
        source_map_both = cfg.get('colprof', 'gamut_map_both', fallback='')        # -S
        use_col_src_p = cfg.getboolean('colprof', 'use_colorimetric_src_for_perceptual', fallback=False)  # -nP
        use_col_src_s = cfg.getboolean('colprof', 'use_colorimetric_src_for_saturation', fallback=False)  # -nS
        source_gamut_file = cfg.get('colprof', 'source_gamut_file', fallback='')  # -g
        abstract_chain = cfg.get('colprof', 'abstract_profiles', fallback='')     # -p
        perc_intent = cfg.get('colprof', 'perceptual_intent', fallback='')        # -t
        sat_intent = cfg.get('colprof', 'saturation_intent', fallback='')         # -T
        view_in = cfg.get('colprof', 'viewcond_in', fallback='')                  # -c
        view_out = cfg.get('colprof', 'viewcond_out', fallback='')                # -d
        gamut_vrml = cfg.getboolean('colprof', 'create_gamut_vrml', fallback=False)  # -P
        manufacturer = cfg.get('colprof', 'manufacturer', fallback='')            # -A
        model = cfg.get('colprof', 'model', fallback='')                          # -M
        copyright_s = cfg.get('colprof', 'copyright', fallback='')                # -C
        # Attributes & default intent via -Z
        attributes = cfg.get('colprof', 'attributes', fallback='')                # tmnb subset
        default_intent = cfg.get('colprof', 'default_intent', fallback='')        # p/r/s/a
        # Ink & black generation
        total_ink = cfg.get('colprof', 'total_ink_limit', fallback='')            # -l
        black_ink = cfg.get('colprof', 'black_ink_limit', fallback='')            # -L
        black_gen = cfg.get('colprof', 'black_generation', fallback='')           # -k params
        k_locus = cfg.get('colprof', 'k_locus', fallback='')                      # -K params
        # Shaper / data toggles
        no_device_shaper = cfg.getboolean('colprof', 'no_device_shaper', fallback=False)  # -ni
        no_grid_pos = cfg.getboolean('colprof', 'no_grid_position', fallback=False)       # -np
        no_output_shaper = cfg.getboolean('colprof', 'no_output_shaper', fallback=False)  # -no
        no_embed_ti3 = cfg.getboolean('colprof', 'no_embed_ti3', fallback=False)          # -nc
        input_auto_wp = cfg.getboolean('colprof', 'input_auto_scale_wp', fallback=False)  # -u
        input_force_abs = cfg.getboolean('colprof', 'input_force_absolute', fallback=False)  # -ua
        input_clip_wp = cfg.getboolean('colprof', 'input_clip_above_wp', fallback=False)   # -uc
        restrict_positive = cfg.getboolean('colprof', 'restrict_positive', fallback=False) # -R
        whitepoint_scale = cfg.get('colprof', 'whitepoint_scale', fallback='')             # -U

        env = os.environ.copy()
        env['OMP_NUM_THREADS'] = threads

        # Build colprof command
        base = os.path.splitext(out_ti3)[0]
        cmd = ['colprof', '-v', f'-q{quality}', f'-b{b2a}']

        # Detect if ti3 contains spectral data; if not, skip spectral-only flags (-i/-o/-f)
        has_spectral = False
        try:
            with open(out_ti3, 'r', encoding='utf-8') as fh:
                head = fh.read(4096)
                if 'INSTRUMENT_TYPE_SPECTRAL "YES"' in head or 'SPEC_' in head:
                    has_spectral = True
        except Exception:
            has_spectral = False
        # Algorithm
        if algorithm:
            cmd.extend(['-a', algorithm])
        # De-emphasis of dark regions
        if demphasis:
            cmd.extend(['-V', demphasis])
        # Average deviation
        if avgdev:
            cmd.extend(['-r', avgdev])
        # FWA compensation
        if fwa_enable and has_spectral:
            if fwa_illum:
                cmd.extend(['-f', fwa_illum])
            else:
                cmd.append('-f')
        # Gamut mapping
        def _append_source_map(flag: str, val: str):
            if not val:
                return
            lower = val.lower()
            is_file_like = lower.endswith(('.icc', '.icm', '.jpg', '.jpeg', '.tif', '.tiff'))
            if is_file_like:
                cand = resolve_input(val)
                if os.path.isfile(cand):
                    cmd.extend([flag, cand])
                else:
                    print(f"Warning: {flag} profile '{cand}' not found; skipping {flag}.")
            else:
                # percentage or inline value
                cmd.extend([flag, val])
        _append_source_map('-s', source_map_perc)
        _append_source_map('-S', source_map_both)
        if use_col_src_p:
            cmd.append('-nP')
        if use_col_src_s:
            cmd.append('-nS')
        if source_gamut_file:
            cmd.extend(['-g', source_gamut_file])
        if abstract_chain:
            cmd.extend(['-p', abstract_chain])
        # Intent overrides
        if perc_intent:
            cmd.extend(['-t', perc_intent])
        if sat_intent:
            cmd.extend(['-T', sat_intent])
        # Viewing conditions
        if view_in:
            cmd.extend(['-c', view_in])
        if view_out:
            cmd.extend(['-d', view_out])
        # VRML gamut
        if gamut_vrml:
            cmd.append('-P')
        # Profile identity strings
        if manufacturer:
            cmd.extend(['-A', manufacturer])
        if model:
            cmd.extend(['-M', model])
        if copyright_s:
            cmd.extend(['-C', copyright_s])
        # Attributes and default intent via -Z
        if attributes:
            cmd.extend(['-Z', attributes])
        if default_intent:
            cmd.extend(['-Z', default_intent])
        # Ink limits and black gen
        if total_ink:
            cmd.extend(['-l', total_ink])
        if black_ink:
            cmd.extend(['-L', black_ink])
        if black_gen:
            cmd.append('-k')
            cmd.extend(shlex.split(black_gen))
        if k_locus:
            cmd.append('-K')
            cmd.extend(shlex.split(k_locus))
        # Shaper & data toggles
        if no_device_shaper:
            cmd.append('-ni')
        if no_grid_pos:
            cmd.append('-np')
        if no_output_shaper:
            cmd.append('-no')
        if no_embed_ti3:
            cmd.append('-nc')
        if input_auto_wp:
            cmd.append('-u')
        if input_force_abs:
            cmd.append('-ua')
        if input_clip_wp:
            cmd.append('-uc')
        if restrict_positive:
            cmd.append('-R')
        if whitepoint_scale:
            cmd.extend(['-U', whitepoint_scale])
        if has_spectral:
            cmd.extend(['-i', illum, '-o', observer])
        else:
            print('Note: ti3 has no spectral data; skipping -i/-o/-f spectral flags')
        cmd.extend(['-D', desc, '-O', out_icc, base])
        run(cmd, env=env)
    else:
        print('Skipping colprof run (colprof.run=false)')

if __name__ == '__main__':
    main()
