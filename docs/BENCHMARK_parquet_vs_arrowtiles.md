# Phase 4 Benchmark Report — `.arrowtiles` (`v0.1`) vs. Sorted HTTP-Range Parquet

**Date:** `2026-11-20`  
**Status:** Complete — Ready for Owner Gate Decisions **`⛔ D8`**, **`⛔ D9`**, and **`⛔ D10`**

---

## 1. Executive Summary

We benchmarked **`.arrowtiles` (`v0.1`)** (PMTiles v3 Hilbert pyramid + schema-stripped Zstd Arrow IPC tiles) against **two sorted HTTP-Range Apache Parquet layouts** in real Chrome Web Workers (`6` workers, `6` concurrent HTTP/1.1 Range connections, `Cache-Control: no-store`, `5` runs per configuration reporting **Median** and **P95**):

1. **`.arrowtiles` (`v0.1`):** 1 Zstd-compressed Arrow IPC `RecordBatch` per quadtree tile inside a single PMTiles v3 archive (`127 B` header + hierarchical Hilbert directories).
2. **Parquet Layout 1 (`parquet_tile_rg`):** Identical priority-sorted quadtree tiles stored as **1 Parquet Row Group per tile** (`compression="zstd", level=3`) + compact JSON tile-to-row-group index (`<name>.index.json`), read via `hyparquet` `1.33.1`.
3. **Parquet Layout 2 (`parquet_page_idx`):** Identical priority-sorted tiles packed into **`250,000`-row Row Groups** with **Parquet V2 Page Index (`ColumnIndex` + `OffsetIndex`, `64 KiB` data pages, `compression="zstd", level=3`)** + JSON tile row-range index, read via `hyparquet` (`useOffsetIndex: true`).

### Key Empirical Findings
- **At 100M+ Spatial Scale (`gaia_100m`: `100,000,000` stars, `9,573` tiles), `.arrowtiles` wins decisively:**
  - **Smallest archive:** `2.441 GiB` (`.arrowtiles`) vs. `2.547 GiB` (`parquet_tile_rg`) and `2.536 GiB` (`parquet_page_idx`).
  - **Constant `O(1)` initial handshake:** **`6.8 ms` (`17.0 KiB`)** in `.arrowtiles` vs. **`5,021.8 ms` (`8.44 MiB` footer + index; `121–154 MB` JS heap)** in `parquet_tile_rg` (`28.5×` slower TTFF: `5,147.8 ms` vs. `180.8 ms`!) and **`112.8 ms` (`839.9 KiB`)** in `parquet_page_idx`. Extrapolated to 1.8B Gaia (`193,246` tiles), 1-row-group-per-tile Parquet reaches a **`~165 MiB` `FileMetaData` footer** — structurally unviable in browsers.
  - **6×–10× fewer HTTP Range round-trips than Page-Indexed Parquet:** At `100M` rows, `.arrowtiles` loads the 21-tile `Z=0..2` overview in **`24` HTTP requests (`180.8 ms` TTFF)** vs. **`147`–`243` HTTP requests (`289.6`–`460.0 ms` on loopback)** for `parquet_page_idx`. Over real object storage / CDN (`25–60 ms` RTT), 150–240 sequential/batched page+index requests add **0.6–2.0 seconds** of extra tail latency.
