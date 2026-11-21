---
log_id: 2026-11-21_01
date: 2026-11-21
type: WALKTHROUGH
status: executed
scope: [all]
source_artifact: none
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Phase 6 Walkthrough — Complete Three.js Removal (`D9`), `64`-Level Numeric Log-Density Precision, Superseded `load()` `AbortError`, and Real-GPU `__gpuStats` Lifecycle Gate

## 1. Summary of Changes

### A. Viewer Repository (`deepgraph-arrowtiles-sandbox`)
1. **Complete Three.js Removal & Native `GPUDevice` Ownership (`D9` Finished):**
   - Removed `three` and `@types/three` from `package.json` (`devDependencies` declares `@webgpu/types`), cutting the minified production JS bundle by **64.4%** (`1,024.89 kB` / `274.74 kB` gzip -> **`364.78 kB` / `94.09 kB` gzip**) and reducing `npm run build` time to **`258 ms`** (`copyPublicDir: false` in `vite.config.ts`).
   - Rewrote `src/core/Renderer.ts` in pure native WebGPU: directly owns `<canvas>` (`touch-action: none`), `navigator.gpu.requestAdapter()` / `adapter.requestDevice({ requiredLimits })`, `GPUCanvasContext` (`configure` / `unconfigure`), pure `Float64` `Camera2D` + pointer-capture drag pan (`pointerdown`/`move`/`up`/`cancel`/`lostpointercapture`) + wheel zoom-to-cursor, and `requestAnimationFrame`.
   - Eliminated all `renderer.backend.device` access; `plot.destroy()` synchronously unconfigures the swapchain context and calls `device.destroy()`.
   - Added explicit `DeepgraphStatic` interface annotation on `export const Deepgraph: DeepgraphStatic` (`npx tsc --noEmit --declaration` exits `0`).
2. **Phase 5b Review Polish & Committed Harness:**
   - **Superseded `load()` (`AbortError`):** `ViewerLayer.load()` rejects superseded in-flight loads (`gen !== this.loadGeneration && !this.destroyed`) with `new DOMException('Dataset load superseded', 'AbortError')`; `src/main.ts` ignores `AbortError` cleanly.
   - **Mode 1 `64`-Level Numeric Color Precision (`16 × 63 = 1,008 < 1,024`):** Kept `64 × 15 = 960 < 1,024` for categorical Mode 1 and upgraded numeric Mode 1 to `16 × 63 = 1,008 < 1,024` (`64` levels/channel = `4×` smoother gradients at `0` extra memory and `0` carry); updated `docs/API.md`.
   - **Committed `scripts/verify_phase5b.mjs`:** Checked in under `deepgraph-arrowtiles-sandbox/scripts/verify_phase5b.mjs` for reproducible Phase 5b verification.
3. **Phase 6 Real-GPU `__gpuStats` & CPU-Buffer Lifecycle Suite (`src/core/gpuStats.ts`, `playwright.config.ts`, `tests/gpu-vram-lifecycle.spec.ts`):**
   - Instrumented `GPUAdapter.prototype.requestDevice`, `GPUDevice.prototype.destroy`, `GPUDevice.prototype.createBuffer`, and `GPUBuffer.prototype.destroy` -> `window.__gpuStats`, plus `PMTilesClient.getCpuMemoryStats()` and HUD `totalGpuMB`.
   - Updated `playwright.config.ts` to run headed real-GPU Chrome (`channel: 'chrome'`, removing legacy `--use-angle=swiftshader`, isolated on `127.0.0.1:5179`) and authored the 5-gate `tests/gpu-vram-lifecycle.spec.ts` suite.

### B. Writer Repository (`duckdb-arrowtiles`)
- Updated `arrowtiles/__main__.py` (`nargs="+"` + `_flatten_column_args`) so `--columns` and `--categorical-cols` accept space-separated (`README.md:89`), comma-separated, and mixed tokens, covered by `test_cli_columns_and_categorical_cols_space_and_comma_syntax` (`51 passed, 1 skipped`).

---

## 2. Verification Evidence

| Check | Command / Probe | Result |
| :--- | :--- | :--- |
| Writer `pytest` suite | `.venv\Scripts\python.exe -m pytest -v -rs -p no:cacheprovider` | **PASS** — `51 passed, 1 skipped in 12.43s` |
| Viewer typecheck, `.d.ts` check & Three.js grep | `npm run typecheck` + `npx tsc --noEmit --declaration` + `three`/`.backend` grep | **PASS** — `0` TS errors; `0` `.d.ts` errors; `0` Three.js/backend references |
| Production bundle build | `npm run build` | **PASS** — `364.78 kB` (`94.09 kB` gzip, `-64.4%` vs. Three.js) in `258 ms` |
| Committed Phase 5b harness | `node scripts/verify_phase5b.mjs` | **PASS** — `exit code 0` across all 8 checks + `AbortError` + post-`destroy()` `0` live bytes/devices |
| Gate 1: Real GPU, `>=20` tiles, pointer/wheel & stability | `npm run test:e2e` (`gpu-vram-lifecycle.spec.ts`) | **PASS** — Intel `xe-lpg` (`isFallbackAdapter: false`), `69` tiles / `15.60M` stars, bit-exact wheel zoom-to-cursor (`0.0` anchor error), stationary shimmer `0.0040%` (`gaia_full` Mode 0), `0.0704%` (LMSys cat), `1.1475%` (LMSys `64`-level num) |
| Gate 2: Deep-zoom LRU eviction plateau (`maxTileCache = 40`) | `npm run test:e2e` (`289` unique `Z >= 3` tiles visited) | **PASS** — Cache pinned at `40` (`160` tile buffers, `144.88 -> 104.73 MB` plateau, `1,084` buffers destroyed, `0 B` retained tile CPU arrays); `1,094,363,344 / 1,094,363,344 B` freed on `destroy()` |
| Gate 3: Superseded `load()` `AbortError` + `5×` dataset swaps | `npm run test:e2e` (`lmsys_sample` ↔ `gaia_sample` × 5) | **PASS** — `AbortError` verified; exact `1,334,628 B` (`67` buffers) on every round (`0`-byte drift) |
| Gate 4: `20×` `Deepgraph.create()` + `plot.destroy()` loop | `npm run test:e2e` | **PASS** — `20 / 20` `GPUDevice`s destroyed, `1,224,723,524 / 1,224,723,524 B` destroyed, `0` live devices/buffers/bytes, `0` `<canvas>` nodes |
| Gate 5: Negative control (`debugSkipBufferDestroy = true`) | `npm run test:e2e` | **PASS** — Deliberate `116,853,136 B` (`111.44 MiB`, `112` buffers) leak caught (`invariantFailedAsExpected: true`), then flushed to `0` |
| Rapid-pan JS heap (`memory-leak.spec.ts`) | `npm run test:e2e` | **PASS** — `8.12 MB -> 7.54 MB` (`-0.58 MB` delta) |
