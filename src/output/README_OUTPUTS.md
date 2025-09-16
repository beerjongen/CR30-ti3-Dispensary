# Output folder

The builder writes outputs here by default:

- .ti3 — CGATS measurement file (base name and path from `[outputs].ti3`)
- .icc — Profile created by colprof when `[colprof].run = true` (path from `[outputs].icc`)

Naming:
- The colprof invocation uses the ti3 basename for the profile unless overridden by `[outputs].icc`.

Notes:
- If you only want the ti3 (no profile), set `[colprof].run = false`.
- When spectral data is present, the TI3 includes spectral and any PCS columns from the CSV; colprof will use spectral for the profile fit.
