---
log_id: 2026-11-19_01
date: 2026-11-19
type: RESEARCH
status: approved
scope: [all]
source_artifact: deep_review_and_research_2026_11_19.md
conversation_id: fe52eab7-65ce-45dd-8140-b03acd621444
---

# Deep Research: ArrowTiles Format Positioning, Ecosystem & Technical Trade-Offs

## 1. Strategic Gap Verification
Research across current (2025–2026) point-cloud and embedding visualization systems confirms that no permissively specified, single-file HTTP range-request format occupies the intersection of:
1. **Arbitrary columnar attributes** (Apache Arrow IPC zero-copy typed arrays),
2. **Abstract 2D coordinates** (embeddings, UMAP/t-SNE, HR diagrams — not restricted to geographic lon/lat),
3. **Hierarchical out-of-core Level-of-Detail (LOD)** with guaranteed completeness and explicit priority/sampling semantics,
4. **Single-file static hosting** over standard CDN HTTP `206 Partial Content` range requests,
5. **SQL-native authoring** via DuckDB.

| Neighbor System | Architecture | Verified Limitation vs. ArrowTiles |
| :--- | :--- | :--- |
| **Quadfeather / Deepscatter** | Directory tree of thousands of `.feather` files + WebGL renderer | **CC BY-NC-SA 4.0** (viral + non-commercial); 10k–100k separate S3 objects & HTTP requests; C++ build friction. |
| **Apple Embedding Atlas** | WebGPU + OIT + GPU KDE contours + DuckDB-WASM cross-filtering | Flat client-side load; excels up to ~2–5M points in RAM, not a hierarchical out-of-core tiled format for 100M–1.8B points. |
| **luma.gl / Deck.gl Point Clouds** | WebGPU / WebGL2 GPU renderers | Rendering libraries rather than a self-describing, single-file multi-zoom point container. |
| **COPC (Cloud Optimized Point Cloud)** | Octree-organized LAZ 1.4 | Strictly LiDAR point records (fixed LAS point formats), not general relational/embedding Arrow schemas. |
| **MapLibre MLT (Mapbox Vector Tile successor)** | Columnar vector tiles inside PMTiles | Polygon/linestring/point cartographic vector features clipped per tile, not billion-row lossless priority-sampled point tables. |

## 2. PMTiles v3 Specification Alignment ("COPC for Arrow Point Pyramids")
- **Header (127 bytes):** `tile_type = 0x00` (`Unknown`) is explicitly reserved in PMTiles v3 for custom binary tile payloads. `tile_compression = 0x04` (`Zstd`) is standard in v3.
- **Metadata Block:** PMTiles v3 lifted v2's 300 KB metadata ceiling; arbitrary-size compressed JSON metadata is supported via `jsonMetadataOffset` and `jsonMetadataLength`.
- **Directory Scaling:** Root directory fits inside the initial 16 KiB fetch; leaf directories for 193,246 tiles in `gaia_full.arrowtiles` occupy ~367 KB total (which `FastFetchSource` in `PMTilesClient.ts` prefetches in one range request, eliminating all secondary directory round-trips).

## 3. Preview of Phase 4: `.arrowtiles` vs. Tile-Sorted Single Parquet (`parquet-wasm` / `hyparquet`)
Literature and implementation analysis identify three quantitative axes that Phase 4's benchmark must test across **small (<20 MB)**, **medium (~2.8M rows)**, and **large (≥100M rows)** scales:
1. **Footer Scaling Overhead:** Parquet stores per-row-group, per-column `ColumnChunk` + `ColumnMetaData` Thrift structures in the file footer. At 100,000–200,000 tiles (one row group per tile) × 8–10 columns, the Parquet footer contains ~1–2M column chunk descriptors (tens to >100 MB of footer bytes) vs. PMTiles' compact delta+varint+RLE Hilbert directory (~367 KB for 193k tiles).
2. **Contiguous Row-Group Fetch vs. Column Projection:**
   - Fetching an entire row group in Parquet is 1 range request (matching PMTiles' 1 range request per tile), whereas fetching *k* of *M* columns requires *k* disjoint byte-range requests per tile (multiplying HTTP request concurrency pressure).
   - Conversely, when *M* is wide (e.g., 38 columns in raw LMSys) and only 3 columns (`x, y, color`) are viewed, Parquet column projection avoids transferring unused columns — a trade-off directly relevant to ArrowTiles' future "Core + Auxiliary Layers" roadmap.
3. **Decode Path Overhead:** Schema-stripped Zstd Arrow IPC maps directly into contiguous Arrow buffers (`tableFromIPC([schema, tileBytes])`) without reparsing Parquet page headers, repetition/definition levels, or Thrift row-group metadata per tile.

## 4. Three.js WebGPU (`r172`) Storage/Vertex Buffer Lifecycle Findings
- Reaching into `(renderer as any).backend.get(attribute)` in `WebGPUAdapter.ts` bypasses Three.js's internal `WebGPUBackend` attribute lifecycle tracking when `attrData.buffer` is manually allocated via `device.createBuffer(...)`.
- Replacing `geo.setAttribute(col, newAttr)` or calling `clearAllTiles()` without calling `gpuBuffer.destroy()` orphans VRAM allocations on the `GPUDevice`.
- Furthermore, instantiating `new Float32Array(262144)` on every `InstancedBufferAttribute` allocates 1 MiB of unused CPU TypedArray backing store per column per slot when `writeToDeviceQueue` writes straight to `GPUBuffer`.
