---
log_id: 2026-11-19_06
date: 2026-11-19
type: WALKTHROUGH
status: executed
scope: [all]
source_artifact: null
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Phase 1 Walkthrough — `SPEC.md` v0.1, `arrowtiles/` Package, Validator, Reader & Viewer Compatibility

## 1. Summary of Changes

### Writer (`duckdb-arrowtiles`)
- **Packaging (`pyproject.toml`, `arrowtiles/`):** Replaced monolithic root `arrowtiles.py` with an installable `arrowtiles` package (`module-name = "arrowtiles._core"`, preventing root `.pyd` drops). Added `*.pdb` and `samples/` to `.gitignore`.
- **Rust PyO3 Engine (`arrowtiles-engine/src/lib.rs`):**
  - Enforced two-tier capacity (`tile_capacity` at `z < nominal_max_zoom` vs. `max_tile_rows` at `z >= nominal_max_zoom`, spilling overflow up to `z = 20`) and failing on `z = 20` exact-duplicate overflow unless `--allow-oversize-leaves` is enabled.
  - Replaced per-zoom Hilbert calls with a single `fast_hilbert::xy2h(ix_20, iy_20, 20)` evaluation + 2-bit shift ancestor derivation, verified by `verify_hilbert_shift_invariants()` (`0` violations across exhaustive `z = 1..5` + 20,000 SplitMix64 samples).
  - Enforced non-nullable `row_id: UInt64`, `x_u16: UInt16`, `y_u16: UInt16`, `z: UInt8` in the exported Arrow IPC `Schema`, rejected `DictionaryType`, returned `PyValueError` on invalid/non-object/reserved-key `custom_metadata`, wrote `.min_zoom(0).max_zoom(actual_max_z)`, and finalized atomically via `<output>.tmp` -> `<output>`.
- **Python Builder, Reader, Validator & CLI (`arrowtiles/builder.py`, `reader.py`, `validator.py`, `__main__.py`, `scripts/build_samples.py`):**
  - Deterministic dense `row_id` via lexicographically sorted `parquet_file_metadata` + `read_parquet(..., filename=true, file_row_number=true)`; explicit `id_col` required for custom SQL queries.
  - `NaN`/`±Inf`/`NULL` coordinate filtering (`dropped_rows`), finite-only `stats` (`allow_nan=False`), `NULL`/`NaN`-last priority sorting in both `ASC` and `DESC`, `UInt8` (`1..256`) / `UInt16` (`257..65,535`) category codes (`D4`), top-down `y_norm = (max_y - y) / span_y` (`D3`), and `partitions/manifest.json` `--resume` validation.
  - Reference `ArrowTilesReader` (`read_tile`, `iter_tiles`, coordinate & category decoding) and `validate_file` / `python -m arrowtiles validate` (checking all v0.1 invariants, v0.0 legacy compatibility warnings, and reporting `max_compressed_tile_bytes`).

### Viewer (`deepgraph-arrowtiles-sandbox`)
- **`src/PMTilesClient.ts`:** Replaced hardcoded `z <= 14` cap with `archiveMaxZoom` read from the PMTiles header (`actual_max_z` on v0.1; `14` fallback when legacy v0.0 reports default `22`) and bounded non-spatial quadtree traversal (`!isSpatialX && !isSpatialY`) at `z <= 2` (`F-07`).
- **`src/pmtiles.worker.ts`:** Decoded Arrow `nullBitmap -> NaN` (`chunk.nullCount > 0` with `chunk.offset`), filled missing columns with `NaN`, and converted `BigInt64Array`/`BigUint64Array` values via `Number(...)`.
- **`src/Scatterplot.ts` & `src/core/ComputeRasterizer.ts`:** Expanded categorical palette to 64 distinct colors + deterministic golden-ratio HSV fallback for `code >= 64`, and guarded `NaN` / `< 0` categorical values to neutral gray `(0.42, 0.42, 0.46)` in both `Compute (Atomic)` and `Hardware Instanced` engines (using TSL `mix` around `TextureNode` to avoid a Three.js `0.172.0` `ConditionalNode` `generateUV` crash).
- **`src/main.ts`:** Added `format`/`version` checking, `metadata.bounds` aspect-ratio fitting, `metadata.view` support, `metadata.stats[col].categories` seeding on load, exclusion of `'row_id'`/`'z'`/`Utf8` from `schemaFields`, automatic `computeMode = 1` for categorical coloring, and `state.flipY = false` reset across Gaia Sky Lenses (`F-06`).

---

## 2. Verification Summary

| Check | Result |
| :--- | :--- |
| Writer `pytest -v -rs -p no:cacheprovider` | `13 passed, 1 skipped in 3.28s` |
| `validate samples/gaia_sample.arrowtiles` (`4.26 MiB`) | `PASS` (`spec=0.1`, `342` tiles, `149,942` rows, `zoom=0..7`, `max_compressed_tile=566,728 B` / `0.54 MiB`) |
| `validate samples/lmsys_sample.arrowtiles` (`0.77 MiB`) | `PASS` (`spec=0.1`, `137` tiles, `100,000` rows, `zoom=0..5`, `max_compressed_tile=137,717 B` / `0.13 MiB`) |
| `validate public/lmsys_full.arrowtiles` (`legacy v0.0`) | `PASS (legacy v0.0)` (`31,473` tiles, `2,835,490` rows; flagged `max_compressed_tile=25.15 MiB` at `3/4/4` due to embedded raw text) |
| Viewer `npx tsc --noEmit` & `npm run build` | `exit code 0` |
| Live Chrome WebGPU Playwright (`v0.0` + `v0.1` Gaia & LMSys + HR/Sky Lens) | `exit code 0` (`pageErrors: []`, `consoleErrors: []`) |
