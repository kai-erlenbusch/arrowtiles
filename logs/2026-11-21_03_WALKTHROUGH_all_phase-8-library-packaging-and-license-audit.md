---
log_id: 2026-11-21_03
date: 2026-11-21
type: WALKTHROUGH
status: executed
scope: [all]
source_artifact: none
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Pre-Phase-8 & Phase 8 Walkthrough — Hover Network/CPU Hardening, Vite ES-Module Library Packaging (`98.5 kB` gzip), TypeScript 6.0 `.d.ts` Consumer Gate, `examples/embed.html`, and Read-Only License Audit (`⛔ D12`)

## 1. Summary of Changes

### Commit 1 (`ecda73d` in `deepgraph-arrowtiles-sandbox`) — Pre-Phase-8 Hover Hardening & Error Guards
1. **Two-Level Hover Decode Cache + Same-Winner Short-Circuit + Coalesced `AbortSignal` (`src/lib/ViewerLayer.ts`, `src/PMTilesClient.ts`, `src/pmtiles.worker.ts`):**
   - Short-circuits repeated hovers on the same `(tileKey, rawRowIdx)` (`0` network requests, `0` worker messages, `0` duplicate `'hover'` events).
   - Maintains a byte-capped (`<= 8` tiles / `<= 24 MiB`) compressed-tile LRU in `PMTilesClient` (opportunistically seeded by `loadTile`, tracked in `getCpuMemoryStats()`, and cleared on `setRequestedColumns` / `destroy()`) plus a 1-tile parsed Arrow `Table` cache in `pmtiles.worker.ts` (`decode_row`, cleared on `init_schema` / `clear_row_cache`) so consecutive hovers across points in the same tile execute in `O(1)` with `0` Zstd decompressions and `0` `ArrayBuffer.slice` copies.
   - Cancels superseded hovers via `AbortController` while coalescing concurrent intra-tile `getZxy(z, x, y, signal)` fetches so rapid intra-tile mouse motion never abort-restarts an in-flight tile download.
2. **Instant GPU Hover Ring, Spatial Slot Culling & Opt-In Hover Sidecar (`src/core/TileGpuStore.ts`, `src/core/PickingLayer.ts`, `src/lib/types.ts`, `docs/API.md`):**
   - Added `GPUBufferUsage.COPY_SRC` to tile column buffers and a `32 B` `winnerCoordBuffer` `MAP_READ` readback in `PickingLayer.ts` so `HighlightOverlay.hoverMarker` renders immediately at `60 FPS` before network/worker row decoding finishes.
   - Added CPU screen-space tile-bounds culling in `PickingLayer.ts` (`!isTransitioning`) to skip non-overlapping spatial slots.
   - Kept `resolveRowAttributes` click/`pickAt`-only by default and added `resolveRowAttributesOnHover?: boolean` (`default: false`).
3. **Async Error Guards & `pointerleave` Cleanup (`src/lib/ViewerLayer.ts`, `src/pmtiles.worker.ts`, `src/core/Renderer.ts`):**
   - Wrapped `handleCanvasClick` and `pickAt` in `try/catch` (`0` `UnhandledPromiseRejection`s on mid-click `destroy()` / superseded `load()`, routing genuine errors to `plot.on('error', ...)`), added `action` + `id` to Zstd init error `postMessage`s in `pmtiles.worker.ts`, and cleared `hoverMarker` + emitted `hover: null` on `<canvas>` `pointerleave`.

### Commit 2 — Phase 8: Embeddable Library Packaging, Public-API Demo, `examples/embed.html` & License Audit (`05_PLAN` §10)
1. **Vite ES-Module Library Build & Dependency Hygiene (`vite.lib.config.ts`, `package.json`, `docs/API.md`):**
   - Configured `"exports"`, `"main"`, `"module"`, `"types"`, `"files": ["dist", "docs/API.md"]`, and `"sideEffects": false` in `package.json` while keeping `"private": true` until `⛔ D12`.
   - Moved `"lil-gui"` to `"devDependencies"`, preserved `copyPublicDir: false` in both `vite.lib.config.ts` (`npm run build` / `npm run build:lib` -> `dist/index.js` at **`429.84 kB` / `98.47 kB` gzip**) and `vite.config.ts` (`npm run build:demo` -> `dist-demo/`).
   - Resolved the tile worker via `new Worker(new URL("assets/pmtiles.worker-*.js", import.meta.url), { type: "module" })` with `@bokuweb/zstd-wasm` inlined as `data:application/wasm;base64,...` inside the worker chunk (`0` `/assets/*.wasm` root URL assumptions).
