---
log_id: 2026-11-22_05
date: 2026-11-22
type: WALKTHROUGH
status: executed
scope: [writer]
source_artifact: walkthrough.md
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Walkthrough: Pre-`v0.1.0` Writer Polish (`__index_level_*__` Auto-Drop & Guarded `Float64 → Float32` Downcast)

## 1. Summary of Changes

1. **Specification & Docs ([`docs/SPEC.md`](../docs/SPEC.md), [`README.md`](../README.md), [`AGENTS.md`](../AGENTS.md)):**
   - Clarified §4.2 (`"dropped_columns"`) so automatic omission covers both high-cardinality free-text columns (`distinct > max_categories`) and unrequested Pandas/PyArrow index artifact columns matching `^__index_level_\d+__$`.
   - Documented optional `Float64 → Float32` payload downcasting (`--keep-float64` opt-out) in §6.2, `README.md`, and `AGENTS.md` (and corrected `--max-zoom` default documentation to `14`).
2. **Builder Pipeline & CLI ([`arrowtiles/builder.py`](../arrowtiles/builder.py), [`arrowtiles/__main__.py`](../arrowtiles/__main__.py)):**
   - **Automatic `__index_level_<N>__` Omission:** When `columns` is omitted in `build_generic()`, columns matching `^__index_level_\d+__$` (unless explicitly referenced in `x_col`, `y_col`, `id_col`, `sort_col`, or `categorical_cols`) are omitted *before* `needed_src_cols` so DuckDB's Parquet reader skips reading them from disk altogether, and recorded in `metadata.dropped_columns`.
   - **Guarded `Float64 → Float32` Payload Downcast (`--keep-float64`):** Finite in-range `DOUBLE` payload columns (`|min|, |max| <= 3.4028234e38`, excluding `keep_source_xy` coordinate columns) are projected as `FLOAT` (`Float32`) with IEEE-754 `Float32`-rounded `stats` (`-0.0` normalized to `0.0`), while coordinate normalization and `sort_col` ordering remain full `Float64`. Out-of-range `DOUBLE` columns (`1e100`) and all integer columns stay untouched; `fingerprint_payload["retained_columns"]` now encodes `[column, sql_type]` so toggling `keep_float64` invalidates `--resume` Pass 1 partitions cleanly.
3. **Deterministic Windows `mmap` Teardown ([`arrowtiles/reader.py`](../arrowtiles/reader.py), [`arrowtiles/validator.py`](../arrowtiles/validator.py)):**
   - Replaced `pmtiles.reader.MmapSource` (whose closure kept `mmap.mmap` open until GC on Windows) with explicit `mmap.mmap` handles closed deterministically inside `ArrowTilesReader.close()` and `validate_file()`, allowing immediate `Path.unlink()` / `TemporaryDirectory` cleanup on Windows.
4. **Tests ([`tests/test_writer_polish_v01.py`](../tests/test_writer_polish_v01.py)):**
   - Added 6 pytest suites covering default `__index_level_0/1__` omission (plus immediate Windows `unlink()`), explicit `columns` / `sort_col` / `id_col` overrides, `Float32` byte savings + `±Infinity`/`NaN`/`NULL`/`-0.0` safety + SHA-256 determinism, `--keep-float64` CLI + `--resume` cache invalidation, `1e100` / `keep_source_xy` / direct `ArrowTilesBuilder.build()` guards, and sub-ULP `Float64` `sort_col` priority ordering before `Float32` storage.

---

## 2. Verification Results

- **Full Pytest Suite (`pytest -v -rs -p no:cacheprovider -W error::UserWarning`):** **`59 passed`** (`0` failures, `0` warnings, `0` skips).
- **Empirical LMSys `100,000`-Row Benchmark (`lmsys.parquet`, 39 columns):**
  - `--keep-float64`: **`10,218,159 B` (`9.74 MiB`)**, `Z=0..2 = 9.73 MiB`, `dropped_columns = ['__index_level_0__', 'conversation_id', 'content']`.
  - Default (`Float32` downcast across 13 `DOUBLE` score columns + `__index_level_0__` dropped): **`6,106,457 B` (`5.82 MiB`)**, `Z=0..2 = 5.81 MiB` (**`-40.2%` total archive size, `-40.3%` `Z=0..2` overview bytes**), `validate_file()` **PASS**.
- **GitHub Actions (`kai-erlenbusch/arrowtiles` `CI` + `Release Wheels & PyPI` dry-run):** Re-verified green on `main` prior to Stage 2b tag/publish sign-off.
