---
log_id: 2026-11-21_02
date: 2026-11-21
type: WALKTHROUGH
status: executed
scope: [all]
source_artifact: none
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Phase 7 Walkthrough — Library-Clean `gpuStats` Isolation, `0.0000%`-Shimmer Numeric Mode 1, Race-Free `1 KB` GPU `PickingLayer`, Standalone `.arrowtiles` `row_id` Decode & `HighlightOverlay`

## 1. Summary of Changes

1. **Pre-Phase-7 Library Hygiene Fix (`src/demo/gpuStats.ts`, `src/core/Renderer.ts`, `src/lib/RenderLoop.ts`):**
   - Moved `gpuStats.ts` from `src/core/` to `src/demo/gpuStats.ts` so `Deepgraph` never monkey-patches `GPUAdapter` / `GPUDevice` / `GPUBuffer` prototypes or writes `globalThis.__gpuStats` on host pages (`0` matches across `src/lib/`, `src/core/`, and `src/index.ts`; verified live via `winGpuStatsDefined === false` & `createBufferUnpatched === true`).
   - Computed `TelemetrySnapshot.totalGpuMB` directly from library-owned byte accounting (`TileGpuStore + ComputeRasterizer + PickingLayer + HighlightOverlay`).
2. **Option B GPU Coexistence (`DeepgraphOptions.powerPreference`):**
   - Added `powerPreference?: 'high-performance' | 'low-power'` to `DeepgraphOptions` (`docs/API.md`, `src/lib/types.ts`, `src/core/Renderer.ts`), `--force_low_power_gpu` in `playwright.config.ts`, and an explicit `adapter.info.vendor === 'intel'` pre-check before `requestDevice()` in `tests/picking-layer.spec.ts` using `< 5 MiB` `gaia_sample` and `lmsys_sample` only (`0 B` on discrete RTX 5090).
3. **Zero-Shimmer `1,024`-Level Scalar Value-Sum for Numeric Mode 1 (`src/core/ComputeRasterizer.ts`, `docs/API.md`):**
   - Replaced the `16 × 63` RGB sum in numeric Mode 1 (`!isCat`) with an order-independent scalar value sum `word1 = Σ(tU * wVal)` (`tU` in `0..1023`, gated at `prevW < 1048576u`, `1,048,576 × 1,023 < 2^32`) and evaluated `eval_ramp(meanT, scaleId)` × `log2(1 + count)` in `fs_main` (`0 / 131,028` changed pixels = **`0.0000%` stationary shimmer**), while keeping `64 × 15` for categorical Mode 1.
4. **Race-Free `1 KB` GPU `PickingLayer`, Standalone `.arrowtiles` Decode & `HighlightOverlay` (`src/core/PickingLayer.ts`, `src/core/HighlightOverlay.ts`, `src/pmtiles.worker.ts`, `src/PMTilesClient.ts`, `src/lib/ViewerLayer.ts`, `src/demo/ControlsPanel.ts`):**
   - `< 4.0 CSS px` pointer-travel click gate in `Renderer.ts` + `45 ms`-throttled `'hover'` (active only when `'hover'` listeners exist) + `plot.pickAt(cssX, cssY)`.
   - Dedicated `@compute` picking pipeline (`1` dynamic uniform + `8` storage buffers, `0 B` per-frame pan/zoom overhead) writing `(dist16th_u12 << 20u) | localRowIdx_u20` via `atomicMin` into a `1,056 B` (`~1 KB`) `slotBestHit` buffer over a `9 × 9 CSS px` cursor window, with automatic multi-chunk fallback for oversize leaves `> 1,048,575` rows.
   - Priority-aware cross-slot tie-breaking (coarser `z` first, `rawRowIdx` second) + on-demand `decode_row` in `pmtiles.worker.ts` (`rowId: number`, lossless `rowIdBigInt?: bigint` when `> 2^53 - 1`, decoded categorical string labels, `NULL -> null`, `0 MB` idle worker RAM, optional `resolveRowAttributes` hook).
   - Plain-WebGPU `HighlightOverlay` (`loadOp: 'load'` dual-contrast cyan hover & gold selection rings tracking pan/zoom/2s transitions) + deterministic `GPUBuffer.destroy()` cleanup on `plot.destroy()`.

---

## 2. Verification Evidence

| Check | Command / Probe | Result |
| :--- | :--- | :--- |
| Typecheck, `.d.ts` check & build | `npm run typecheck` + `npx tsc --noEmit --declaration` + `npm run build` | **PASS** — `0` TS/`.d.ts` errors; `399.12 kB` (`102.46 kB` gzip) built in `262 ms` |
| Library hygiene proof (static + live) | Grep across `src/lib/`, `src/core/`, `src/index.ts` + Step 1 in `picking-layer.spec.ts` | **PASS** — `0` matches; `winGpuStatsDefined === false`, `createBufferUnpatched === true` |
| Intel iGPU coexistence pre-check | Step 0 in `tests/picking-layer.spec.ts` | **PASS** — `vendor === 'intel'` (`xe-lpg`) verified before `requestDevice()`; `< 5 MiB` samples only (`0 B` on RTX 5090) |
| Numeric Mode 1 stationary shimmer | Step 2 in `tests/picking-layer.spec.ts` (`lmsys_sample` `num_of_tokens`) | **PASS** — **`0 / 131,028` lit pixels changed (`0.0000%`, `maxDelta = 0`)** |
| Drag vs. click gate (`< 4 CSS px`) | Step 3a in `tests/picking-layer.spec.ts` | **PASS** — `40 × 25 px` drag emitted `0` clicks; stationary click emitted `'click'` + `'select'` |
| `ArrowTilesReader` parity (`lmsys_sample` & `gaia_sample`) | Steps 3b & 4a–4c in `tests/picking-layer.spec.ts` | **PASS** — Exact `rowId`, `dataX`/`dataY` (`< 1e-9`), categorical `model` strings (`"mixtral"`, `"llama-3"`, `"gpt-4"`), `NULL -> null`, `'hover'`, and HR Diagram (`rowId = 14301`) |
| `HighlightOverlay`, tie-break, oversize leaf, `BigInt` & `destroy()` | Steps 3c & 5 in `tests/picking-layer.spec.ts` | **PASS** — `140` gold ring px (cleared on empty click); `0/0/0` beat `1/1/1`; `1,060,000`-row leaf picked `1,055,000`; `5900000000000000123n` preserved; `17,021,320 / 17,021,320 B` & `2 / 2` devices freed (`0` leaks) |
