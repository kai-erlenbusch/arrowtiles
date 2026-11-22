---
log_id: 2026-11-21_07
date: 2026-11-21
type: RESEARCH
status: approved
scope: [all]
source_artifact: arrowtiles_post_v01_improvements_research.md
conversation_id: fe52eab7-65ce-45dd-8140-b03acd621444
---

# Deep Research: High-Leverage Improvements Beyond ArrowTiles `v0.1`

> [!NOTE]
> Grounded in empirical bottlenecks measured during Phases 2–8 (our `50 ms` RTT / `50 Mbps` WAN benchmark, the `31.0 GB` 1.8B-row Gaia footprint, and `SPEC.md` `v0.1` reserved hooks) plus 2025–2026 columnar storage & interactive analytics research (**Apache Arrow IPC per-buffer ZSTD**, **Vortex / Lance**, **ALP & Byte-Stream-Split**, **Zstd trained dictionaries**, and **UW IDL Mosaic / `anywidget`**).

---

## 0. Pre-Publish `v0.1` Spec Prerequisite (Land Before `v0.1` Release)

Before publishing `v0.1`, tighten `SPEC.md` §1 version gating so `v0.1` readers cleanly reject breaking `0.2+` archives (such as single-file column groups):
- **0.x Minor-Version Rule:** While `major == 0`, compliant readers **MUST** reject archives whose `minor` version exceeds the highest minor version they implement (e.g., a `0.1` reader **MUST** reject `"version": "0.2"`).
- **Feature Negotiation (`"required_features"`):** Reserve `"required_features": string[]` in metadata (`[]` or omitted in `v0.1`); readers **MUST** reject any archive listing an unrecognized feature name.

---

## Executive Priority Matrix (Refined After `lmsys` 39-Column Empirical Audit)

| Phase | Improvement | Spec Break? | Empirical Evidence / Bottleneck Addressed | Expected Gain | Effort |
| :---: | :--- | :---: | :--- | :--- | :---: |
| **`v0.1.x`** | **Auto-Drop Pandas Index (`__index_level_0__`) + Safe `Float64 → Float32` Attribute Downcast** (`--keep-float64` opt-out) | **No** (100% `v0.1` valid) | In `lmsys_d7_proportional_25k` (`39` cols), `11` `Float64` score cols = **`68%` of file**; `__index_level_0__` = `3.5%` dead weight | **`~35–40%` smaller archives** on float-heavy tables, zero custom codecs, zero viewer changes | Very Low |
| **`v0.1.x`** | **`anywidget` Jupyter Bridge (`arrowtiles.plot()`)** | **No** | Python package builds files but doesn't render inline in notebooks | **1-line interactive WebGPU plots in Jupyter / Colab / Marimo** | Low |
| **`v0.2`** | **Single-File Column Groups via PMTiles `tile_id` Subspaces** (`hot`, click-only `row_id`, attribute groups) + External `"layers"` | **Yes (`v0.2`)** | Drawing `x, y, color` needs `~4.6 B/row` out of `~100 B/row` (`row_id` alone is `44%` of slim views); per-column Range reads caused `839`-request latency in Parquet | **`10×–20×` less WAN bytes** in *one* file, `1` Range req/tile/group, `0` extra header RTTs, **100% plain Arrow IPC** | Medium |
| **`v0.2`** | **`"tile_stats"` Table (`rows_represented`, `min`/`max`, `64`-bit category bloom) + Exact `Z=0..2` Density Grids** | **Yes (`v0.2`)** | Honest density normalization across LODs + skipping non-matching deep/clustered leaf tiles | Exact macro density + deep-tile filter pruning | Medium |
| **`v0.2`** | **Public WGSL Predicate Cross-Filtering API (`plot.setFilter(...)`)** | **No** (Viewer API) | Linked dashboard/Mosaic brushing without loading cold `row_id` arrays | `< 0.3 ms` GPU range/category/polygon cross-filtering | Medium |
| **`v0.2`** | **`2.5D` Dynamic Column Extrusion (`pitch` / `bearing`)** | **No** | Uses any loaded `Float32` column as dynamic elevation | 3D orbital exploration at 15% of octree cost | Medium |
| **`v0.3+`** | **`"tiling": "octree-3d"` + Optional Arrow `Float16` + Trained Zstd Dictionaries + Streaming Writer + `read_arrowtiles`** | **Yes (`v0.3`)** | True fly-inside 3D volumes, deep small-leaf compression, Stage 1 temp-file elimination (measure baseline spill on full Gaia build first), and spatial SQL inspection | Volumetric "COPC for any Arrow table" | Med–High |

