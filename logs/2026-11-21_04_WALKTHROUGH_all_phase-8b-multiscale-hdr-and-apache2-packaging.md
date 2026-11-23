---
log_id: 2026-11-21_04
date: 2026-11-21
type: WALKTHROUGH
status: executed
scope: [all]
source_artifact: phase8b_multiscale_hdr_comparison.md
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Walkthrough: `D12b` Apache-2.0 Licensing, `SPEC.md` `v0.1` `tiling: "quadtree-2d"`, Phase 8b Multiscale Linear HDR Resolve, and Phase 8c Bundler/Standalone Split

## 1. Summary of 3-Commit Execution (`revival/2026-11-wip`, Unpushed)

1. **Commit 1 (`54e0c2a` writer) — `D12b` Licensing & `SPEC.md` `v0.1` `"tiling": "quadtree-2d"` *(subsequently amended in `2026-11-22_06` so `arrowtiles` remains `Apache-2.0` while `deepgraph` uses `CC-BY-NC-4.0` + Commercial License)*:**
   - Added standard Apache License 2.0 `LICENSE` and `NOTICE` (`Copyright 2026 Kai Erlenbusch`) at the root of `arrowtiles` (zero per-file license headers).
   - Configured `Apache-2.0` metadata in `pyproject.toml`, `arrowtiles-engine/Cargo.toml`, and `docs/SPEC.md` (with `deepgraph` later updated to `CC-BY-NC-4.0` + Commercial License in `package.json`, keeping `"private": true`, and preserving ESA/Gaia/DPAC and LMSys-Chat-1M data attributions).
   - Standardized reserved `"tiling": "quadtree-2d"` in `docs/SPEC.md` (§1 & §6.4), `arrowtiles/builder.py`, `arrowtiles/reader.py`, `arrowtiles/validator.py`, `tests/test_spec_tiling.py` (`52 passed, 1 skipped`), and `DatasetSession.ts` (defaulting omitted `"tiling"` to `"quadtree-2d"` while rejecting unknown present values).

2. **Commit 2 (viewer) — Phase 8b Multiscale Zoom-Adaptive Density & Per-Pixel Linear HDR Resolve:**
   - Replaced per-star `three_aces_filmic` + `linear_to_srgb` and `rand255` stochastic skip in Mode 0/3 (`ComputeRasterizer.ts`) with deterministic linear radiometric flux accumulation (`word0` at scale `1.0 = 65536.0`, saturation-gated `< 0x80000000u`) and exact flux-weighted chromaticity (`word1 = Σ(fClamped * tU255)` mapped across active `[u.colorMin, u.colorMax]`, gated on `prevFlux < 16,777,215`, `16,777,215 × 255 = 4,278,190,075 < 2^32`), resolving linear-space Gaia blackbody + ACES filmic + sRGB **once per screen pixel** in `fs_main`.
   - Added continuous unclamped `Renderer.logZoom`, `pointSize * pow(2.0, logZoom * zoomBalance)` point sizing (`pointSize = 1.0`, `zoomBalance = 0.22`), relaxed deep-zoom `maxMagCutoff` (`22.0`, `bin = 15`), exact `Float64` `RTC` viewport-intersection density estimation with stationary-frame bit-exact exposure lock, continuous Mode 1 `refCount` (`96.0 → 1.15`), expanded `PickingLayer` hit windows, and public `pointSize` / `zoomBalance` / `pointOpacity` / `exposure` options + `ControlsPanel` sliders.

