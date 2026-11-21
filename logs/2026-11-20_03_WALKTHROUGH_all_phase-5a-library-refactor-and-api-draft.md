---
log_id: 2026-11-20_03
date: 2026-11-20
type: WALKTHROUGH
status: executed
scope: [all]
source_artifact: API.md
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Phase 5a & Pre-5a Follow-Ups Walkthrough — Locked `D8`/`D9`/`D10`, Throttled WAN Benchmark, Embeddable Library Split (`D11`) & `docs/API.md` Draft

## 1. Summary of Changes

### A. `duckdb-arrowtiles` (Pre-Phase-5a Follow-Ups + Locked `D8`/`D9`/`D10`)
1. **Locked Decisions Recorded (`05_PLAN`, `SPEC.md`, `BENCHMARK_parquet_vs_arrowtiles.md`):**
   - **`D8`:** Kept `.arrowtiles` (`v0.1`) as the primary pyramid container; elevated multi-archive column-group `"layers"` sidecars to a **required `v0.2` roadmap item** in [`docs/SPEC.md`](../docs/SPEC.md) §6.4; documented standalone `.arrowtiles` `row_id` + retained-column Phase 7 picking with optional `resolveRowAttributes` sidecar hook.
   - **`D9`:** Locked **Compute-Only** for Phase 5b (retiring `Scatterplot` Three.js instanced point meshes & `WebGPUAdapter.ts`, owning `GPUBuffer`s directly, moving 2s axis transitions into WGSL, and adding a plain-WebGPU point highlight overlay in Phase 7/8).
   - **`D10`:** Locked **Split-by-Mode** for Phase 5b (per-point ACES+sRGB scoped to Gaia optical Modes 0 & 3; generic numeric Mode 1 moved to Resolve-pass log-density tone mapping; race-free interval-gated `prevW = atomicAdd(&accumBuf[base2], w)` in `2 × u32` `8 B/px` `accumBuffer` + adapter `maxStorageBufferBindingSize`).
