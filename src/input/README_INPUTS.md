# Input folder overview

This folder holds the inputs required by the builder:

- CR30 CSV: semicolon-separated, with Lab and/or XYZ, and preferably spectral 400–700 nm @ 10 nm.
- ti1: the Argyll target definition created by `targen` (device fields RGB_* or CMYK_*).
- Optional source ICC: e.g., AdobeRGB1998.icc if you want -S/-s gamut mapping in colprof.

Workflow expectations:
- Ordered mapping only: CSV row N must correspond to ti1 patch N.
- We do not use ti2/SAMPLE_LOC in this workflow.
- Spectral-first: if spectral columns are present, the converter writes spectral-only ti3 by default.

Replace these templates with your real inputs, and edit `src/profile_config.ini` accordingly.
