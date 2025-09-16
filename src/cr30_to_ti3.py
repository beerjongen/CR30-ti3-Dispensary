#!/usr/bin/env python3
"""
CR30 → ti3 converter

Reads a CHNSPEC CR30 export CSV (semicolon-separated, decimal comma aware),
and a ti1 (for device values and device space), then writes a CGATS/Argyll .ti3
file using strict index pairing (no SAMPLE_LOC matching). The script detects available Lab/XYZ/Spectral
columns and populates the header accordingly. If only Lab is present and XYZ is
requested, it converts Lab→XYZ using D50 white.

Usage
-----
Preferred entry point: run `python3 build_profile.py`, which reads `profile_config.ini`, calls this converter, and (optionally) runs `colprof`.

Standalone examples (only if you want to generate a TI3 directly):
    # Provide your own files explicitly (no built-in defaults)
    python3 cr30_to_ti3.py \
        --csv "input/your_measurements.csv" \
        --ti1 "input/your_target.ti1" \
        --out "output/your_result.ti3"

"""
import argparse
import re
from datetime import datetime
import os
from typing import List, Dict, Tuple, Optional

# --------------------- Utilities ---------------------

def _to_float(val: str) -> Optional[float]:
    if val is None:
        return None
    s = val.strip().replace(',', '.')
    if s == '' or s.lower() in ('nan', 'null'):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def lab_to_xyz(L: float, a: float, b: float, illuminant: str = 'D50') -> Tuple[float, float, float]:
    # Reference whites
    if illuminant.upper() == 'D50':
        Xn, Yn, Zn = 96.422, 100.000, 82.521
    elif illuminant.upper() == 'D65':
        Xn, Yn, Zn = 95.047, 100.000, 108.883
    else:
        # Default to D50 if unknown
        Xn, Yn, Zn = 96.422, 100.000, 82.521
    fy = (L + 16.0) / 116.0
    fx = fy + (a / 500.0)
    fz = fy - (b / 200.0)
    delta = 6.0/29.0
    def f_inv(t: float) -> float:
        if t > delta:
            return t**3
        return 3*delta*delta*(t - 4.0/29.0)
    X = Xn * f_inv(fx)
    Y = Yn * f_inv(fy)
    Z = Zn * f_inv(fz)
    return X, Y, Z

# --------------------- CR30 CSV parsing ---------------------

