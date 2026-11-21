---
log_id: 2026-11-20_04
date: 2026-11-20
type: WALKTHROUGH
status: executed
scope: [all]
source_artifact: none
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Phase 5b Walkthrough — Compute-Only Direct `GPUBuffer` Pipeline (`D9`), Race-Free `2 × u32` Split-by-Mode Shaders (`D10`), CPU `Float64` `RTC` Deep Zoom, and Public API Lock (`D11`)

## 1. Summary of Changes

### A. Viewer Repository (`deepgraph-arrowtiles-sandbox`)
1. **Public API Lock & Phase 5a Review Refinements (`docs/API.md`, `src/index.ts`, `src/lib/types.ts`, `src/lib/ViewState.ts`, `src/lib/ViewerLayer.ts`, `src/lib/diagnostics.ts`, `src/main.ts`):**
   - Sealed `src/index.ts` to export **only** `Deepgraph` (`create`, `isSupported`) and public TypeScript interfaces (`0` internal class exports; workspace diagnostic hooks isolated behind an unexported `INTERNAL_DIAGNOSTICS` `Symbol` in `src/lib/diagnostics.ts`).
   - Hid internal `x_u16` / `y_u16` column identifiers from the public API (`xField: string | null`, `yField: string | null`), honored custom `{ domain, range, transform }` on `encoding.x` and `encoding.y`, separated Cartesian chart-column `flipY` range orientation from top-down `y_u16` orientation (fixing HR Diagram `flipY: true` so bright `M_G = 3` stars render at the top), and supported `setEncoding({ x: null, y: null })` to reset back to spatial positions.
   - Moved astronomy/flow domain options (`esa_*` scales, `'trails'` / `'streamlines'`, `metricType`, `auxFields`, `magnitudeFields`, `opticalColorField`, `legacyFlipY`, `trailMode`, `trailTimeKyr`, `minParallax`, `animateFlow`) into `ExperimentalOptions`, supported a `preset` resolver function `(rawMetadata, source) => DeepgraphPreset | undefined`, renamed `gaiaMagField` -> `magnitudeField`, converted `getViewport()` / `setViewport()` to **data coordinates**, added `plot.fitView()`, hardened URL sanitization with `!queryFile.includes('\\')`, and guarded mid-flight `load()` against concurrent `destroy()` or superseded `load()` calls.
2. **Unused Dependency & Legacy Dual-Renderer Removal (`package.json`, `src/`, `tests/`):**
   - Removed 6 confirmed-unused dependencies (`@sentry/browser`, `@sentry/tracing`, `gl-matrix`, `@types/gl-matrix`, `stats.js`, `@types/stats.js`) and 3 dead files (`src/counter.ts`, `src/ui.ts`, `tests/compute_test.mjs`).
   - Retired `src/Scatterplot.ts` (`THREE.InstancedBufferGeometry` + `MeshBasicNodeMaterial`) and `src/WebGPUAdapter.ts` (`renderer.backend.get` private internals).
3. **`D9` Direct `GPUBuffer` Store & 2-Second WGSL Axis Transitions (`src/core/TileGpuStore.ts`, `src/core/ComputeRasterizer.ts`, `src/core/Renderer.ts`):**
   - Implemented `TileGpuStore` owning exact-sized per-tile, per-column `GPUBuffer`s directly on `GPUDevice` (reducing active tile VRAM on 21-tile `0.46M`-point LMSys from `>300 MB` pre-allocated instanced geometry to **`5.2 MB`**) with full `dispose()` cleanup across `TileGpuStore` and `ComputeRasterizer`.
   - Moved 2-second smoothstep axis transitions (`mix(prevRelPos, currRelPos, transitionT)`) into `ComputeRasterizer.ts` while keeping `@compute` bindings within the universal WebGPU baseline (`2` uniform buffers + `8` storage buffers by moving the 64-color categorical palette to a `256 B` uniform buffer).
   - Fixed `computeSlotMagBins` (`Number.isFinite(m)`) so bright stars with `M_G <= 0` map into bin `0` (`F-12`), added CPU `Float64` Relative-to-Center (`RTC`) deep-zoom projection (`F-07`), clamped `zoomT` to `[0, 1]`, and guarded `cpy < u.screenHeight` in Mode 4 streamline seeding.
