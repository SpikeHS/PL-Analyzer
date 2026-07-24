# quantized Origin worksheet reader

This directory vendors the worksheet/workbook-reading subset of
[pquarterman17/quantized](https://github.com/pquarterman17/quantized).

- Upstream package: `quantized-lab`
- Version: `0.11.0`
- Tag: `v0.11.0`
- Commit: `c34980b82947af3f82f7a9a4ff5692610ba5398f`
- Retrieved: `2026-07-24`
- License: Apache License 2.0

## Included upstream files

- `src/quantized/datastruct.py`
- `src/quantized/io/origin_project/container.py`
- `src/quantized/io/origin_project/opj.py`
- `src/quantized/io/origin_project/opju.py`
- `src/quantized/io/origin_project/opju_codec.py`
- `src/quantized/io/origin_project/opju_reports.py`
- `src/quantized/io/origin_project/origin_richtext.py`
- `src/quantized/io/origin_project/windows.py`
- `src/quantized/io/origin_project/windows_opju.py`
- upstream `LICENSE` and `NOTICE`

## Local changes

The parsing algorithms and data contract are unchanged. Six modules have only
their absolute `quantized...` imports rewritten to imports relative to this
private package. Each such file carries a prominent modification notice. The
two reader modules also carry file-level Ruff suppressions so the upstream
Python 3.11-compatible import order and generic syntax remain unchanged.
`__init__.py` is a PL Analyzer Pro facade that dispatches `.opj` and `.opju`
to the corresponding upstream workbook reader.

The subset intentionally excludes figure/graph decoding, matrix pages, notes,
results logs, project-folder trees, templates, writers, routes, and all web
application code. Runtime dependencies are therefore Python 3.11+ and NumPy.

## Updating

Update only from a reviewed upstream release tag. Re-copy the files listed
above, reapply only the relative-import rewrite, update the version/commit
here, retain `LICENSE` and `NOTICE`, and rerun OPJ/OPJU workbook, multi-book,
X-plus-multiple-Y, malformed-input, real-instrument, and frozen-EXE tests.