def _read_text_with_fallback(path: str) -> str:
    for enc in ('utf-8', 'utf-8-sig', 'cp1252', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    # Last resort: binary read and decode latin-1 to avoid crash
    with open(path, 'rb') as f:
        return f.read().decode('latin-1', errors='replace')


def parse_cr30_csv(path: str) -> Dict:
    """Parse CR30 CSV. Returns dict with:
    {
      'rows': [
         {
           'name': str,
           'date': str,
           'test_mode': str,
           'light_source_angle': str,  # e.g. 'D50/10°'
           'L': float|None,
           'a': float|None,
           'b': float|None,
           'X': float|None,
           'Y': float|None,
           'Z': float|None,
           'spectral': { wavelength:int -> reflectance float (0-100)} | {}
         }, ...
      ],
      'illum_code': 'D50'|'D65'|None,
      'observer_deg': 2|10|None
    }
    """
    text = _read_text_with_fallback(path)
    # Normalize line endings
    lines = [ln.rstrip('\r') for ln in text.split('\n')]
    if not lines:
        raise ValueError('Empty CSV file')

    header = [h.strip() for h in lines[0].split(';')]
    # Build column index mapping (case/space tolerant)
    norm = lambda s: re.sub(r'[^a-z0-9_]+', '', s.strip().lower())
    hmap: Dict[str, int] = {norm(h): i for i, h in enumerate(header)}

    # Heuristics for known columns
    idx_name = hmap.get('name')
    idx_date = hmap.get('date')
    idx_mode = hmap.get('testmode')
    idx_lsag = hmap.get('lightsourceangle')
    
    # L*a*b*
    idx_L = hmap.get('l') or hmap.get('l*') or hmap.get('lstar')
    idx_a = hmap.get('a') or hmap.get('a*') or hmap.get('astar')
    idx_b = hmap.get('b') or hmap.get('b*') or hmap.get('bstar')

    # XYZ (if present)
    idx_X = hmap.get('x')
    idx_Y = hmap.get('y')
    idx_Z = hmap.get('z')

    # Detect spectral columns: patterns like 'spec_400', '400nm', 'r400nm', 'reflectance400', etc.
    spec_cols: List[Tuple[int, int]] = []  # (col_index, wavelength)
    for key, i in hmap.items():
        m = re.search(r'(\d{3})(?:nm)?$', key)
        if m:
            wl = int(m.group(1))
            if 300 <= wl <= 1100:  # reasonable guard
                spec_cols.append((i, wl))
    spec_cols.sort(key=lambda t: t[1])

    rows = []
    illum_code: Optional[str] = None
    observer: Optional[int] = None

    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(';')
        # Basic filter: look for measurement rows - many CR30 exports set Name to 'target'
        name = parts[idx_name] if idx_name is not None and idx_name < len(parts) else ''
        # Skip rows lacking Lab/XYZ entirely
        L = _to_float(parts[idx_L]) if idx_L is not None and idx_L < len(parts) else None
        a = _to_float(parts[idx_a]) if idx_a is not None and idx_a < len(parts) else None
        b = _to_float(parts[idx_b]) if idx_b is not None and idx_b < len(parts) else None
        X = _to_float(parts[idx_X]) if idx_X is not None and idx_X < len(parts) else None
        Y = _to_float(parts[idx_Y]) if idx_Y is not None and idx_Y < len(parts) else None
        Z = _to_float(parts[idx_Z]) if idx_Z is not None and idx_Z < len(parts) else None
        if L is None and X is None:
            # no Lab nor XYZ, likely not a measurement row
            continue

        lsag = parts[idx_lsag] if idx_lsag is not None and idx_lsag < len(parts) else ''
        test_mode = parts[idx_mode] if idx_mode is not None and idx_mode < len(parts) else ''
        date = parts[idx_date] if idx_date is not None and idx_date < len(parts) else ''

        # Spectral map for this row
        spectral: Dict[int, float] = {}
        if spec_cols:
            for ci, wl in spec_cols:
                if ci < len(parts):
                    v = _to_float(parts[ci])
                    if v is not None:
                        spectral[wl] = v

        # Derive illum/observer once from first non-empty LS/angle
        if illum_code is None and lsag:
            # Expect like "D50/10°" or "D65/2°"
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

# --------------------- ti1 parsing ---------------------

def parse_ti1(path: str) -> Dict:
    """Parse ti1 to get device space and per-patch device values.
    Returns {
      'device_fields': ['RGB_R','RGB_G','RGB_B'] or ['CMYK_C',...],
      'device_values': [(1, [R,G,B]), ...],
      'color_rep_device': 'iRGB'|'RGB'|'CMYK'|... (from COLOR_REP if available)
    }
    """
    device_fields: List[str] = []
    device_values: List[Tuple[int, List[float]]] = []
    color_rep_device = None

    with open(path, 'r', encoding='utf-8') as f:
        lines = [ln.rstrip('\n') for ln in f]

    # Grab COLOR_REP device part if present
    for ln in lines[:50]:
        m = re.match(r'^COLOR_REP\s+"([^"]+)"', ln)
        if m:
            color_rep_device = m.group(1)
            break

    # Locate BEGIN_DATA_FORMAT / END_DATA_FORMAT
    fmt_start = None
    fmt_end = None
    for i, ln in enumerate(lines):
        if ln.strip() == 'BEGIN_DATA_FORMAT':
            fmt_start = i + 1
        elif ln.strip() == 'END_DATA_FORMAT':
            fmt_end = i
            break
    if fmt_start is None or fmt_end is None:
        raise ValueError('ti1 missing data format block')

    # Collect all tokens in data format (can span multiple lines)
    fmt_tokens: List[str] = []
    for ln in lines[fmt_start:fmt_end]:
        fmt_tokens.extend(ln.split())
    fields = fmt_tokens
    # Detect device fields by explicit allowed prefixes only (exclude SAMPLE_ID/XYZ/etc.)
    allowed_prefixes = ("RGB_", "CMYK_", "GRAY_", "K_")
    device_fields = [f for f in fields if any(f.startswith(p) for p in allowed_prefixes)]
    # Fallback: if not found, infer from common RGB/CMYK fields
    if not device_fields:
        for f in ("RGB_R","RGB_G","RGB_B","CMYK_C","CMYK_M","CMYK_Y","CMYK_K"):
            if f in fields:
                device_fields.append(f)

    # Parse data rows
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
            vals: List[float] = []
            for f in device_fields:
                try:
                    idx = fields.index(f)
                except ValueError:
                    vals.append(0.0)
                    continue
                # Shift by 0 because parts includes SAMPLE_ID at index 0 as well; fields[0] should be SAMPLE_ID
                # Map field index to parts index
                pidx = idx  # SAMPLE_ID is explicit in fields
                if pidx < len(parts):
                    v = _to_float(parts[pidx])
                    vals.append(v if v is not None else 0.0)
                else:
                    vals.append(0.0)
            device_values.append((sid, vals))

    # Sort by SAMPLE_ID
    device_values.sort(key=lambda t: t[0])
    return {
        'device_fields': device_fields,
        'device_values': device_values,
        'color_rep_device': color_rep_device
    }

# --------------------- ti3 writing ---------------------

def write_ti3(out_path: str,
              device_fields: List[str],
              device_values: List[Tuple[int, List[float]]],
              cr30: Dict,
              device_class: str = 'OUTPUT',
              prefer_spectral: bool = True,
              prefer_xyz_over_lab: bool = True) -> None:
    # Ensure output directory exists for standalone use (builder handles this elsewhere)
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    # Determine availability
    has_lab = any(r.get('L') is not None for r in cr30['rows'])
    has_xyz = any(r.get('X') is not None for r in cr30['rows'])
    has_spec = any(bool(r.get('spectral')) for r in cr30['rows'])
    # Decide what to include to avoid redundancy
    # If spectral is present and preferred, include spectral only (no XYZ/Lab)
    include_xyz = False
    include_lab = False
    if has_spec and prefer_spectral:
        include_xyz = False
        include_lab = False
    else:
        if has_xyz and (not has_lab or prefer_xyz_over_lab):
            include_xyz = True
            include_lab = False
        elif has_lab:
            include_xyz = False
            include_lab = True

    # Compose COLOR_REP from device space
    # Infer device tag from device_fields prefix
    dev_tag = 'RGB' if any(df.startswith('RGB_') for df in device_fields) else (
               'CMYK' if any(df.startswith('CMYK_') for df in device_fields) else 'DEV')
    # Prefer XYZ if selected, else LAB; if spectral-only, we still indicate XYZ as the intended PCS
    pcs = 'XYZ' if (include_xyz or (has_spec and prefer_spectral)) else 'LAB'
    color_rep = f"i{dev_tag}_{pcs}"

    # Build field list
    fields: List[str] = ['SAMPLE_ID']
    fields.extend(device_fields)
    if include_xyz:
        fields.extend(['XYZ_X','XYZ_Y','XYZ_Z'])
    if include_lab:
        fields.extend(['LAB_L','LAB_A','LAB_B'])
    # If spectral present, add SPEC_XXX
    spec_wls_sorted: List[int] = []
    if has_spec:
        # Intersect wavelengths across rows to ensure consistent columns
        all_sets = [set(r['spectral'].keys()) for r in cr30['rows'] if r['spectral']]
        common = set.intersection(*all_sets) if all_sets else set()
        spec_wls_sorted = sorted(common)
        for wl in spec_wls_sorted:
            fields.append(f'SPEC_{wl:03d}')

    # Safety: align counts
    N = min(len(device_values), len(cr30['rows']))

    # Strict index order pairing only: assume input rows are in the same order as target
    ordered_rows: List[Dict] = cr30['rows'][:N]

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('CTI3   \n\n')
        f.write('DESCRIPTOR "CR30 converted measurements"\n')
        f.write('ORIGINATOR "cr30_to_ti3.py"\n')
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
        # Include helpful comments
        ls = cr30.get('illum_code')
        obs = cr30.get('observer_deg')
        if ls:
            f.write(f'# ILLUMINANT_CODE "{ls}"\n')
        if obs:
            f.write(f'# OBSERVER "{obs} deg"\n')
        f.write('# INSTRUMENT "CHNSPEC CR30"\n')
        f.write('# GEOMETRY "45/0"\n')

        # Data format
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
            # Device values
            line_parts.extend([f'{v:.5f}' for v in dev])
            # Colorimetric
            # XYZ (if selected)
            if include_xyz:
                if row.get('X') is not None and row.get('Y') is not None and row.get('Z') is not None:
                    line_parts.extend([f'{row["X"]:.6f}', f'{row["Y"]:.6f}', f'{row["Z"]:.6f}'])
                elif row.get('L') is not None and row.get('a') is not None and row.get('b') is not None:
                    # Compute from Lab under D50 by default
                    Xc, Yc, Zc = lab_to_xyz(row['L'], row['a'], row['b'], illuminant='D50')
                    line_parts.extend([f'{Xc:.6f}', f'{Yc:.6f}', f'{Zc:.6f}'])
                else:
                    line_parts.extend(['0.000000','0.000000','0.000000'])
            # Lab (if selected)
            if include_lab:
                L = row.get('L'); a = row.get('a'); b = row.get('b')
                if L is not None and a is not None and b is not None:
                    line_parts.extend([f'{L:.2f}', f'{a:.2f}', f'{b:.2f}'])
                else:
                    line_parts.extend(['0.00','0.00','0.00'])
            # Spectral
            if spec_wls_sorted:
                spec = row.get('spectral', {})
                for wl in spec_wls_sorted:
                    v = spec.get(wl)
                    line_parts.append(f'{(v if v is not None else 0.0):.6f}')
            f.write(' '.join(line_parts) + ' \n')
        f.write('END_DATA\n')

# --------------------- Main ---------------------

def main():
    p = argparse.ArgumentParser(description='Convert CR30 CSV + ti1 to Argyll .ti3 (order-only)')
    # All inputs must be provided explicitly when used standalone
    p.add_argument('--csv', required=True)
    p.add_argument('--ti1', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--device-class', default='OUTPUT')
    p.add_argument('--no-prefer-spectral', action='store_true', help='If spectral present, do not force spectral-only; allow XYZ/Lab as per availability')
    p.add_argument('--prefer-lab', action='store_true', help='When choosing a single PCS (no spectral), prefer Lab over XYZ')
    args = p.parse_args()

    # Parse inputs
    cr30 = parse_cr30_csv(args.csv)
    ti1 = parse_ti1(args.ti1)

    # Write ti3
    write_ti3(
        out_path=args.out,
        device_fields=ti1['device_fields'],
        device_values=ti1['device_values'],
        cr30=cr30,
        device_class=args.device_class,
        prefer_spectral=not args.no_prefer_spectral,
        prefer_xyz_over_lab=not args.prefer_lab
    )

    print(f"✓ Wrote {args.out}")

if __name__ == '__main__':
    main()
