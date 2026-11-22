---
log_id: 2026-11-20_02
date: 2026-11-20
type: WALKTHROUGH
status: executed
scope: [all]
source_artifact: d7_sampling_comparison.md
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Phase 4 Walkthrough — `D7` (`proportional` `25k` Default), Categorical Log-Density Tone Mapping, `SLO` Diagnosis & `.arrowtiles` vs. Sorted Parquet Benchmark

## 1. Summary of Changes

### Writer (`duckdb-arrowtiles`)
- **Locked `D7` & Generic `DEFAULT_TILE_CAPACITY = 25_000` ([builder.py](../arrowtiles/builder.py), [__main__.py](../arrowtiles/__main__.py), [SPEC.md](../docs/SPEC.md)):**
  - Set `sampling = "proportional"` and `DEFAULT_TILE_CAPACITY = 25_000` as the default for generic builds (`ArrowTilesBuilder.build`, `build_generic`, and `python -m arrowtiles build`), keeping `sampling = "even_coverage"` and `DEFAULT_GAIA_TILE_CAPACITY = 100_000` for `build_gaia` / `--preset gaia`.
  - Added `categorical_cols` (`--categorical-cols`) in `build_generic` so integer cluster ID columns (`clusters_07`, `clusters_14`, `clusters_28`) can be encoded directly as `UInt8` / `UInt16` v0.1 categoricals.
  - Added 5 independent 64-bit literal `SplitMix64` golden vectors (`0xE220A8397B1DCDAF`, `0xBDD732262FEB6E95`, `0xBA69EC90EB4FEF88`, `0xF3203E9039F4A821`, `0xF1C1278DBFA2126B`) in [test_phase3_priority_and_presets.py](../tests/test_phase3_priority_and_presets.py) (`48 passed, 1 skipped`).
  - Documented the `v0.2` per-tile density/category-count summary grid roadmap item under `"tile_stats"` in `docs/SPEC.md` §6.4.
- **Authored Full Phase 4 Benchmark Report ([BENCHMARK_parquet_vs_arrowtiles.md](../docs/BENCHMARK_parquet_vs_arrowtiles.md)):**
  - 5-run Median + P95 Chrome Web Worker HTTP-Range benchmark comparing `.arrowtiles` (`v0.1`), `parquet_tile_rg` (1 Row Group/tile + JSON index), and `parquet_page_idx` (`250k`-row Row Groups + Parquet V2 Page Index `OffsetIndex` + JSON index) across `gaia_sample` (`150k`), `lmsys_sample` (`100k`), `lmsys_full` (`2.84M`, 3-of-38 projection & 36-col full schema), and `gaia_100m` (`100,000,000` Gaia stars), plus `100k`/`50k`/`25k` capacity sweep and `SLO Status` cold-vs-warm latency decomposition.

### Viewer (`deepgraph-arrowtiles-sandbox`)
- **Log-Density Categorical Tone Mapping ([ComputeRasterizer.ts](https://github.com/kai-erlenbusch/deepgraph/blob/main/src/core/ComputeRasterizer.ts), `Scatterplot.ts`, [main.ts](https://github.com/kai-erlenbusch/deepgraph/blob/main/src/main.ts)):**
  - Widened `accumBuffer` to `3 × u32` (`12 B/px`) and replaced additive categorical splatting with per-pixel exact `hitWeightSum` (`u32`) + `16-bit` RGB accumulation resolved via logarithmic density brightness (`log2(1 + count) / log2(1 + refCount)`) × mean category color, eliminating dense-core white-out.
  - Switched `Hardware Instanced` categorical blending to `OneMinusSrcAlphaFactor` and auto-registered discrete integer `clusters_*` columns (`0..255`) in `main.ts`.

---

## 2. Verification Summary

| Check | Result |
| :--- | :--- |
| Writer `pytest -v -rs -p no:cacheprovider` | **`48 passed, 1 skipped in 10.58s`** |
| Viewer `npx tsc --noEmit` & `npm run build` | **`exit code 0`** |
| Live Chrome WebGPU `clusters_14` `Z=2` & `Z=4` renders + `SLO` telemetry check | **`exit code 0`** (`pageErrors: []`, `consoleErrors: []`) |
| Temporary `100M` Gaia benchmark files (`_tmp_phase4_parquet_bench`) | Cleaned up after writing `BENCHMARK_parquet_vs_arrowtiles.md` |