---

## 1. Solving Wide-Table Read Amplification Without Parquet's Request Explosion (`v0.2`)

### Empirical Byte Breakdown (`lmsys_d7_proportional_25k.arrowtiles`, `39` Columns, `641k` Rows)
- `11 × category_scores.*` (`Float64`): **`~68%`** of compressed tile bytes (`7.1 B/row` each)
- `x_ncvis, y_ncvis` (`Float32` raw coords): **`6.4%`** (`3.7 B/row` each)
- `__index_level_0__` (leftover Pandas index): **`3.5%`** (`3.6 B/row`)
- `row_id` (`UInt64`, needed *only* on click/hover): **`3.5%`** (`3.6 B/row` — **`44%` of slim-view bytes** when drawing just `x_u16, y_u16, color`!)
- `x_u16 + y_u16` (`UInt16`): **`3.4%`** (`~4.0 B/row` combined)
- `clusters_14` (`UInt8` color): **`0.6%`** (`0.65 B/row`)

### Why Column Groups Inside One PMTiles Directory Beat Per-Column `RecordBatch` Slicing
Our Phase 4 WAN benchmark already proved that firing separate `Range` requests per column + reading an offset header (`parquet_page_idx`: `839` requests, `16s`) gets crushed by RTT multiplication. Instead, **keep every payload 100% plain Zstd Arrow IPC** (`group_schemas` stored in metadata per group) and store **Column Groups as distinct `tile_id` subspaces inside the single PMTiles v3 directory**:
- **2D Bit-Budget (`quadtree-2d`, $z \le 20$):** Max `tid_2d` is $\frac{4^{21}-1}{3} = 1.466 \times 10^{12} < 2^{41}$, leaving **`12` upper bits (`4,096` column-group slots)** below JavaScript's `Number.MAX_SAFE_INTEGER` ($2^{53} - 1 = 9.007 \times 10^{15}$).
- **3D Bit-Budget Compatibility (`octree-3d`):** At octree depth $z = 17$, `tid_3d` consumes `~51.2` bits (leaving only `3` groups under `2^53 - 1`). Therefore `octree-3d` in `v0.3` should either cap inline-group octree depth at **$z \le 14$** ($\frac{8^{15}-1}{7} < 2^{43} \implies$ **`1,024+` groups**, still giving $2^{30} \approx 10^9$ effective `u16` steps/axis!) or use `BigInt` directory decoding.
- **Implementation Guardrails:**
  - **JavaScript 32-Bit Shift Hazard:** Never write `(g << 41)` in JS/TS (bitwise shifts truncate to signed `Int32`!). Always compute `g * (2 ** 41)` (`g * 2199023255552`) or `BigInt`, verified with cross-language Rust/JS golden tests and `pmtiles verify`.
  - **`Group 0` (`tid = tid_2d`):** Hot geometry (`x_u16, y_u16, z` + default primary visual column) — **`1` HTTP Range request per visible tile, `0` extra header RTTs**.
  - **`Group 1` (`tid = 1 * 2**41 + tid_2d`):** Cold `row_id: UInt64` — fetched **only on click/hover** (`0 B` during pan/zoom!).
  - **`Group 2..K` (`tid = g * 2**41 + tid_2d`):** Attribute groups, pre-indexed in the single cached PMTiles directory.

---

## 2. Safe Plain-Arrow Compression Wins (`Float64 → Float32` With Precision Guards)