2. **TypeScript 6.0 `.d.ts` Gate (`tsconfig.build.json`, `scripts/emit_dts.mjs`, `scripts/verify_consumer_dts.mjs`, `src/index.ts`, `src/lib/types.ts`):**
   - Emitted clean `dist/index.d.ts` + `dist/lib/types.d.ts` (`rootDir: "./src"`, `stripInternal: true`, `.ts -> .js` relative specifiers, `0` internal class / symbol / `@webgpu/types` leaks), verified by `npm run verify:types` (`tsc --noEmit` under both `bundler` and `nodenext` with `allowImportingTsExtensions` disabled, `skipLibCheck: false`, and `types: []`).
3. **Pure Public-API Demo & Single-HTML Embed (`src/main.ts`, `src/demo/ControlsPanel.ts`, `examples/embed.html`, `tests/library-embed.spec.ts`):**
   - Removed `INTERNAL_DIAGNOSTICS` from `src/main.ts` (`0` deep internal imports in `src/main.ts` and `src/demo/*`), added live `'hover'` + pinned `'click'` point inspection to `ControlsPanel.ts`, authored `examples/embed.html` (`44` lines importing `../dist/index.js`), and verified end-to-end in Playwright on Intel `xe-lpg` iGPU (`0 B` on RTX 5090).

---

## 2. Verification Summary

| Check | Command / Probe | Result |
| :--- | :--- | :--- |
| Writer pytest suite | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | **PASS** — `51 passed, 1 skipped` |
| Library build + `.d.ts` hygiene | `npm run typecheck && npm run build:lib` | **PASS** — `dist/index.js` = `429.84 kB` (`98.47 kB` gzip) in `224 ms`; `0` `lil-gui` / `three` / `gpuStats` / `INTERNAL_DIAGNOSTICS` / `.ts` specifier leaks |
| External consumer `tsc --noEmit` | `npm run verify:types` | **PASS** — Both `bundler` and `nodenext` pass with `allowImportingTsExtensions=false`, `skipLibCheck=false`, `types=[]` |
| Standalone demo build | `npm run build:demo` | **PASS** — Built cleanly to `dist-demo/` in `260 ms` (`copyPublicDir: false`) |
| Pre-Phase-8 throttled hover & error guards | `npx playwright test tests/picking-layer.spec.ts` (Intel `xe-lpg` iGPU) | **PASS** — `0` Range reqs across 20 loaded-tile hovers; `1` Range req across 20 cold-cache hovers (`50 ms` RTT / `50 Mbps`); instant GPU hover ring; `3 / 5` slots culled; `0` `UnhandledPromiseRejection`s; `37.92 MB / 37.92 MB` freed |
| Phase 8 `examples/embed.html` + public-API demo | `npx playwright test tests/library-embed.spec.ts` (Intel `xe-lpg` iGPU) | **PASS** — `/examples/embed.html?power=low` loaded `/dist/index.js` + worker/WASM (`failedUrls=[]`, `0` `.lil-gui`, clicked `row_id=40064` `"mixtral"`); demo hover + click readout & `0`-leak `destroy()` verified |

---

## 3. Read-Only `LICENSE` & Third-Party Dependency Audit (`05_PLAN` §10.3)

> [!IMPORTANT]
> Strictly read-only audit — **zero `LICENSE` files or `README.md` license sections were created or modified**.

### 3.1 Repository License File Status

