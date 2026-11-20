---
log_id: 2026-11-19_07
date: 2026-11-19
type: WALKTHROUGH
status: executed
scope: [all]
source_artifact: null
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Phase 2 Walkthrough — Deterministic 2-Stage Bucketer, Single-Pass Preflight, `D7a`, `--resume` & 100M/2.84M Verification

## 1. Summary of Changes

### Writer (`duckdb-arrowtiles`)
- **Deterministic Zero-Atomic 2-Stage Batch Bucketer (`arrowtiles-engine/src/lib.rs`, `Cargo.toml`):**
  - Removed `dashmap` and all atomic operations in `run_bucketer`.
  - **Stage A (Parallel, Stateless):** Computes `(ix_20, iy_20, h_20)` in parallel via Rayon (`16 B/row`).
  - **Stage B (Sequential, Deterministic):** Claims `Vec<u64>` (`coarse_bitsets`), `Vec<u32>` (`coarse_counts`, `mid_counts`), and `HashMap<u64, u32>` (`deep_counts`) in strict `(priority_key, row_id ASC)` order, writing directly into Arrow `ScalarBuffer` vectors (`UInt8Array`, `UInt64Array`, `UInt16Array`).
- **Single-Pass SQL Preflight, `D7a` `dropped_columns`, & Full `--resume` Fingerprint (`arrowtiles/builder.py`):**
  - Merged row counts, `id_col` validation, bounds, numeric stats, and string distinct counts into a single preflight scan in `build_generic`, `build_gaia`, and direct `ArrowTilesBuilder.build()`.
  - Implemented `D7a`: string columns with `distinct > max_categories` (`4,096` default) are dropped by default unless explicitly requested in `columns=`, logged clearly, and recorded in `"dropped_columns": [...]` in metadata.
  - Upgraded `partitions/manifest.json` (`arrowtiles-partitions-v2`) with a SHA-256 fingerprint over resolved input files (`path`, `size`, `mtime_ns`) + all build parameters, automatically invalidating stale partitions when any input or setting changes.
  - Enforced `sort_keys=True` across all JSON metadata serialization for byte-identical output.
- **Specification & Validator (`docs/SPEC.md`, `arrowtiles/validator.py`):**
  - Tightened `SPEC.md` §2.5 (`> 16 MiB` warning, `> 64 MiB` error on `v0.1`), §4.2/§6.4 (`dropped_columns`), §5.2 (`z <= 6` with `z < nominal_max_zoom` for `even_coverage`), and §6.2 (`0 <= code < len(categories)`).
  - Updated `validator.py` to enforce `<= 64 MiB` compressed tile ceiling on `v0.1`, per-tile categorical code bounds, and `dropped_columns` schema exclusion.
- **Tests & Sample Builder (`tests/test_determinism_and_completeness.py`, `scripts/build_samples.py`):**
  - Added 13 new tests (bringing total to `44 passed, 1 skipped`) covering byte-identical SHA-256 rebuilds (unique, all-tied, seeded-random), per-cell ($z \le 6 \land z < \text{nominal\_max\_zoom}$) and per-tile priority monotonicity, `resume=True` byte-identical output + stale-manifest invalidation, `D7a` drop + opt-in, and invalid category code detection.
  - Added `--include-lmsys-full` to `scripts/build_samples.py` to build gitignored `samples/lmsys_full_v01.arrowtiles` (`2,835,490` rows).

### Viewer (`deepgraph-arrowtiles-sandbox`)
- **Bounded Explicit Range Handling (`vite.config.ts`):** Preserved `16 MiB` cap on open-ended `Range: bytes=start-`, enabled explicit `Range: bytes=start-end` up to `64 MiB` (serving legacy `lmsys_full.arrowtiles`'s `25.15 MiB` tile `3/4/4` without truncation), and returned `413 Payload Too Large` above `64 MiB`.
- **Arrow Boolean Unpacking (`src/pmtiles.worker.ts`):** Added bit-unpacking for `Type.Bool` columns (`0.0` / `1.0`, `NaN` for nulls) in `getFloat32Col`.

---

## 2. Benchmark & Verification Summary

| Check | Result |
| :--- | :--- |
| **100M Gaia Pass 1 Benchmark — Phase 1 Atomic (`25a1a93`)** | `75.503 s` (`1.324 M rows/s`, `actual_max_z = 8`) |
| **100M Gaia Pass 1 Benchmark — Phase 2 2-Stage Deterministic** | **`56.394 s` (`1.773 M rows/s`) — `25.3%` faster (`+33.9%` throughput)** |
| **Full 2.84M LMSys `v0.1` Double-Build SHA-256 (`lmsys_full_v01.arrowtiles`)** | **Exact match:** `552f70129e3a53497acb11b59ae2ebbaf12f1c1221d303d1b70596c36b5dcd45` (`277.6 MiB` vs. `802.5 MiB` legacy; `max_compressed_tile = 7.82 MiB` vs. `25.15 MiB`; `dropped_columns = ["conversation_id", "content"]`) |
| **Writer `pytest -v -rs -p no:cacheprovider`** | **`44 passed, 1 skipped in 8.29s`** |
| **Viewer `npx tsc --noEmit` & `npm run build`** | **`exit code 0`** |
| **Dev Server Range Verification (`127.0.0.1:5199`)** | `bytes=0-` → `206` (`16 MiB`); `bytes=17791-26384857` → `206` (`26,367,067 B` full); `bytes=0-73400320` → `413 Payload Too Large` |
