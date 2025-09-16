#!/usr/bin/env python3
import configparser
import os
import shlex
import subprocess
import sys
import shutil

HERE = os.path.dirname(__file__)
CFG_PATH = os.path.join(HERE, 'profile_config.ini')
WS_ROOT = os.path.abspath(os.path.join(HERE, '..'))
IN_DIR = os.path.join(HERE, 'input')
OUT_DIR = os.path.join(HERE, 'output')

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

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
    ti1 = resolve_input(cfg.get('inputs', 'ti1'))
    # Ordered workflow: ti2/SAMPLE_LOC are intentionally not used

    out_ti3 = resolve_output(cfg.get('outputs', 'ti3'))
    out_icc = resolve_output(cfg.get('outputs', 'icc'))
    desc = cfg.get('outputs', 'description', fallback='profile')

    device_class = cfg.get('options', 'device_class', fallback='OUTPUT')
    prefer_spectral = cfg.getboolean('options', 'prefer_spectral', fallback=True)
    prefer_lab = cfg.getboolean('options', 'prefer_lab', fallback=False)

    # Preflight checks
    missing = False
    if not csv or not os.path.isfile(csv):
        print(f"Error: CSV not found -> {csv!r}. Edit inputs.csv in {CFG_PATH} or place the file under src/input.")
        missing = True
    if not ti1 or not os.path.isfile(ti1):
        print(f"Error: ti1 not found -> {ti1!r}. Edit inputs.ti1 in {CFG_PATH} or place the file under src/input.")
        missing = True
    if missing:
        sys.exit(2)
    # Warn early if colprof won't be available
    if cfg.getboolean('colprof', 'run', fallback=True) and shutil.which('colprof') is None:
        print("Warning: 'colprof' not found on PATH. ICC creation will fail. Either install ArgyllCMS or set [colprof].run = false in profile_config.ini to skip.")

    # Build ti3 using cr30_to_ti3.py
    script = os.path.join(os.path.dirname(__file__), 'cr30_to_ti3.py')
    cmd = [sys.executable, script,
           '--csv', csv,
           '--ti1', ti1,
           '--out', out_ti3,
           '--device-class', device_class]
    if not prefer_spectral:
        cmd.append('--no-prefer-spectral')
    if prefer_lab:
        cmd.append('--prefer-lab')
    print(f"CSV: {csv}\nTI1: {ti1}\nTI3(out): {out_ti3}\n")
    run(cmd)

    # Optionally run colprof
    if cfg.getboolean('colprof', 'run', fallback=True):
        # Common options
        quality = cfg.get('colprof', 'quality', fallback='m')  # l/m/h/u
        b2a = cfg.get('colprof', 'b2a', fallback='m')          # n/l/m/h/u
        illum = cfg.get('colprof', 'illuminant', fallback='D50')
        observer = cfg.get('colprof', 'observer', fallback='1931_2')
        threads = cfg.get('colprof', 'threads', fallback='1')
        extra = cfg.get('colprof', 'extra_args', fallback='')

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
        if extra.strip():
            cmd.extend(shlex.split(extra))
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