2. **Sparse `UTINYINT` / `USMALLINT` `--categorical-cols` Fix ([`arrowtiles/builder.py`](../arrowtiles/builder.py#L496)):**
   - Always joins `cat_lookup_tables` whenever `col in cat_lookup_tables`, fixing sparse/1-based unsigned integer category IDs (`[10, 20, 30]`, `[100, 250, 1000]`) so they remap to dense `0..K-1` codes and pass `validate_file`. Verified by `test_sparse_utinyint_usmallint_categorical_cols` (`49 passed, 1 skipped`).
3. **Committed Benchmark Harness ([`scripts/bench/`](../scripts/bench/)) & Throttled WAN `lmsys_full` Run (`50 ms` RTT, `50 Mbps`):**
   - Added portable CLI flags (`--only`, `--runs`, `--throttle-50mbps`, `--out`) to `build_phase4_datasets.py` and `run_phase4_browser_bench.mjs` (`scripts/bench/node_modules/` gitignored).
   - Ran 5-iteration Chrome CDP throttled (`50 ms` RTT, `50 Mbps`) benchmark on `lmsys_full` (`proj_3_of_38` & `full_schema_36`), appended Section `5.4` to [`docs/BENCHMARK_parquet_vs_arrowtiles.md`](../docs/BENCHMARK_parquet_vs_arrowtiles.md), and cleaned up `samples/_tmp_phase4_parquet_bench/`.

### B. `deepgraph-arrowtiles-sandbox` (Phase 5a Pure Structural Refactor + `D11` Library Boundary + `docs/API.md`)
1. **Library Modules (`src/lib/` + `src/index.ts` — Zero Behavior Change, Domain-Agnostic, DOM/GUI/URL-Free):**
   - `src/lib/types.ts`: Public TypeScript interfaces (`DeepgraphOptions`, `DeepgraphPlot`, `DeepgraphEncoding`, `DeepgraphPreset`, `DatasetMetadataSummary`, `TelemetrySnapshot`, `PointHitEvent`, `RowAttributeResolver`) with zero leaked `THREE.*` types.
   - `src/lib/DatasetSession.ts`: Format/version validation (`v0.1` + legacy `v0.0`), `bounds` aspect-ratio math, `stats` + `categories` extraction, discrete `[0..255]` integer cluster inference, and `PMTilesClient` lifecycle.
   - `src/lib/ViewState.ts`: Canonical state & declarative `applyEncoding` / `patch`, exposing a single `effectiveFlipY` getter (`pipeline === 'optical' ? false : flipY`) driving both `PMTilesClient.getVisibleTiles` and `Scatterplot` `yRange`.
   - `src/lib/RenderLoop.ts`: Frame loop, camera frustum culling, active-tile upload, `ComputeRasterizer` / `Renderer` dispatch, and 250 ms structured `TelemetrySnapshot` callbacks (zero DOM touches).
   - `src/lib/ViewerLayer.ts` & `src/index.ts`: Public `Deepgraph.create(container, options)` facade (`load`, `setEncoding`, `getEncoding`, `setViewOptions`, `getViewState`, `getMetadata`, `getCategories`, `getCategoryColorHex`, `getViewport`, `setViewport`, `on`/`off`, `destroy`), plus `ResizeObserver` & listener cleanup in `Renderer.dispose()`.
2. **Demo App Modules (`src/demo/` + `src/main.ts` = `112` lines):**
   - `src/demo/gaiaPreset.ts`: `GAIA_DEMO_PRESET`, `GAIA_FALLBACK_STATS`, and all 12 `GAIA_SCIENCE_LENS_NAMES` builders.
   - `src/demo/ControlsPanel.ts`: `lil-gui` folders, `renderCategoricalLegend`, and `TelemetryHud` (`#ui-metrics`, `#copy-metrics-btn`).
   - `src/main.ts` (`112` lines): Safe `?file=` parsing (including `!queryFile.startsWith('//')` protocol-relative URL guard), drag-and-drop loader, and `window.__viewer` test handle.
3. **Drafted Public API Spec (`docs/API.md`):**
   - Documented factory options, declarative encodings, instance methods, events (`load`, `dictionaries`, `telemetry`, `error`, plus Phase 7 `click` / `hover` / `select` & `resolveRowAttributes`), domain presets, and Phase 5b–8 evolution notes.

---

## 2. Verification Summary

| Check | Result |
| :--- | :--- |
| `duckdb-arrowtiles` `pytest` | **`49 passed, 1 skipped in 10.94s`** |
| Throttled WAN (`50 ms` RTT, `50 Mbps`) `lmsys_full` | `proj_3_of_38`: `parquet_tile_rg` `1,322.5 ms` beats `parquet_page_idx` `1,901.7 ms` (`113` reqs) vs. monolithic 36-col `.arrowtiles` `7,223.3 ms`; `full_schema_36`: `.arrowtiles` **`7,238.9 ms` (`154.7 ms` HS)** vs. `parquet_tile_rg` `7,401.0 ms` (`523.9 ms` HS) and `parquet_page_idx` `16,151.9 ms` (`839` reqs) |
| `src/main.ts` line count | **`112` lines** (`< 150` target) |
| `D11` prohibited-symbol grep in `src/lib/*` & `src/index.ts` | **`0` matches** (`lil-gui`, `window.location`, `URLSearchParams`, `getElementById`, `querySelector`, `document.body`, Gaia strings) |
| `npm run typecheck` & `npm run build` | **`exit code 0`** |
| Headed Chrome WebGPU (`verify_phase5a.mjs`) | **`0` console/page errors** across `gaia_full` (`v0.0` + `?file=//` guard), `gaia_sample` (`v0.1` + HR/Sky `effectiveFlipY`), `lmsys_sample`, `lmsys_d7_proportional_25k` (`clusters_14`), and standalone `640x480` `Deepgraph.create()` + `destroy()` (`lilGuiInDom: 0`, `canvasCountAfter: 0`) |
