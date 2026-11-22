---
log_id: 2026-11-22_04
date: 2026-11-22
type: PLAN
status: executed
scope: [writer]
source_artifact: pre_v010_writer_polish_plan.md
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Implementation Plan: Pre-`v0.1.0` Writer Polish (`__index_level_*__` Auto-Drop & Guarded `Float64 → Float32` Downcast)

## 1. Goal Description

Before executing `⛔ D12c` Stage 2b (tagging `v0.1.0` and publishing immutable packages to PyPI and npm), include two high-leverage, 100% spec-compatible writer optimizations in `arrowtiles` `v0.1.0` identified during empirical tile inspection of `lmsys_d7_proportional_25k.arrowtiles`:

1. **Auto-drop Pandas/PyArrow leftover index columns (`^__index_level_\d+__$`):** Pandas DataFrames saved to Parquet without `index=False` write hidden `__index_level_0__` columns (~`3.5%` dead tile bytes on LMSys plus UI dropdown clutter in Deepgraph). When `columns` is not explicitly specified, `build_generic` omits unrequested `__index_level_<N>__` columns before preflight scanning (so DuckDB Parquet column pruning skips reading them from disk altogether) and records them in metadata `"dropped_columns"`.
2. **Guarded `Float64 → Float32` payload attribute downcast (`--keep-float64` opt-out):** On LMSys, moderation score columns (`[0, 1]`) stored as `DOUBLE` (`Float64`) accounted for `68%` of archive bytes. Deepgraph's WebGPU shaders already upload numeric columns as `f32` (and `pmtiles.worker.ts` hits a zero-loop `Float32Array.set()` fast path when tiles store `Float32`). Downcasting finite in-range `DOUBLE` payload columns to standard Arrow `Float32` shrinks float-heavy `.arrowtiles` archives by `~35–40%` with **zero `.arrowtiles` `v0.1` wire-format changes** and **zero changes to `deepgraph`**.

---

## 2. Precision & Safety Guardrails

1. **Coordinate Normalization (`x_col`, `y_col`):** Always computed in `Float64` (`DOUBLE`) before `u16` tile quantization (and if `--keep-source-xy` is requested, raw source `x_col`/`y_col` retain `Float64`).
2. **Priority Sorting (`--sort-col`):** `ArrowTilesBuilder.build()` evaluates `"__at_sort_key"` on the unrounded `Float64` source column *before* casting the projected tile payload column to `FLOAT`, so subtle `Float64` priority differences (`1.00000000` vs `1.00000001`) never reorder rows.
3. **Out-of-Range, `-0.0`, & Integer Safety:** Only `DOUBLE` (`Float64`) columns whose preflight finite `[min, max]` fits within `[-3.4028234e38, +3.4028234e38]` are downcast (`NaN` and `±Infinity` cast losslessly to IEEE-754 `Float32`; negative subnormals underflowing to `-0.0` normalize to `0.0` in JSON metadata; out-of-range columns such as `1e100` stay `Float64` with a diagnostic print). Integer columns (`BIGINT`, `UBIGINT`, etc.) are never converted to floats.
4. **Direct `ArrowTilesBuilder.build()` Callers & `--resume` Fingerprinting:** Direct `build(downcast_float32_cols=...)` calls apply the same `FLOAT32_SAFE_MAX` check and `_round_f32` rounding when computing `stats`, and `fingerprint_payload["retained_columns"]` records `[col, sql_type]` pairs so toggling `keep_float64` invalidates stale Pass 1 `--resume` partitions cleanly.

---

## 3. Planned File Changes

- [`docs/SPEC.md`](../docs/SPEC.md): Clarify §4.2 (`"dropped_columns"`) for `__index_level_<N>__` omission and §6.2 for optional `Float64 → Float32` payload downcasting.
- [`README.md`](../README.md) & [`AGENTS.md`](../AGENTS.md): Document `--keep-float64` and preflight column pruning / `Float32` downcasting.
- [`arrowtiles/builder.py`](../arrowtiles/builder.py) & [`arrowtiles/__main__.py`](../arrowtiles/__main__.py): Implement `PANDAS_INDEX_COL_RE` auto-drop, `FLOAT32_SAFE_MAX` guarded downcast, `_round_f32` (`-0.0 → 0.0`), `--resume` type fingerprinting, and `--keep-float64`.
- [`tests/test_writer_polish_v01.py`](../tests/test_writer_polish_v01.py): Add 6 comprehensive pytest cases covering default index drop, explicit overrides, `Float32` savings + `NaN`/`±Inf`/`NULL`/`-0.0` + SHA-256 determinism, `--keep-float64` CLI + `--resume` invalidation, `1e100` / `--keep-source-xy` / direct `build()` guards, and `Float64` `sort_col` ordering before `Float32` storage.
