---
log_id: 2026-11-21_05
date: 2026-11-21
type: WALKTHROUGH
status: executed
scope: [viewer, spec, writer]
source_artifact: phase8b_visual_tuning_candidates.md
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# Walkthrough: Restored Pre-8b (`Pre-8b`) `R16 / G16 / B16` Optical RGB Pipeline + `zoom > 36` Deep-Zoom Rescue & Pre-Publish `SPEC.md` `0.x` / `required_features` Gates

## 1. Root-Cause Diagnosis & Final Resolution

1. **Why Scalar `mean(bp_rp)` Was Retired in Favor of `Pre-8b`'s Exact `R16 / G16 / B16` Pipeline:**
   - Averaging scalar `bp_rp` per pixel before looking up a single colour stop discarded multi-star blue OB + golden red-clump mixing and prevented sequential `R → G → B` channel saturation (`amber-gold → bright yellow → incandescent white-gold bulge` at `Z=2..3`, `zoom = 2.17`).
   - `Pre-8b`'s `2 × u32` `16-bit` channel accumulator (`word0 = R16 | (G16 << 16)`, `word1 = B16`, scale `1.0 = 1024.0`, resolved via `min(ch, 1024u) / 1024.0` + `clamp(bg + rgb, 0, 1)`) was verified both algebraically and empirically to have **`0.0000%` stationary shimmer** (`64×` headroom before `65535` wrap).
   - Restored `Pre-8b`'s `eval_color` optical RGB stops, `three_aces_filmic`, `linear_to_srgb`, `splat_optical_pixel`, Mode 3 star trails, and `fs_main` `16-bit` RGB resolve **verbatim** in `src/core/ComputeRasterizer.ts`, removing `eval_optical_blackbody`, `encode_optical_color_t`, and `saturation` while keeping the 4 clean public `ViewOptions` (`pointSize`, `zoomBalance`, `pointOpacity`, `exposure`).

2. **Exact `zoom <= 36` (`Z=0..7`) Bit-Exact Anchor + `zoom > 36` Deep-Zoom Rescue:**
   - Preserved `Pre-8b`'s **exact** `exposure = mix(1.0, 0.35, clamp((zoomT - 0.30) / 0.50, 0, 1))` (`1.000` at `Z=0..3` including `zoom = 2.17`; `0.350` at `LMC Z=7` `zoom = 36`), `diameterPx`, `effDiam = 2.5 * dpr`, and `dynamicOpacity` curve verbatim across `logZoom <= 5.20` (`zoom <= 36.8`).
   - Strictly above `logZoom > 5.20` (`zoom > 36.8`), uncapped continuous star-size growth past `zoom = 64` (`extraZoomGrowth`, `maxDiamCss` up to `6.0`) and gently lifted `autoOpticalExposure` (`0.35 → 1.07` across `logZoom = 5.20..9.0`) + bright-star `deepBrightBoost` (`G < 19.2`) so `M31` (`zoom = 48`), `LMC Z=8` (`zoom = 114`), `M33` (`zoom = 180`), and `LMC Z=10` (`zoom = 358`) clear ACES's `0.00325` toe with crisp star hierarchy and dark velvet sky.

3. **Pre-Publish `SPEC.md` `v0.1` `0.x` Minor-Version & `required_features` Gates:**
   - Updated `docs/SPEC.md` (§1 & §6.4), `arrowtiles/builder.py` (`RESERVED_METADATA_KEYS`), `arrowtiles/reader.py`, `arrowtiles/validator.py`, and `deepgraph-arrowtiles-sandbox/src/lib/DatasetSession.ts`:
     - While `major == 0`, readers and validators **reject** archives with `minor > 1` (`"0.1"` accepted; `"0.2"` rejected with a descriptive error).
     - Reserved `"required_features": string[]` (`[]` or omitted in `v0.1`); readers and validators **reject** non-array values or any unrecognized feature identifier.

---

## 2. Quantitative Side-by-Side Comparison (`Intel xe-lpg iGPU`, `0 B` on Discrete RTX 5090)