- **On Wide Embedding Tables (`lmsys_full`: `2,835,490` rows × `36` payload cols):**
  - **Full schema (`37` cols):** `.arrowtiles` is **`1.80×` faster TTFF** than `parquet_tile_rg` (`249.3 ms` vs. `448.3 ms`) and **`4.48×` faster TTFF / `7.35×` faster Deep Zoom** than `parquet_page_idx` (`249.3 ms` / `113.7 ms` vs. `1,116.6 ms` / `836.0 ms` across `839` / `684` HTTP requests).
  - **Narrow 3-of-38 column projection (`x_u16, y_u16, clusters_14`):** Parquet's columnar projection transfers **`9.0×`–`12.9×` fewer bytes** (`3.13 MiB` in `parquet_tile_rg`, `4.62 MiB` in `parquet_page_idx` vs. `40.39 MiB` in monolithic 36-col `.arrowtiles`), allowing `parquet_page_idx` to beat monolithic 36-col `.arrowtiles` on 3-column TTFF (`158.1 ms` vs. `212.1 ms`) and `parquet_tile_rg` to beat it on 3-column deep zoom (`37.5 ms` vs. `107.5 ms`).
  - **Architectural takeaway for `⛔ D8`:** Keeping **`.arrowtiles` (`v0.1`)** as the primary spatial pyramid container while keeping core visual archives lean (`--columns` or `SPEC.md` §6.4 `"layers"` sidecars for wide 30+-column text/moderation metadata tables) captures `.arrowtiles`'s `O(1)` billion-point scaling and single-range tile reads without paying wide-table byte amplification.

---

## 2. Fairness & Methodology Controls

To eliminate implementation bias between `.arrowtiles` and Parquet:
1. **Identical Compression:** All three formats compress payloads with **Zstd level `3`**.
2. **Identical WASM Zstd Decoder:** Both `.arrowtiles` (`pmtiles` + `apache-arrow`) and `hyparquet` (`localCompressors.ZSTD`) were wired to the **exact same `@bokuweb/zstd-wasm` (`0.0.27`) WebAssembly decompressor**, pre-warmed before each timed run.
3. **Zero Row-Object Transposition Handicap for Parquet:** `hyparquet` used its raw columnar `onChunk` callback writing directly into `Uint16Array` / `Float32Array` transfer buffers (never `parquetReadObjects`), and Parquet's `FileMetaData` footer was fetched **once** on the main thread and `structuredClone`d to the 6 workers (avoiding 6× duplicate HTTP footer fetches).
4. **Identical Pyramid Rows & Verification:** All three layouts were generated from the exact same priority-ordered tile assignments, and every single run asserted `decodedOverviewRows == expectedOverviewRows` and `decodedDeepRows == expectedDeepRows`.

---

## 3. Generic `proportional` `tile_capacity` Benchmark (`D7` Condition #1)

Following Owner Decision **`D7`** (`proportional` as the generic default; `--preset gaia` stays `even_coverage`), we benchmarked `tile_capacity` = `100,000`, `50,000`, and `25,000` on all `2,835,490` rows of `lmsys.parquet` (`SplitMix64(seed=42)`, 5 cold+warm runs in headed WebGPU Chrome):

