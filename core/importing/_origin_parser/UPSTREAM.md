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

Six modules have their absolute `quantized...` imports rewritten to imports
relative to this private package. The two reader modules also carry file-level
Ruff suppressions, and `__init__.py` is a PL Analyzer Pro facade that dispatches
`.opj` and `.opju` to the corresponding upstream workbook reader.

PL Analyzer Pro additionally maintains two narrowly scoped, regression-tested
CPYA compatibility changes:

- `opj.py` recognizes dataset names at the format's structural name offsets,
  including 140-byte CPYA 4.2930 headers whose size is divisible by the
  10-byte numeric-record width, preserves the oldest 0x57-offset names, and
  prevents graph references from being mistaken for dataset headers.
- `windows.py` accepts the legacy 341-byte `Pd<Name>` sheet header and
  493-byte column-property block (including high-bit storage flags), supports
  Origin short names up to 16 characters, and maps each structurally
  identified sheet and sheet type to its exact `<Book>@N` metadata key.

The `DataStruct` contract is unchanged. Each modified upstream file carries a
prominent notice and the compatibility behavior is covered by redistributable
synthetic fixtures; user project files are not vendored.

The subset intentionally excludes figure/graph decoding, matrix pages, notes,
results logs, project-folder trees, templates, writers, routes, and all web
application code. Runtime dependencies are therefore Python 3.11+ and NumPy.

## Updating

Update only from a reviewed upstream release tag. Re-copy the files listed
above, reapply only the relative-import rewrite, update the version/commit
here, retain `LICENSE` and `NOTICE`, and rerun OPJ/OPJU workbook, multi-book,
X-plus-multiple-Y, malformed-input, real-instrument, and frozen-EXE tests.