1. **Immediate `v0.1.x` Writer Defaults (Zero Custom Codecs, 100% Plain Arrow IPC):**
   - **Auto-drop DataFrame index artifacts** (`__index_level_0__`, `Unnamed: 0`) unless explicitly listed in `--columns`.
   - **Guarded `Float64 → Float32` Attribute Downcast:** Downcast continuous display `Float64` columns (like scores, embeddings, astrophysics metrics) to `Float32` by default, **skipping** temporal/epoch columns, exact integer-valued `Float64` IDs/counts exceeding $2^{24}$ (`16,777,216`), or columns failing a relative precision / domain-span tolerance (e.g. Unix epoch timestamps around `1.79e9`, where `Float32` ULP is `~128 s`). Always compute `"stats"` (`min`/`max`) in `Float64` *before* downcasting, record `"downcast_float32_columns"` in metadata, and keep `--keep-float64` opt-out.
   - **Drop `Byte-Stream-Split` / `ALP`:** Preserving *"every tile is a 100% standard Arrow IPC `RecordBatch`"* (`pyarrow`, `arrow-rs`, `apache-arrow` JS) is worth far more than custom non-Arrow float codecs.

---

## 3. `"tile_stats"`, WGSL Predicate Cross-Filtering & `anywidget` (`v0.1.x`–`v0.2`)

1. **`"tile_stats"` (`rows_represented` + Deep-Tile Zone Maps + Exact `Z=0..2` Density Grids):**
   - Store **`rows_represented`** per tile (total points in that spatial subtree) alongside `[min, max, null_count]` and a **64-bit category bloom mask** (`1 << (code % 64)`, supporting `> 64` categories with zero false negatives). Note: coarse `Z=0..2` random-sample tiles span most of the global range, so min/max skipping primarily accelerates **deep zoom (`Z=5+`)** and **spatially clustered attributes**, while `Z=0..2` pre-aggregated `128×128` count grids give exact population density on `10B+`-row tables.
2. **GPU Predicate Cross-Filtering (Instead of `row_id` Bitmasks):**
   - Keeping `row_id` cold (click-only) means cross-filtering (`UW IDL Mosaic` / `SQLRooms` linked charts) should push **WGSL filter conditions** (`score BETWEEN a AND b`, category bitset, 2D polygon/bbox) evaluated directly against already-loaded GPU columns in `< 0.3 ms` — matching how Mosaic expresses selections as SQL predicates rather than ID lists.
3. **`anywidget` (`arrowtiles.plot()`) & Scoped `read_arrowtiles`:**
   - `arrowtiles.plot()` via `dist/standalone.js` requires zero format changes (documenting Chrome/Edge WebGPU notebook requirements).
   - If a DuckDB `read_arrowtiles(...)` reader is added later (`v0.3`), document explicitly that `.arrowtiles` is a **visual spatial index** (`16`-bit tile-local coords + retained visual columns), not a lossless replacement for raw archival Parquet containing free-text blobs.

---

## 4. Zero-Scratch-Disk Streaming Writer & DuckDB Extension (`v0.2`–`v0.3`)

1. **Eliminating the Stage 1 Temp Parquet Spill:**
   Today `builder.py` materializes Hive-partitioned temporary Parquet chunks (`~40–60 GB` temporary NVMe usage on 1.8B Gaia) before Stage 2 Rust bucketing. Streaming coarse `Z=2` (`16` partitions) or `Z=3` (`64` partitions) batches directly over DuckDB's zero-copy **Arrow C Data Interface (`ArrowArrayStream`)** into bounded Rust `rayon` arenas cuts temporary disk usage to near zero (spilling only oversized macro-cells that exceed `RAM_BUDGET`).
2. **Bi-Directional DuckDB Integration (`read_arrowtiles`):**
   Because every `.arrowtiles` archive stores a clean Arrow `Schema` + Hilbert `tile_id` directory + `"bounds"` (and `"tile_stats"` in `v0.2`), a Python/Rust table function (and eventual DuckDB Community Extension) can expose `SELECT * FROM read_arrowtiles('https://cdn.../gaia.arrowtiles') WHERE x BETWEEN -1.37 AND -1.32 AND y BETWEEN -0.32 AND -0.29` — pushing the spatial bounding box straight into Hilbert `tile_id` ranges so **one `.arrowtiles` file serves both 60 FPS WebGPU visualization AND fast spatial SQL analytics!**