| Target View | Tuning | `roiMeanLum` | `p99Lum` | `bgMeanLum` | `contrastRatio` | `meanChroma` | `meanRGB` | `darkSkyPct` | Mean `\|ΔRGB\|` vs `Pre-8b` |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. All-Sky Core** (`Z=2`, `zoom=1.8`) | `Pre-8b` Ref | `115.78` | `193.4` | `87.65` | `1.40×` | `73.01` | `[143.1, 112.3, 70.1]` | `24.67%` | — |
| | **Final Phase 8b** | **`115.78`** | **`193.4`** | **`87.65`** | **`1.40×`** | **`73.01`** | **`[143.1, 112.3, 70.1]`** | **`24.67%`** | **`0.0000`** *(bit-exact)* |
| **2. Galactic Bulge** (`Z=3`, `zoom=2.17`) | `Pre-8b` Ref | `213.35` | `255.0` | `82.70` | `2.99×` | `109.96` | `[239.5, 214.1, 129.5]` | `7.55%` | — |
| | **Final Phase 8b** | **`213.35`** | **`255.0`** | **`82.70`** | **`2.99×`** | **`109.96`** | **`[239.5, 214.1, 129.5]`** | **`7.55%`** | **`0.0000`** *(bit-exact)* |
| **3. LMC Bar** (`Z=7`, `zoom=36`) | `Pre-8b` Ref | `120.17` | `194.4` | `24.10` | `14.54×` | `67.74` | `[145.8, 116.8, 78.1]` | `19.68%` | — |
| | **Final Phase 8b** | **`120.18`** | **`194.4`** | **`24.10`** | **`14.54×`** | **`67.75`** | **`[145.8, 116.8, 78.1]`** | **`19.67%`** | **`0.0166`** *(max Δ = 1)* |
| **4. LMC Deep** (`Z=8`, `zoom=114`) | `Pre-8b` Ref *(dim)* | `60.34` | `104.8` | `29.63` | `3.43×` | `24.38` | `[69.5, 59.4, 45.1]` | `25.16%` | — |
| | **Final Phase 8b** | **`165.70`** | **`255.0`** | **`59.55`** | **`3.49×`** | **`68.50`** | **`[187.3, 164.1, 118.8]`** | **`6.95%`** | Rescued (`+174.6%` ROI) |
| **5. LMC Starfield** (`Z=10`, `zoom=358`) | `Pre-8b` Ref *(dark)* | `24.05` | `49.4` | `20.73` | `1.89×` | `6.24` | `[31.6, 29.1, 25.4]` | `75.29%` | — |
| | **Final Phase 8b** | **`98.50`** | **`253.0`** | **`58.86`** | **`1.95×`** | **`35.23`** | **`[115.7, 103.7, 80.5]`** | **`19.34%`** | Rescued (`+412%` `p99`) |
| **6. Andromeda M31** (`Z=7`, `zoom=48`) | `Pre-8b` Ref *(faint)* | `24.15` | `60.0` | `22.03` | `1.42×` | `8.65` | `[32.9, 29.0, 24.2]` | `81.00%` | — |
| | **Final Phase 8b** | **`34.64`** | **`109.3`** | **`29.52`** | **`1.41×`** | **`15.20`** | **`[48.0, 41.8, 32.8]`** | **`58.44%`** | Rescued (`+82.2%` `p99`) |
| **7. Triangulum M33** (`Z=9`, `zoom=180`) | `Pre-8b` Ref *(dark)* | `17.47` | `45.7` | `17.19` | `0.47×` | `4.95` | `[27.8, 25.6, 22.9]` | `99.33%` | — |
| | **Final Phase 8b** | **`21.63`** | **`138.6`** | **`19.85`** | **`1.63×`** | **`13.30`** | **`[54.2, 49.3, 41.0]`** | **`93.04%`** | Rescued (`+203.3%` `p99`) |

- **Stationary Shimmer Proof (`gaia_full.arrowtiles` on Intel `xe-lpg`):**
  - `Z=3, zoom=2.17`: **`0 / 962,054` changed pixels (`0.0000%`, `maxDelta = 0`)**.
  - `LMC Z=10, zoom=358`: **`0 / 899,827` changed pixels (`0.0000%`, `maxDelta = 0`)**.

---

## 3. Local Reference Assets (`logs/assets/`, Gitignored Binary Snapshots)

- Master `2 × 7` Comparison Grid: [`assets/2026-11-21_05_master_2x7_grid.png`](assets/2026-11-21_05_master_2x7_grid.png)
- Galactic Core `Z=2` (`zoom=1.8`): [`assets/2026-11-21_05_pair_gaia_core_z2.png`](assets/2026-11-21_05_pair_gaia_core_z2.png)
- Galactic Bulge `Z=3` (`zoom=2.17`): [`assets/2026-11-21_05_pair_gaia_core_z3_zoom217.png`](assets/2026-11-21_05_pair_gaia_core_z3_zoom217.png)
- LMC Bar `Z=7` (`zoom=36`): [`assets/2026-11-21_05_pair_lmc_z7_zoom36.png`](assets/2026-11-21_05_pair_lmc_z7_zoom36.png)
- LMC Deep `Z=8` (`zoom=114`): [`assets/2026-11-21_05_pair_lmc_z8_zoom114.png`](assets/2026-11-21_05_pair_lmc_z8_zoom114.png)
- LMC Starfield `Z=10` (`zoom=358`): [`assets/2026-11-21_05_pair_lmc_z10_zoom358.png`](assets/2026-11-21_05_pair_lmc_z10_zoom358.png)
- Andromeda Galaxy M31 (`zoom=48`): [`assets/2026-11-21_05_pair_m31_zoom48.png`](assets/2026-11-21_05_pair_m31_zoom48.png)
- Triangulum Galaxy M33 (`zoom=180`): [`assets/2026-11-21_05_pair_m33_z9.png`](assets/2026-11-21_05_pair_m33_z9.png)

---

## 4. Build & Test Verification

- **Writer Suite (`duckdb-arrowtiles`):** `53 passed, 1 skipped in 22.70s` (including `test_spec_0x_minor_version_and_required_features_gates`).
- **Viewer Typecheck & Builds (`deepgraph`):**
  - `npm run typecheck`: `0` errors (`0` references to `saturation` or `eval_optical_blackbody`).
  - `npm run build:lib`: `dist/index.js` = `187.22 kB` (**`46.62 kB` gzip**); `dist/standalone.js` = `435.82 kB` (**`99.97 kB` gzip**); `pmtiles.worker` = `514.00 kB`.
  - `npm run verify:types` + `npm run build:demo`: PASS.
  - **Playwright Suite (`Intel xe-lpg iGPU`, `< 5 MiB` samples):** `3 passed` (`library-embed.spec.ts`, `phase8b-hdr-density.spec.ts` including `"0.2"` & `required_features` rejection gates, `picking-layer.spec.ts`, `liveDevices = 0`, `liveBytes = 0`).