| Repository | `LICENSE*` File on Disk | Manifest `license` Field | `README.md` §Licensing Text | Action Needed at `⛔ D12` |
| :--- | :---: | :---: | :---: | :--- |
| `duckdb-arrowtiles` | **None** | Unset (`pyproject.toml`, `Cargo.toml`) | `CC BY-NC 4.0` | Owner chooses final `LICENSE` + aligns `pyproject.toml`, `Cargo.toml`, `SPEC.md`, and `README.md` |
| `deepgraph-arrowtiles-sandbox` | **None** | Unset (`package.json`, `"private": true`) | `CC BY-NC 4.0` | Owner chooses final `LICENSE` + package `"name"` + aligns `package.json` and `README.md` |

### 3.2 Viewer (`deepgraph-arrowtiles-sandbox`) Dependencies

| Package | Version | Scope | License | Notes |
| :--- | :---: | :---: | :---: | :--- |
| `@bokuweb/zstd-wasm` | `0.0.27` | `dependencies` (bundled in worker) | `MIT` | Zstandard WASM decompressor (inlined as base64 WASM in `dist/assets/pmtiles.worker-*.js`) |
| `apache-arrow` | `21.1.0` | `dependencies` (bundled) | `Apache-2.0` | Arrow IPC `RecordBatch` / schema reader |
| `fflate` | `0.8.3` | `dependencies` (bundled) | `MIT` | Synchronous Gzip decompression for PMTiles v3 directories (`PMTilesClient.ts`) |
| `p-queue` | `9.3.1` | `dependencies` (bundled) | `MIT` | Priority concurrency queue for HTTP Range fetches |
| `pmtiles` | `4.4.1` | `dependencies` (bundled) | `BSD-3-Clause` | PMTiles v3 header & Hilbert directory reader |
| `lil-gui` | `0.21.0` | `devDependencies` (demo-only) | `MIT` | Used only in `src/demo/ControlsPanel.ts` (`0 B` in `dist/`) |

### 3.3 Writer (`duckdb-arrowtiles`) Direct Python & Rust Dependencies

| Ecosystem | Package / Crate | Version | License |
| :---: | :--- | :---: | :--- |
| Python | `duckdb` | `1.5.3` | `MIT` |
| Python | `pyarrow` | `24.0.0` | `Apache-2.0` |
| Python | `pmtiles` | `3.7.0` | `BSD-3-Clause` |
| Python | `tqdm` | `4.67.3` | `MPL-2.0 AND MIT` |
| Python (build) | `maturin` | `1.14.1` | `MIT OR Apache-2.0` |
| Rust | `arrow`, `parquet` | `58.3.0` | `Apache-2.0` |
| Rust | `pyo3` (`0.23.5`), `pyo3-log` (`0.12.4`), `pmtiles` (`0.23.0`), `rayon` (`1.12.0`), `serde_json` (`1.0.150`), `base64` (`0.22.1`), `anyhow` (`1.0.103`), `log` (`0.4.32`) | — | `MIT OR Apache-2.0` |
| Rust | `fast_hilbert` (`2.1.0`), `zstd` (`0.13.3`) | — | `MIT` |

*(Across all `426` transitive Rust crates in `Cargo.lock`, `424` use permissive `MIT`/`Apache-2.0`/`BSD`/`ISC`/`Zlib`/`Unicode-3.0` licenses, plus `attohttpc` `0.30.1` `MPL-2.0` and `webpki-roots` `1.0.7` `CDLA-Permissive-2.0`; `0` GPL/AGPL/SSPL/non-commercial crates.)*

---

## 4. Stopped Cleanly at `⛔ D12` — Owner Decision Checklist

1. **Package Naming (`⛔ D12a`):** Choose the npm package name for `deepgraph-arrowtiles-sandbox` and confirm PyPI name `arrowtiles` for `duckdb-arrowtiles`.
2. **Licensing (`⛔ D12b`):** Choose the repository `LICENSE` file(s) (e.g. Apache-2.0 / MIT / dual-license or commercial strategy, plus open `SPEC.md` license) and update `README.md` §Licensing + package manifests accordingly.
3. **Publishing & Git Push (`⛔ D12c`):** Review local branch `revival/2026-11-wip` in both repositories, push to GitHub / open PRs, and flip `"private": false` when ready to publish.