4. **`D10` Unified `2 × u32` (`8 B/px`) Race-Free Split-by-Mode Accumulation (`src/core/ComputeRasterizer.ts`):**
   - Unified `accumBuffer` at `2 × u32` (`8 B/px` = `112.5 MiB` at `5120×2880` 5K Retina `< 128 MiB` WebGPU baseline limit):
     - **Modes 0 & 3:** `16-bit` fixed-point RGB (`word0 = R16 | G16<<16`, `word1 = B16`, scale `1024.0`) with per-point ACES + sRGB.
     - **Mode 1 (Both Categorical & Generic Numeric Points):** `word0 = atomicAdd(&accumBuf[base2], w)` (`prevW`), `word1 = R10 | G10<<10 | B10<<20` strictly interval-gated on `prevW < 64u` (`wRgb = min(w, 64u - prevW)` -> max channel sum `64 * 15 = 960 < 1024`, zero TOCTOU race and zero 10-bit carry), resolved with `log2(1 + count)` brightness + mean RGB.
     - **Modes 2 & 4:** Separated `valSum_u32` (`word0`) from `weightSum` (`word1`), eliminating `16-bit` carry corruption.
5. **Streaming Worker, Zero Duplicate CPU Retention & Retry Hardening (`src/PMTilesClient.ts`, `src/pmtiles.worker.ts`, `src/demo/ControlsPanel.ts`):**
   - Eagerly compiled `zstd.wasm` on worker startup, consolidated `DatasetSession.open()` onto a single `PMTiles` instance, invoked `onTileUnloaded` before recycling buffers in `setRequestedColumns()` (`F-09`), released CPU `tile.columns` immediately after GPU upload (`0` retained CPU column arrays on uploaded tiles), separated `coldBootMs` from steady-state `steadyTotals`, added exponential retry backoff + 4-attempt negative caching, and synced the categorical legend automatically when `color` changes via `plot.setEncoding()`.

### B. Writer Repository (`duckdb-arrowtiles`)
- Tracked `overview_compressed_bytes` (`z <= 2`) in `arrowtiles-engine/src/lib.rs`, emitted a build-time warning in `arrowtiles/builder.py` when `Z=0..2` overview bytes exceed `10 MiB` recommending `--columns`, emitted a non-fatal notice when `--id-col > 2^53 - 1`, documented `--columns` prominently in `README.md`, and added `test_overview_bytes_warning_and_uint64_large_id_col` in `tests/test_phase3_priority_and_presets.py`.

---

## 2. Verification Evidence

| Check | Command / Probe | Result |
| :--- | :--- | :--- |
| Writer test suite | `.venv\Scripts\python.exe -m pytest -v -rs -p no:cacheprovider` | **PASS** — `50 passed, 1 skipped` |
| Viewer typecheck & build | `npm run typecheck` + `npm run build` | **PASS** — `0` TS errors; Vite production bundle built cleanly (`172` modules) |
| Retired symbol & `D11` boundary grep | Grep across `src/**/*.ts` and `src/lib/*.ts` | **PASS** — `0` retired symbols (`Scatterplot`, `WebGPUAdapter`, `backend.get`, `gaiaMagField`, `RenderEngineMode`); `0` DOM/GUI/URL violations in `src/lib/` |
| Sealed barrel & mid-flight `load()+destroy()` race | `verify_phase5b.mjs` Checks 1 & 2 | **PASS** — `exportedKeys: ["Deepgraph"]`, `isSupported() === true`, `lilGuiInDom === 0`, mid-flight `load()+destroy()` rejected cleanly with `0` lingering `<canvas>` nodes |
| URL sanitization (`//` and `/\`) | `verify_phase5b.mjs` Check 3 | **PASS** — Both `?file=//...` and `?file=/%5C...` fell back safely to `/gaia_full.arrowtiles` |
| `gaia_full` Modes `0, 2, 3, 4` + `M_G <= 0` fix | `verify_phase5b.mjs` Check 4 | **PASS** — Mode 0 (`490,625` lit px, `whiteRatio = 0.00098`), negative/zero magnitudes `[-1.46, 0.0]` retained in `bin 0` (`bin0Count === 2`), Modes `2/3/4` `0` WebGPU validation errors |
| `gaia_sample` 2s WGSL transition, `{ domain, range }`, `x: null` reset, data-coord viewport & `RTC` `zoom = 131,072` | `verify_phase5b.mjs` Checks 5–7 | **PASS** — Custom `x`/`y` domains & flipped HR `y.range = [1.6, -1.6]` honored; `transitionT = 0.081 -> 1.0`; `x: null` reset hid `x_u16`/`y_u16`; exact data-coord `getViewport`/`setViewport` round-trip; `zoom = 131,072` `0` validation errors |
| `lmsys_d7_proportional_25k` Mode 1 (categorical + numeric), lazy cols & `0` CPU retention | `verify_phase5b.mjs` Check 8 | **PASS** — Categorical `clusters_14` & numeric `num_of_tokens` at `240 FPS`, `0.1 ms` render, `5.2 MB` active tile VRAM, `3` of `36` active cols requested, `0` retained CPU column arrays across `21` uploaded tiles |