3. **Commit 3 (Phase 8c viewer + writer logs) — Bundler (`dist/index.js`) vs. Standalone (`dist/standalone.js`) Build Split, Consumer Vite Build Gate & `RowAttributeResolver` `AbortSignal`:**
   - Split library output into externalized `dist/index.js` (`exports["."]`, `188.30 kB` / **`47.37 kB` gzip**, externalizing main-thread `pmtiles`, `p-queue`, `fflate`, `apache-arrow`, `@bokuweb/zstd-wasm`) and self-contained `dist/standalone.js` (`exports["./standalone"]`, `436.90 kB` / `100.73 kB` gzip for `examples/embed.html`), keeping `dist/assets/pmtiles.worker-*.js` (`514.00 kB`) 100% self-contained with inlined base64 `zstd.wasm` in both builds.
   - Extended `scripts/verify_consumer_dts.mjs` (`npm run verify:types`) with a real `vite build` consumer application importing `dist/index.js` alongside `apache-arrow` in addition to external `bundler` and `nodenext` `tsc --noEmit`.
   - Added `signal?: AbortSignal` as the 4th parameter of `RowAttributeResolver` with pre-call `signal?.aborted` short-circuiting and `AbortController` cancellation across hover, click, `pickAt`, `load()`, and `destroy()`.

---

## 2. Quantitative Acceptance Matrix (`Intel xe-lpg iGPU`, `0 B` on Discrete RTX 5090)

| Check / View | Metric | Before (`Pre-8b`) | After (`Phase 8b / 8c`) | Result |
| :--- | :--- | :---: | :---: | :---: |
| **Mode 0 Shimmer** (`gaia_sample`) | Changed pixels across 2 frames | `0 / 178,928` (`0.0000%`) | **`0 / 171,864` (`0.0000%`, `maxDelta = 0`)** | **PASS** |
| **Galactic Core `Z=2`** (`zoom = 1.8`, `4.33M` pts) | FPS / Mean lit / `p99` / Pure white | `101.9 fps` / `106.99` / `194` / `0.00%` | **`104.7 fps` (`+2.7%`)** / `117.44` / `169` / **`0.00%`** | **PASS** |
| **Galactic Core `Z=3`** (`zoom = 3.5`, `9.33M` pts) | FPS / Mean lit / `p99` / Pure white | `65.8 fps` / `116.07` / `246` / `0.05%` | **`69.9 fps` (`+6.2%`)** / `104.75` / `160` / **`0.00%`** | **PASS** |
| **LMC `Z=3 → Z=7 → Z=8 → Z=10`** (`zoom = 3.2..358`) | Mean lit brightness trajectory | `122.9 → 65.6 → 44.7 → 28.5` | **`108.8 → 145.2 → 163.2 → 114.9`** (`0%` clip) | **PASS** |
| **M31 Andromeda** (`zoom = 48`, `2.75M` pts) | Center ROI mean lit / `p99` | `27.91` / `52` | **`75.91` / `172` (`+230.8%` `p99`)** | **PASS** |
| **Pan LMC → Empty Sky** (`zoom = 16`) | Fixed sky patch `pumpingRatio` | `1.000` | **`1.000` (`74.36 → 74.36`)** | **PASS** |
| **LMSys 2.84M** (`Z=2` & `zoom = 64`, Mode 1) | `Z=2` mean lit / `zoom=64` `p99` | `88.02` / `129` | **`87.98` (`-0.05%`) / `181` (`+40.3%`)** | **PASS** |
| **Bundler vs. Standalone Build** (`npm run build:lib`) | `dist/index.js` / `dist/standalone.js` | `429.8 kB` (`98.5 kB` gz) | **`188.3 kB` (`47.4 kB` gz)** / **`436.9 kB` (`100.7 kB` gz)** | **PASS** |
| **Consumer `tsc` + Real `vite build`** (`verify:types`) | `bundler` + `nodenext` + `vite build` | `tsc` only | **`PASS` (`2` consumer JS chunks + worker)** | **PASS** |
| **Playwright E2E (`< 5 MiB` samples, Intel iGPU)** | `library-embed` + `phase8b` + `picking-layer` | `2 passed` | **`3 passed in 55.2s` (`0` GPU/buffer leaks)** | **PASS** |
| **Writer `pytest` Suite** (`duckdb-arrowtiles`) | Full `pytest` suite | `51 passed, 1 skipped` | **`52 passed, 1 skipped in 17.10s`** | **PASS** |
