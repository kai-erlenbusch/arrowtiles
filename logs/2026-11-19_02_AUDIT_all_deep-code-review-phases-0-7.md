---
log_id: 2026-11-19_02
date: 2026-11-19
type: AUDIT
status: approved
scope: [all]
source_artifact: deep_review_and_research_2026_11_19.md
conversation_id: fe52eab7-65ce-45dd-8140-b03acd621444
---

# Deep Code Review Audit: `duckdb-arrowtiles` & `deepgraph-arrowtiles-sandbox`

> [!WARNING]
> **Post-Verification Errata (2026-11-19 — see [`docs/PROGRESS_2026-11.md`](../docs/PROGRESS_2026-11.md) & [`2026-11-19_05_PLAN`](2026-11-19_05_PLAN_all_merged-consensus-revival-plan.md)):**
> 1. **`z_indices: HashMap` iteration order (Finding #1):** Does *not* affect output determinism because each zoom level writes to its own `z_{z}.parquet` buffer in input row order. The real reproducibility bugs are the `into_par_iter()` slot-claim race (`P5`) and unbroken SQL `ORDER BY` ties (`P4`).
> 2. **Single-word `atomic<u32>` pixel accumulators (Strength #2):** Do *not* prevent bit-field carry overflow under concurrent GPU workgroups (`atomicLoad` + `atomicAdd` is a TOCTOU race; $\ge 3$ concurrent threads overflow 10-bit Blue in `11-11-10`, and $\ge 6$ threads carry 20-bit `valSum` into `wSum` in Mode 2). Fixed in Phase 5b via `2 × atomic<u32>` per pixel.
> 3. **Coordinate column duplication & `x_norm` collision (Finding #3):** `run_bucketer` drops `x_norm`/`y_norm`, while `build_generic` retains the *source* coordinate columns (e.g., `x_umap`) and renames its computed `x_norm` to `x_norm_1` when the input already contains `x_norm`—silently bypassing normalization (`P2`).
> 4. **Per-tile `DictionaryBatch` framing (Finding #3):** Superseded by **D4** in [`SPEC.md`](../docs/SPEC.md) (`UInt8`/`UInt16` integer codes + metadata `stats[col].categories`, zero `DictionaryBatch` messages).

## 1. Executive Summary
A full line-by-line review was conducted across both repositories prior to executing the revival plan. All findings in `HANDOFF_2026-11-19_arrowtiles-revival.md` were verified against source code, and **10 additional technical findings** (4 blocking/high, 4 important/medium, 2 minor/housekeeping) were identified and mapped into Phases 0–7.

### Key Strengths Observed
- **Shared Vertex + Storage VRAM Buffer (`WebGPUAdapter.ts` + `Scatterplot.ts` + `ComputeRasterizer.ts`):** Packing `(x_u16, y_u16)` into 4 bytes per point allows `ComputeRasterizer` (`array<u32>`) and Three.js `InstancedBufferGeometry` (`vec2` normalized `Uint16Array`) to bind the exact same `GPUBuffer` with zero conversion copies.
- **Single-Word Lock-Free Pixel Accumulators (`ComputeRasterizer.ts:469–544`):** Packing 11-11-10 additive sRGB and 20-bit weighted sum + 12-bit weight mean-field accumulators into single `atomic<u32>` words with saturation guards avoids WebGPU 64-bit atomic extensions while preventing carry overflow.
- **Single-Pass Worker Zstd + Arrow IPC (`PMTilesClient.ts:254–258`, `pmtiles.worker.ts:87–98`):** Passing compressed Zstd tile bytes straight to the worker pool avoids main-thread decompression and extra `ArrayBuffer` copies.
- **Leaf Directory Prefetching (`PMTilesClient.ts:12–57`):** `FastFetchSource` caches the entire 367 KB PMTiles leaf directory region in one HTTP range request.

---

## 2. Verification of Handoff Findings & Newly Discovered Issues

### 🔴 Blocking / High-Severity Findings

1. **[Writer — Determinism] Parallel Slot-Claim Race (`lib.rs:152–207`) AND Unbroken SQL Sort Ties (`arrowtiles.py:103–107, 193–198`)**
   - *Handoff finding verified:* `into_par_iter()` races on `coarse_bitsets.fetch_or`, `mid_counts.fetch_add`, and `deep_counts.fetch_add`.
   - *New finding:* Even after making Rust slot-claiming deterministic, DuckDB's multi-threaded external `ORDER BY {q_sort} {sort_dir_clean}` in Pass 1 (`arrowtiles.py:106`) and `ORDER BY final_tile_id ASC, {q_sort} {sort_dir_clean}` in Pass 2 (`arrowtiles.py:193`) is **non-deterministic whenever two rows share equal `sort_col` values** (common in integer metrics like `num_of_tokens` or quantized float32 `abs_m`). Additionally, `z_indices: HashMap<u8, Vec<u32>>` (`lib.rs:245`) uses randomized hash iteration order.
   - *Action (Phase 1 & Phase 2):* Assign stable `row_id` before/during Pass 1, break all SQL `ORDER BY` clauses with `, row_id ASC`, use `BTreeMap` for `z_indices`, and make Rust slot claiming deterministic in priority order.

2. **[Writer — Correctness] `NaN` Coordinate Poisoning in `build_generic` (`arrowtiles.py:306–325, 381–387`)**
   - *New finding:* In DuckDB SQL, IEEE-754 `NaN` satisfies `IS NOT NULL` and dominates `MAX(col)` (`MAX(x)` returns `NaN` if even a single row is `NaN`). This turns `range_x` into `NaN`, making every row's `x_norm` become `NaN`, which `lib.rs:155` (`raw_x.is_finite()`) silently clamps to `(0.5, 0.5)`.
   - *Action (Phase 1):* Filter `isfinite(x) AND isfinite(y)` in both bounds aggregation and Pass 1 normalization queries.

3. **[Writer + Spec — Format] Dictionary-Encoded (`ENUM`) Tile Framing & Coordinate Duplication (`lib.rs:368–385, 435–441`, `arrowtiles.py:165–166, 381–386`)**
   - *New finding (Spec clarity):* When `categorical_columns` are present, `ArrowTilesPacker::new` measures `global_schema_size` using an empty `StreamWriter` (Schema message only), while `flush_chunk_buffer` writes a `RecordBatch` containing `DictionaryArray` columns — causing Arrow's `StreamWriter` to emit `[Schema][DictionaryBatch(es)][RecordBatch][EOS]`. Slicing `&sink[global_schema_size..]` therefore embeds `DictionaryBatch` message(s) at the start of every compressed tile payload (starting with `0xFFFFFFFF`), which `apache-arrow` JS `tableFromIPC([globalSchemaBuffer, rawData])` parses cleanly. `SPEC.md` v0.1 must document this exact framing explicitly.
   - *New finding (Column duplication & collision):* `build_generic` uses `SELECT *, CAST(...) AS x_norm, CAST(...) AS y_norm`, which (a) collides if the input Parquet already contains `x_norm`/`y_norm` (the CLI default!), and (b) leaves raw `x_col`/`y_col` float64 columns duplicated inside every tile alongside `x_u16`/`y_u16`.
   - *Action (Phase 1):* Document DictionaryBatch framing in `SPEC.md`; use `SELECT * EXCLUDE (...)` or safe internal aliases (`__arrowtiles_x_norm`) in `build_generic`.

4. **[Viewer — GPU & CPU Memory] Dataset Swap VRAM Leak + 1 MiB/Slot/Column CPU Shadow Arrays (`WebGPUAdapter.ts:27–36`, `Scatterplot.ts:232–237, 781–802`)**
   - *Handoff finding verified & mechanism proven:* `Scatterplot.clearAllTiles()` never destroys `GPUBuffer`s attached to `renderer.backend.get(attr).buffer`, never disposes `slotMeshes[i].geometry`, and leaves previous dataset column attributes attached to all 256 slot geometries across `loadDataset()` swaps.
   - *New finding:* `Scatterplot.ts:233–235` allocates a full `Float32Array(262144)` (1 MiB) on the CPU per column per active slot even when `writeToDeviceQueue` writes straight to VRAM (`250 slots × 8 cols = ~2 GB` of redundant JS ArrayBuffers), and `ComputeRasterizer` lacks a `dispose()` method for its GPU buffers.
   - *Action (Phase 5 & Phase 6):* Centralize buffer creation/destruction in `WebGPUAdapter.ts`, instrument `window.__gpuStats` in Phase 6, and verify zero leak across panning eviction and 5× dataset swaps.

---

### 🟡 Important / Medium-Severity Findings

5. **[Writer + Viewer — Coordinate Semantics] Inverted Y-Axis Convention Between `build_gaia` and `build_generic` (`arrowtiles.py:259, 384`, `main.ts:323`)**
   - `build_gaia` pre-inverts `y_norm = 1.0 - ...` (`0` = North/top, `1` = South/bottom), whereas `build_generic` computes `y_norm = (y - min_y) / range_y` (`0` = `min_y`/bottom, `1` = `max_y`/top). Meanwhile `main.ts:323` maps `domain [0, 1] -> range [1, -1]` when `flipY = false`, rendering every `build_generic` dataset upside-down unless `Flip Y` is toggled.
   - *Action (Phase 1):* Lock down a single unambiguous coordinate direction in `SPEC.md` (with `bounds` metadata) so the writer, Python reference reader, and WebGPU viewer agree without dataset-specific hacks.

6. **[Writer + Viewer — Capacity Semantics] `max_capacity` 2.62× Inflation & Leaf Tile Overflow Truncation (`arrowtiles.py:76`, `lib.rs:97–106, 180`, `Scatterplot.ts:27, 905`)**
   - `max_capacity = 100,000` rounds `grid_size` up to `512` and squares it to `tile_capacity = 262,144` (`2.62×` requested capacity). At `z == effective_max_zoom`, `lib.rs:180` accepts unlimited rows (`claimed = true`), while `Scatterplot.ts:905` silently clamps `Math.min(tile.numRows, 262144)`, dropping overflow points in ultra-dense leaf tiles.
   - *Action (Phase 1 & Phase 2):* Document exact capacity rules in `SPEC.md`; decouple `tile_capacity` from `grid_int^2` where appropriate and verify completeness in `validate` + viewer.

7. **[Writer — Environment Hazard] Stale Root `arrowtiles_core.pyd` Shadows Installed Wheel/Venv (`duckdb-arrowtiles/arrowtiles_core.pyd`)**
   - An untracked `arrowtiles_core.pyd` built on `2026-07-22` sits in the writer repo root (`sys.path[0]`), shadowing newer `site-packages/arrowtiles_core` builds whenever Python is invoked from the repo root.
   - *Action (Phase 0):* Guard `tests/conftest.py` so `pytest` loads the `.venv` build from `maturin develop --release`, and ask owner permission before deleting/archiving the stale root `arrowtiles_core.pyd`.

8. **[Viewer — Dev Server Resilience & Security] `arrowtilesFastRangePlugin` in `vite.config.ts:41–100`**
   - Missing directory-containment check on `path.resolve(...)` (bypasses `server.fs.strict` for `*.arrowtiles` while `host: true` binds to LAN); unbounded `Buffer.allocUnsafe(chunkLen)` risks V8 OOM on open-ended `Range: bytes=0-` over 31 GB files; perpetual `fdCache` locks files on Windows and serves stale `stat.size` if a file is overwritten.
   - *Action (Phase 4 / Phase 5):* Enforce path containment within project root/public, cap single range chunk allocation (or stream large ranges), and validate `mtimeMs`/`size` on cached FDs.

---

### 🟢 Minor / Housekeeping Findings

9. **[Viewer — Dependencies] Phantom `fflate` Import & Unused `@sentry/*` Packages (`PMTilesClient.ts:5`, `package.json:19–20`)**
   - `PMTilesClient.ts` imports `fflate` directly, relying on `three`'s transitive dependency rather than declaring `fflate` in `package.json`. `@sentry/browser` and `@sentry/tracing` are installed (~2 packages) without initialization anywhere in `src/`.
10. **[Viewer — Dead Prototype Code] Unused Files (`src/ui.ts`, `src/counter.ts`, `tests/compute_test.mjs`, `PMTilesClient.ts:379` `rawPayloads`)**
   - `src/ui.ts` and `src/counter.ts` are never imported; `tests/compute_test.mjs` is 0 bytes; `rawPayloads` pool recycling in `PMTilesClient.ts` is unreachable dead code. Clean up during Phase 5 refactor (with owner approval before any file deletion).

---

## 3. Recommended Refinements to Phases 0–7 Plan
The handoff's 8-phase structure (`Phases 0–7`) is well-sequenced and sound. Based on this audit, we incorporate four targeted refinements within the existing phases (no scope expansion):
1. **Phase 0:** Use a local `.venv` (`--system-site-packages`) so `maturin develop --release` works natively on Windows, and configure `tests/conftest.py` so `pytest` imports the freshly compiled `.venv` extension rather than the stale July 22 root `arrowtiles_core.pyd`.
2. **Phase 1:** Explicitly specify `DictionaryBatch` placement, `isfinite` NaN filtering, safe internal coordinate aliases (`__arrowtiles_x_norm`), and canonical y-axis orientation + `bounds` metadata in `SPEC.md` v0.1.
3. **Phase 2:** Add `, row_id ASC` deterministic tie-breaking to both Pass 1 and Pass 2 DuckDB `ORDER BY` queries and switch `z_indices` from `HashMap` to `BTreeMap` in `lib.rs` alongside deterministic slot claiming — otherwise duplicate `sort_col` values will break byte-identical rebuilds (`2a`).
4. **Phase 6:** Track **both** WebGPU `GPUBuffer` bytes (`window.__gpuStats`) and `slotMeshes` CPU `ArrayBuffer` footprint so dataset-swap and slot-reuse leaks are eliminated on both GPU and CPU.
