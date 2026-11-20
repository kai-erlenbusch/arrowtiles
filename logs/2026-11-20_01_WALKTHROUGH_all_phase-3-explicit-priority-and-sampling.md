---
log_id: 2026-11-20_01
date: 2026-11-20
type: WALKTHROUGH
status: executed
scope: [all]
source_artifact: d7_sampling_comparison.md
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Phase 3 Walkthrough — Portable `SplitMix64` Default Priority, `--preset gaia` (`phot_g_mean_mag`), HUD Telemetry & `⛔ D7` Sampling Comparison

## 1. Summary of Changes

### Writer (`duckdb-arrowtiles`)
- **Portable `SplitMix64` Default Priority ([SPEC.md](file:///D:/exploratory/duckdb-extension/duckdb-arrowtiles/docs/SPEC.md), [lib.rs](file:///D:/exploratory/duckdb-extension/duckdb-arrowtiles/arrowtiles-engine/src/lib.rs), [builder.py](file:///D:/exploratory/duckdb-extension/duckdb-arrowtiles/arrowtiles/builder.py)):**
  - Formalized unsigned 64-bit `splitmix64(row_id, seed)` in `SPEC.md` §6.1 (`0x9E3779B97F4A7C15`, `0xBF58476D1CE4E5B9`, `0x94D049BB133111EB`).
  - Replaced DuckDB's version-dependent `hash(...)` with `_duckdb_splitmix64_sql(...)` evaluated in 128-bit unsigned `UHUGEINT` with `xor(...)` and `& CAST(18446744073709551615 AS UHUGEINT)` wrapping, plus matching `splitmix64_py` in Python and `#[pyfunction] splitmix64_hash` in Rust.
  - Changed `ArrowTilesBuilder.build(..., sort_col: str | None = None)` so omitting `sort_col` defaults to `{"kind": "random", "seed": 42}` everywhere (removing the legacy `"abs_m"` default).
- **Explicit `--preset gaia` (`phot_g_mean_mag ASC`) & Flexible Input Schema ([builder.py](file:///D:/exploratory/duckdb-extension/duckdb-arrowtiles/arrowtiles/builder.py), [__main__.py](file:///D:/exploratory/duckdb-extension/duckdb-arrowtiles/arrowtiles/__main__.py)):**
  - Inspected input Parquet columns via `DESCRIBE` in `build_gaia(...)` so both raw ESA Gaia DR3 names (`phot_g_mean_mag`, `bp_rp`) and local `s3_cache` names (`magnitude`, `bv`) are accepted seamlessly (with `NULL::FLOAT` fallback for omitted optional kinematics columns).
  - Emits canonical `phot_g_mean_mag: Float32` sorted `ASC` (`view.sizeField = "phot_g_mean_mag"`) and forwards `sampling`, `grid_size`, `allow_oversize_leaves`, and `custom_config` from `python -m arrowtiles build --preset gaia`.
- **Samples & `⛔ D7` Comparison Pair ([build_samples.py](file:///D:/exploratory/duckdb-extension/duckdb-arrowtiles/scripts/build_samples.py)):**
  - Rebuilt `samples/gaia_sample.arrowtiles` (`phot_g_mean_mag ASC`) and `samples/lmsys_sample.arrowtiles` (`SplitMix64(seed=42)`), and added `--build-d7-comparison` to build full `2,835,490`-row `samples/lmsys_d7_even_coverage.arrowtiles` and `samples/lmsys_d7_proportional.arrowtiles`.

### Viewer (`deepgraph-arrowtiles-sandbox`)
- **Dual `phot_g_mean_mag` / Legacy `abs_m` Support ([Scatterplot.ts](file:///D:/exploratory/duckdb-extension/deepgraph-arrowtiles-sandbox/src/Scatterplot.ts), [ComputeRasterizer.ts](file:///D:/exploratory/duckdb-extension/deepgraph-arrowtiles-sandbox/src/core/ComputeRasterizer.ts), [main.ts](file:///D:/exploratory/duckdb-extension/deepgraph-arrowtiles-sandbox/src/main.ts)):**
  - Added `scatterplot.gaiaMagField` (`'phot_g_mean_mag'` when present in schema, else `'abs_m'`) across `getActiveColumns`, `getMaterialSignature`, `createMainMaterial`, `computeSlotMagBins`, `ComputeRasterizer.render`, `gaiaFallbacks`, Sky Lenses 10 & 1, and HR Diagram `yField`.
- **HUD Priority & Sampling Display + `/samples/` Dev Route ([main.ts](file:///D:/exploratory/duckdb-extension/deepgraph-arrowtiles-sandbox/src/main.ts), [vite.config.ts](file:///D:/exploratory/duckdb-extension/deepgraph-arrowtiles-sandbox/vite.config.ts)):**
  - Added `#tel-pyramid` line in the telemetry HUD displaying active `Priority` & `Sampling` via `.textContent`.
  - Added safe `?file=/...arrowtiles` query param support and `/samples/<name>.arrowtiles` HTTP Range serving from `../duckdb-arrowtiles/samples` (retaining `403` traversal protection).

---

## 2. Verification & `⛔ D7` Comparison Results

| Check | Result |
| :--- | :--- |
| `pytest -v -rs -p no:cacheprovider` | **`48 passed, 1 skipped in 14.71s`** (including `tests/test_phase3_priority_and_presets.py`: bit-exact Rust/Python/DuckDB `SplitMix64`, top-k random ranking, dual-schema Gaia preset + CLI forwarding, and explicit capacity/sampling passthrough) |
| `samples/lmsys_d7_even_coverage.arrowtiles` (`2,835,490` rows, `seed=42`) | **`[PASS]`** — `284.85 MiB` (`10,768` tiles, `zoom=0..7`, `max_tile_rows=79,008`, `max_compressed_tile=8.05 MiB`, SHA-256 `f77e6ab5f89573fcf8bc30c56fa1b9b1beade1d37f806147b0d457cd5dfbe64c`) |
| `samples/lmsys_d7_proportional.arrowtiles` (`2,835,490` rows, `seed=42`) | **`[PASS]`** — `279.00 MiB` (`61` tiles, `zoom=0..4`, `max_tile_rows=100,000`, `max_compressed_tile=10.24 MiB`, SHA-256 `aa41e950d0dcf56d8c183c0acff002b6ad9a65c9a707cc96e184ab9c80fc88ee`) |
| Viewer `npx tsc --noEmit` & `npm run build` | **`exit code 0`** |
| Live Chrome WebGPU verification (`gaia_full`, `gaia_sample` + HR Diagram, `lmsys_d7_even_coverage` & `lmsys_d7_proportional` at `Z=2` and `Z=4`) | **`exit code 0`** (`pageErrors: []`, `consoleErrors: []`) |
