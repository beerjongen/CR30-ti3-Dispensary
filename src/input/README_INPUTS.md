# Input folder overview

This folder holds the inputs required by the builder:

- CR30 CSV: semicolon-separated, with Lab and/or XYZ, and preferably spectral 400–700 nm @ 10 nm.
- ti2: the Argyll chart layout created by `printtarg` (device fields and patch locations).
- Optional source ICC: e.g., AdobeRGB1998.icc if you want -S/-s gamut mapping in colprof.

Workflow expectations:
- Ordered mapping: CSV row N corresponds to ti2 SAMPLE_ID N.
- SAMPLE_LOC: if present in ti2 data, it's copied to the ti3. If ti2 lacks SAMPLE_LOC but the header defines layout (STEPS_IN_PASS, PASSES_IN_STRIPS2, INDEX_ORDER), it is generated deterministically. Otherwise it is omitted which could produce unreliable ti3 files.
- Spectral precedence: if spectral columns are present, the TI3 will include spectral and any PCS columns (XYZ/Lab) that exist in your CSV. colprof will prefer spectral for the fit; XYZ/Lab are retained for manual auditing.

Replace these templates with your real inputs, and edit `src/profile_config.ini` accordingly.