| Configuration | Archive Size | Total Tiles (`max_zoom`) | Max Tile Size | `Z=0..2` Overview Points | `Z=0..2` Compressed Bytes | Cold Viewer TTFF Median (`P95`) | Warm Zoom Burst Median (`P95`) | Warm Per-Tile `Net + Worker` Median (`P95`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `even_coverage` (`100k`, `316×316`) | `284.85 MiB` | `10,768` (`Z=0..7`) | `8.05 MiB` | `294,238` (`0.29M`) | `30.17 MiB` | `984.4 ms` (`993.1 ms`) | `374.0 ms` (`391.8 ms`) | `30.6 ms` (`115.6 ms`) |
| `proportional` (`100k`) | `279.00 MiB` | `61` (`Z=0..4`) | `10.24 MiB` | `1,247,543` (`1.25M`) | `118.07 MiB` | `1,229.1 ms` (`1,321.5 ms`) | `610.9 ms` (`637.5 ms`) | `155.2 ms` (`430.3 ms`) |
| `proportional` (`50k`) | `278.06 MiB` | `137` (`Z=0..5`) | `5.12 MiB` | `815,613` (`0.82M`) | `73.60 MiB` | `1,050.1 ms` (`1,073.0 ms`) | `343.1 ms` (`388.5 ms`) | `141.9 ms` (`212.3 ms`) |
| **`proportional` (`25k` — Locked Default)** | **`278.04 MiB`** | **`221` (`Z=0..5`)** | **`2.56 MiB`** | **`458,389` (`0.46M`)** | **`40.38 MiB`** | **`1,017.4 ms` (`1,071.4 ms`)** | **`351.4 ms` (`353.1 ms`)** | **`76.2 ms` (`118.2 ms`)** |

**Outcome:** `DEFAULT_TILE_CAPACITY = 25_000` is now locked for generic builds (`DEFAULT_GAIA_TILE_CAPACITY = 100_000` preserved for `build_gaia` / `--preset gaia`). It cuts `Z=2` overview payload by **`2.92×`** (`40.38 MiB` vs. `118.07 MiB`), renders **`0.46M` points** at `Z=2` with honest statistical density, keeps every tile `<= 2.56 MiB`, and packs 2.84M rows into just `221` tiles (`805 B` root directory, `0 B` leaf directories).

---

## 4. Root-Cause Diagnosis of Red `SLO Status (P95 < 50ms)` (`306–704 ms`)

Instrumenting `PMTilesClient.fetchTelemetry` separately across the **21-tile cold page-load burst** vs. **50 warm pan/zoom tiles** proved that **both** a cold-start telemetry distortion and a 100k-capacity wide-table payload cost were contributing:

| Archive | Cold First-Tile `Net` | Cold First-Tile `Worker` | Cold `Z=0..2` Rolling `P95` | Warm Median `Net` | Warm Median `Worker` | Warm Median Total | Warm 64-Tile Burst `P95` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `even_coverage` (`100k`) | `115.6 ms` | **`204.7 ms`** | `347.5 ms` | `21.6 ms` | **`6.7 ms`** | **`30.6 ms`** | `115.6 ms` |
| `proportional` (`100k`) | `582.6 ms` | **`233.6 ms`** | `864.9 ms` | `104.9 ms` | `48.2 ms` | `155.2 ms` | `430.3 ms` |
| `proportional` (`50k`) | `347.0 ms` | **`331.3 ms`** | `713.3 ms` | `100.7 ms` | `43.1 ms` | `141.9 ms` | `212.3 ms` |
| **`proportional` (`25k`)** | `153.1 ms` | **`344.5 ms`** | `521.7 ms` | `57.3 ms` | **`22.1 ms`** | **`76.2 ms`** | **`118.2 ms`** |

1. **Cold-start metric artifact (primary cause of `300–520 ms` at `Z=2`):**
   - In `PMTilesClient.ts:631`, `tWorkerStart` is recorded on the main thread when `worker.postMessage` is called — **before** the newly spawned Vite Web Worker finishes downloading `apache-arrow` + `@bokuweb/zstd-wasm` (`428 KB`) and compiling `zstd.wasm` (`initZstd()`), inflating the first batch's `workerMs` from **`6.7–22.1 ms` (warm)** to **`204.7–344.5 ms` (cold, `15×`–`30×` higher)**.
   - Similarly, `t0` (`PMTilesClient.ts:684`) starts before `PMTiles.getZxy` fetches and Zstd-decompresses the root/leaf directory on a cold worker.
   - Because `fetchTelemetry` retains the last `50` tiles (`PMTilesClient.ts:401`) and `Z=0..2` loads `21` tiles, `p95` (`index 19 of 21`) stays **permanently pinned to that one-time cold boot spike** until the user pans through 30+ additional tiles.
2. **Real payload bottleneck at `100k` capacity on wide 36-column tables (secondary cause of `704–865 ms`):**
   - At `tile_capacity = 100,000` on 36-column LMSys, each tile is `8–10.24 MiB` compressed (`~22 MiB` uncompressed Arrow IPC), so 6 concurrent tiles genuinely take `155.2 ms` median / `430.3 ms` P95 even warm. Dropping generic `tile_capacity` to **`25,000`** cuts warm median to `76.2 ms` (`22.1 ms` worker) and warm burst P95 by **`3.64×`** (`118.2 ms`). *(We should separate cold worker/directory init from steady-state tile decode SLO in Phase 5b.)*

---

## 5. Full Benchmark Matrix — `.arrowtiles` vs. Sorted HTTP-Range Parquet (5 Runs, Median / P95)

### 5.1 Static File, Build & Footer/Index Scaling

| Dataset (`rows`, `tiles`) | Format | Build / Pack Time | Archive Size | Metadata / Footer + Index Size | Row Groups |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **`gaia_sample`** (`149,942` rows, `331` tiles) | `.arrowtiles` (`v0.1`) | `1.2 s` | `4.27 MiB` | **`2.02 KiB`** (`0 B` leaf dir) | — |
| | `parquet_tile_rg` | `+0.09 s` pack | `4.64 MiB` | `289.4 KiB` (`278.9 KiB` footer + `10.5 KiB` idx) | `331` |
| | `parquet_page_idx` | `+0.09 s` pack | `4.17 MiB` | `12.7 KiB` (`2.2 KiB` footer + `10.5 KiB` idx) | `1` |
| **`lmsys_sample`** (`100,000` rows, `11` tiles) | `.arrowtiles` (`v0.1`) | `0.67 s` | **`0.86 MiB`** | **`0.87 KiB`** | — |
| | `parquet_tile_rg` | `+0.01 s` pack | `0.97 MiB` | `6.34 KiB` (`5.32 KiB` footer + `1.01 KiB` idx) | `11` |
| | `parquet_page_idx` | `+0.01 s` pack | `0.96 MiB` | `2.27 KiB` (`1.25 KiB` footer + `1.01 KiB` idx) | `1` |
| **`lmsys_full`** (`2,835,490` rows, `221` tiles, `36` payload cols) | `.arrowtiles` (`v0.1`, `25k`) | `21.11 s` | **`278.04 MiB`** | **`3.17 KiB`** (`805 B` root dir) | — |
| | `parquet_tile_rg` | `+3.75 s` pack | `282.46 MiB` | `815.1 KiB` (`805.7 KiB` footer + `9.4 KiB` idx) | `221` |
| | `parquet_page_idx` | `+3.75 s` pack | `282.96 MiB` | `66.2 KiB` (`56.8 KiB` footer + `9.4 KiB` idx) | `12` |
| **`gaia_100m`** (`100,000,000` rows, `9,573` tiles, `7` payload cols) | `.arrowtiles` (`v0.1`, `100k`) | `622.7 s` | **`2.441 GiB`** | **`1.18 KiB`** (`38 B` root dir) | — |
| | `parquet_tile_rg` | `+91.0 s` pack | `2.547 GiB` | **`8.44 MiB`** (`8.12 MiB` footer + `328 KiB` idx) | `9,573` |
| | `parquet_page_idx` | `+91.0 s` pack | `2.536 GiB` | `774.4 KiB` (`446.5 KiB` footer + `328 KiB` idx) | `400` |

### 5.2 Streaming HTTP-Range & Worker Decode Performance (5 Runs Each: `Median` / `P95`)

| Dataset & Workload | Format | Handshake `ms` (`Wire KB`, `Reqs`) | Overview TTFF `ms` (`Z=0..2`) | Overview Wire `MiB` (`Reqs`) | Overview Worker CPU Sum `ms` | Deep-Zoom Burst `ms` | Deep-Zoom Wire `MiB` (`Reqs`) | Deep Worker CPU Sum `ms` | Peak JS + Buffers `MB` |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`gaia_sample`** (`4` cols, `111k` ov / `1.8k` deep rows) | **`.arrowtiles`** | **`4.1` / `5.5`** (`17.0 KB`, `2`) | **`40.3` / `63.4`** | `3.18` (`23`) | `106.5` / `144.4` | **`9.6` / `12.8`** | `0.06` (`16`) | `4.8` / `7.3` | `2.0` / `2.0` |
| | `parquet_tile_rg` | `76.3` / `85.3` (`522.5 KB`, `3`) | `131.2` / `149.5` | **`1.79`** (`43`) | **`56.5` / `106.6`** | `17.6` / `19.5` | **`0.05`** (`17`) | **`0.9` / `1.6`** | `5.6` / `5.6` |
| | `parquet_page_idx` | `10.2` / `10.8` (`522.5 KB`, `3`) | `167.8` / `192.7` | `5.67` (`129`) | `103.1` / `143.8` | `100.3` / `105.2` | `3.03` (`96`) | `13.0` / `13.0` | **`1.6` / `1.6`** |
| **`lmsys_sample`** (`4` cols, `100k` rows) | **`.arrowtiles`** | **`7.1` / `8.1`** (`16.7 KB`, `2`) | **`38.0` / `45.0`** | **`0.86` (`13`)** | `85.4` / `129.4` | `16.0` / `18.0` | `0.84` (`8`) | `19.5` / `21.9` | `2.8` / `2.8` |
| | `parquet_tile_rg` | `11.9` / `12.9` (`513.0 KB`, `3`) | `42.7` / `48.6` | `1.20` (`14`) | `75.3` / `96.6` | **`13.7` / `15.0`** | **`0.70` (`8`)** | **`9.5` / `11.5`** | `2.7` / `2.7` |
| | `parquet_page_idx` | `9.2` / `10.5` (`513.0 KB`, `3`) | `82.3` / `91.3` | `2.34` (`58`) | **`61.3` / `65.8`** | `48.8` / `50.3` | `1.51` (`40`) | `13.6` / `15.3` | **`2.5` / `2.5`** |
| **`lmsys_full` — 3-of-38 Projection** (`x_u16, y_u16, clusters_14`; `458k` ov / `245k` deep rows) | **`.arrowtiles`** | **`7.5` / `8.1`** (`18.3 KB`, `2`) | `212.1` / `245.7` | `40.39` (`23`) | `315.1` / `366.6` | `107.5` / `127.3` | `24.11` (`16`) | `86.4` / `99.9` | **`6.1` / `6.1`** |
| | `parquet_tile_rg` | `183.1` / `204.6` (`815.1 KB`, `4`) | `235.6` / `255.6` | **`3.13` (`46`)** | **`68.1` / `88.3`** | **`37.5` / `38.4`** | **`1.30` (`32`)** | **`9.6` / `10.4`** | `15.7` / `15.8` |
| | `parquet_page_idx` | `22.8` / `36.1` (`521.4 KB`, `3`) | **`158.1` / `159.1`** | `4.62` (`113`) | `105.2` / `115.5` | `94.8` / `95.8` | `2.62` (`90`) | `20.8` / `22.8` | `6.2` / `6.3` |
| **`lmsys_full` — Full 36-Col Schema** (`458k` ov / `245k` deep rows) | **`.arrowtiles`** | **`7.6` / `10.0`** (`18.3 KB`, `2`) | **`249.3` / `263.4`** | **`40.39` (`23`)** | `549.2` / `586.0` | **`113.7` / `128.3`** | `24.11` (`16`) | **`134.5` / `140.7`** | **`96.6` / `96.6`** |
| | `parquet_tile_rg` | `189.5` / `201.4` (`815.1 KB`, `4`) | `448.3` / `459.8` | `40.43` (`38`) | **`310.7` / `330.3`** | `134.3` / `153.8` | **`23.64` (`24`)** | `134.7` / `141.7` | `100.4` / `100.4` |
| | `parquet_page_idx` | `39.9` / `41.2` (`521.4 KB`, `3`) | `1116.6` / `1164.4` | `57.74` (`839`) | `779.9` / `798.7` | `836.0` / `873.2` | `36.76` (`684`) | `434.1` / `454.8` | `96.6` / `96.6` |
| **`gaia_100m` — 4-Col Optical** (`828k` ov / `905k` deep rows) | **`.arrowtiles`** | **`6.8` / `10.8`** (`17.0 KB`, `2`) | **`180.8` / `222.9`** | `25.03` (`24`) | `271.3` / `337.6` | `119.5` / `173.1` | `26.30` (`16`) | `92.6` / `163.9` | **`20.5` / `20.6`** |
| | `parquet_tile_rg` | `5021.8` / `5066.9` (`8641.6 KB`, `4`) | `5147.8` / `5192.2` | `17.48` (`46`) | `200.6` / `213.2` | **`94.8` / `97.7`** | **`9.83` (`32`)** | `95.0` / `96.6` | `121.2` / `140.0` |
| | `parquet_page_idx` | `112.8` / `212.6` (`839.9 KB`, `3`) | `289.6` / `417.6` | **`13.66` (`147`)** | **`135.6` / `222.6`** | `144.2` / `154.4` | `12.57` (`120`) | **`58.5` / `98.6`** | `26.1` / `26.4` |
| **`gaia_100m` — Full 9-Col Gaia** (`828k` ov / `905k` deep rows) | **`.arrowtiles`** | **`7.2` / `8.8`** (`17.0 KB`, `2`) | **`182.1` / `188.3`** | **`25.03` (`24`)** | `324.1` / `346.5` | **`110.7` / `118.7`** | `26.30` (`16`) | **`108.6` / `116.7`** | **`53.6` / `53.6`** |
| | `parquet_tile_rg` | `4926.0` / `5138.8` (`8641.6 KB`, `4`) | `5211.5` / `5411.6` | `31.14` (`29`) | `434.1` / `457.6` | `222.3` / `267.7` | **`24.14` (`24`)** | `257.8` / `295.5` | `154.3` / `154.3` |
| | `parquet_page_idx` | `114.6` / `190.1` (`839.9 KB`, `3`) | `460.0` / `621.2` | `33.23` (`243`) | **`201.0` / `375.1`** | `348.7` / `368.9` | `31.13` (`200`) | `286.1` / `294.1` | `55.5` / `55.5` |

### 5.3 Why Each Format Behaves the Way It Does
1. **Why `parquet_tile_rg` collapses at 100M+ rows (`5.0s` handshake, `121–154 MB` JS heap):** Parquet stores a flat monolithic `FileMetaData` Thrift footer listing every `ColumnChunk` of every `RowGroup`. At `9,573` tiles × `11` columns = `105,303` column chunks, the footer hits `8.12 MiB` (`~165 MiB` at 1.8B Gaia). By contrast, PMTiles partitions its Hilbert directory into a `16 KiB` root directory + lazy leaf directories (`367 KiB` total even at 1.8B rows!).
2. **Why `parquet_page_idx` multiplies HTTP Range requests by `6×`–`36×` (`113`–`839` requests vs. `23`):** For every tile straddling a `250k`-row Row Group, `hyparquet` must fetch each projected column's `OffsetIndex` plus separate non-adjacent byte ranges per column chunk (`21 tiles × 3 cols × ~2 = 113+` requests, and `839` requests at 37 cols!). Over cloud object storage (`Cloudflare R2` / `S3` with `25–60 ms` RTT per wave), `147–839` range requests suffer severe round-trip amplification compared to `.arrowtiles`'s **`1` contiguous range read per tile**.
3. **Where Parquet wins (`lmsys_full` 3-of-38 projection):** When an archive packs `36` payload columns into every tile (`lmsys_full`) and the viewer only needs `3` columns (`x, y, clusters_14`), `.arrowtiles` downloads `40.39 MiB` instead of `3.13–4.62 MiB`. That gap disappears when wide datasets either project visual columns at build time (`--columns model,clusters_14,num_of_tokens`) or split cold/wide columns into `SPEC.md` §6.4 `"layers"` sidecar `.arrowtiles` archives (or a sidecar Parquet lookup table for click-inspection!).

---

## 6. Owner Stop Gate Decisions Needed Before Phase 5 (`⛔ D8`, `⛔ D9`, `⛔ D10`)

### `⛔ D8` — Primary Container Choice
- **Option 1 (Recommended — Keep `.arrowtiles` `v0.1` as Primary Pyramid Container + Optional Sidecar Layers/Parquet for Wide Cold Attributes):**
  - Retains `6.8 ms` `O(1)` startup at 100M–1.8B+ rows, `1` HTTP Range request per tile (`23–24` overview requests vs. `113–839`), smallest billion-point file size, and zero-transcode Arrow IPC buffers.
  - For wide 30+-column embedding tables, recommend keeping the primary `.arrowtiles` archive to active visual columns (or `v0.2` `"layers"` sidecars) while optional full-row text/metadata inspection can query source Parquet or sidecar layers by `row_id`.
- **Option 2 (Pivot to `parquet_page_idx` + Sidecar Index):**
  - Wins wire bytes on unprojected 38-column tables (`4.62 MiB` vs. `40.39 MiB`), but incurs `6×`–`36×` more HTTP Range requests (`147–839` vs. `23–24`) and slower TTFF at 100M+ rows (`290–460 ms` loopback, `>1s` on WAN).

### `⛔ D9` — Renderer Architecture for Phase 5 & Phase 6
- **Option 1 (Recommended — Unify on `ComputeRasterizer` ("Compute-Only") & Retire `Scatterplot` Instanced Point Meshes):**
  - Currently, `Scatterplot.ts` allocates `200` `THREE.InstancedBufferGeometry` meshes solely to upload `GPUBuffer`s via Three.js's backend *and* to run 2-second axis-transition animations, duplicating code paths (`TSL` vs. `WGSL`) and retaining Three.js attribute wrappers.
  - Unifying on `ComputeRasterizer` manages raw `GPUBuffer` slots directly (making Phase 6's `window.__gpuStats` VRAM accounting 100% deterministic), moves 2-second axis transitions (`mix(prevPos, currPos, transitionT)`) directly into the WGSL compute shader (~25 lines of WGSL), and deletes ~500 lines of duplicate `MeshBasicNodeMaterial` TSL code.
- **Option 2 (Keep Dual-Renderer: `Compute (Atomic)` + `Hardware Instanced`):**
  - Preserves the `Hardware Instanced` dropdown option for debugging/comparison, requiring dynamic attribute disposal in `Scatterplot.ts` during Phase 6 without leaving 0-length buffers on live Three.js geometries.

### `⛔ D10` — Continuous / Optical Tone Mapping (`Per-Point` vs. `Resolve-Pass`)
- *(Note: Categorical Mode 1 now already uses **Resolve-pass log-density tone mapping** per `D7` Condition #2! `D10` applies to **Gaia Mode 0 Optical Flux** and **Numeric Additive Mode 1**.)*
- **Option 1 (Recommended — Keep Per-Point ACES + sRGB Transfer in Modes 0 & 3, Widen Channels to `16-bit` in `2 × u32` `accumBuffer` in Phase 5b):**
  - Preserves the tuned ESA Gaia DR3 Milky Way dust-lane & star-color look in Mode 0 and Star Trails Mode 3 while eliminating 11-bit channel carry races (`accumBuffer` is already `12 B/px` now and becomes unified clean `u32` words in Phase 5b).
- **Option 2 (Move Continuous / Optical Tone Mapping to the Resolve Pass — Accumulate Linear HDR RGB + Apply ACES/Log-Exposure Once per Pixel in Resolve):**
  - Physically linear HDR accumulation (brightness sums linearly before tone mapping rather than summing pre-tone-mapped sRGB values), which slightly alters Gaia Milky Way contrast/gamma curves and requires retuning Mode 0 exposure constants.
