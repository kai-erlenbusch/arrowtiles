# ArrowTiles & Deepgraph `v0.1.1` — `1.35B` Gaia DR3 Hardware Crucible & Dual-GPU Benchmark

**Date:** `2026-11-24`  
**Versions:** `arrowtiles==0.1.1` (`Apache-2.0`), `deepgraph@0.1.1` (`CC-BY-NC-4.0` + Commercial)  
**Wire Format:** `.arrowtiles` `v0.1` (`docs/SPEC.md` — zero wire-format changes from `v0.1.0`)

---

## 1. Testbed & Reproducibility Environment

| Component | Specification |
| :--- | :--- |
| **OS** | Windows 11 (`10.0.26200-SP0`) |
| **CPU** | Intel 24-logical-core (`Intel64 Family 6 Model 198 Stepping 2`), `memory_limit="24GB"` |
| **Integrated GPU (Pass 1)** | Intel Arc / `xe-lpg` (`powerPreference: "low-power"`, `--force_low_power_gpu`) |
| **Discrete GPU (Pass 2)** | NVIDIA GeForce RTX 5090 Laptop GPU (`architecture: "blackwell"`, verified idle `0 MiB / 0 %` via `nvidia-smi` prior to run) |
| **Toolchain** | Python `3.14.2`, DuckDB `1.5.3`, PyArrow `24.0.0`, Rust `1.80+` (`maturin --release --locked`), Node.js `24`, Chromium WebGPU (`1280×720` viewport, `180 Hz` panel) |
| **Scratch Isolation** | `TEMP`, `TMP`, `--temp-dir`, and Playwright `outputDir` strictly pinned to `../_scratch_crucible` on the data drive (`0 B` spilled to the OS drive; OS drive free space started at `18.26 GiB` and finished at `24.07 GiB`) |
| **Source Corpus** | `41` local ESA Gaia DR3 Parquet shards (`s3_cache/batch_000..040.parquet`, **`1,348,176,623` stars**) + LMSys UMAP chat embeddings (`lmsys.parquet`, **`2,835,490` rows × `38` columns**) |

### Reproduction Commands

```powershell
# 1. Progressive 4-rung out-of-core build + SPEC v0.1 validation + raw Parquet row_id > 1B parity check:
New-Item -ItemType Directory -Force "..\_scratch_crucible\tmp" | Out-Null
$env:TEMP = (Resolve-Path "..\_scratch_crucible\tmp").Path; $env:TMP = $env:TEMP
python scripts/bench/run_v011_crucible.py `
  --gaia-glob "../deepgraph/s3_cache/batch_*.parquet" `
  --lmsys-parquet "../lmsys.parquet" `
  --scratch-dir "../_scratch_crucible" `
  --out-gaia "../deepgraph/public/gaia_full.arrowtiles" `
  --overwrite `
  --memory-limit 24GB

# 2. Intel xe-lpg iGPU 5-Gate VRAM Lifecycle + 1.35B Crucible Suite (in sibling `deepgraph` repo):
npx playwright test tests/gpu-vram-lifecycle.spec.ts tests/crucible-1b.spec.ts

# 3. NVIDIA RTX 5090 dGPU Pass (only when `nvidia-smi` reports <= 512 MiB used and <= 5% util):
$env:DEEPGRAPH_ALLOW_DGPU = "1"
npx playwright test tests/gpu-vram-lifecycle.spec.ts tests/crucible-1b.spec.ts
```

---

## 2. Progressive Out-of-Core Build & `validate_file` Ladder (`2.84M → 1.35B`)

All four rungs retained `100.0%` of finite-coordinate input rows (`dropped_rows = 0`), stayed strictly within bounded private commit memory (`24.83 GiB` during 500M build; `27.59 GiB` peak process commit across the entire `4.2h` run; `37.12 GiB` peak OS working set including `mmap` pages during `31.81 GiB` archive validation), and passed full `validate_file` `SPEC.md v0.1` verification (`0` warnings, `0` errors).

| Rung & Dataset | Input / Retained Rows | Total Wall (`Pass 1` / `Pass 2`) | Throughput (`rows/s`) | Output Archive Size | Addressed Tiles (`max_zoom`) | Peak `D:` Scratch (`Combined`) | `validate_file` Wall (`Status`) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Rung 1:** LMSys Wide (`38 → 35` cols, `13` `f64→f32`) | `2,835,490` | `9.35s` (`4.64s` / `0.89s`) | `303,235/s` | `151.32 MiB` | `57` (`Z=4`) | `0.22 GiB` | `0.85s` (`PASS`) |
| **Rung 2:** Gaia DR3 (`100M` real stars) | `100,000,000` | `155.46s` (`117.00s` / `33.90s`) | `643,273/s` | `2.44 GiB` | `9,573` (`Z=8`) | `3.77 GiB` (`6.19 GiB`) | `25.15s` (`PASS`) |
| **Rung 3:** Gaia DR3 (`500M` real stars) | `500,000,000` | `2,191.65s` (`1,253.13s` / `913.83s`) | `228,138/s` | `11.98 GiB` | `19,037` (`Z=9`) | `18.18 GiB` (`30.14 GiB`) | `148.02s` (`PASS`) |
| **Rung 4:** Full Local Gaia DR3 (`1.35B` real stars) | **`1,348,176,623`** | **`15,132.05s`** (`8,453.14s` / `6,613.49s`) | **`89,094/s`** | **`31.81 GiB`** (`34,151,138,086 B`) | **`36,931` (`Z=9`)** | **`48.27 GiB`** (`80.07 GiB`) | **`485.95s` (`PASS`)** |

### Full `1.35B` Archive Structural Profile (`public/gaia_full.arrowtiles`, `v0.1`)
- **PMTiles v3 Directory Footprint:** Root directory `73 B` (in-header), JSON metadata `1,059 B`, leaf directories **`110,286 B` (`107.7 KiB` covering all `36,931` tiles)**.
- **Tile Size Bounds:** Largest compressed tile across all `36,931` tiles is **`3.02 MiB`** (`3,161,596 B` at `Z=3, X=5, Y=5`, well below the `64 MiB` `SPEC.md` ceiling); `observed_max_tile_rows = 100,000`.
- **Overview Payload (`Z=0..2`):** `21` tiles totaling `49.83 MiB` (`1,650,899` stored rows; `1,630,920` rendered at the preset's default `phot_g_mean_mag <= 14.0` magnitude cutoff); root tile `Z=0/0/0` is **`2.42 MiB`** (`79,032` stored rows; `78,959` rendered `phot_g_mean_mag <= 14.0` stars).

---

## 3. Cold Boot & Simulated WAN (`50 ms RTT / 50 Mbps`) TTFF (`deepgraph/standalone`)

Measured on the `1.35B`-star `v0.1` Gaia archive (`31.81 GiB`, `1,348,176,623` stars) using the production single-file `dist/standalone.js` bundle (`198.96 kB` gzipped, `Blob`-inlined Zstd WASM + `@uwdata/flechette` worker) with cache-busted `.arrowtiles` URLs so `100%` of HTTP `206 Partial Content` Range requests execute cold:

| Network Profile | GPU Adapter | Cold TTFF (`ms`) | Rendered Stars (`Stored Rows`) | HTTP `206` Range Requests | `.arrowtiles` Bytes Transferred |
| :--- | :--- | ---: | ---: | ---: | ---: |
| **Cold Loopback** (`detailOffset=2`, `Z=0..2`) | Intel `xe-lpg` iGPU | **`389.4 ms`** | `1,630,920` (`1,650,899` across `21` tiles) | `24` | `49.95 MiB` |
| **Cold Loopback** (`detailOffset=2`, `Z=0..2`) | NVIDIA RTX 5090 (`blackwell`) | **`742.0 ms`** | `1,630,920` (`1,650,899` across `21` tiles) | `24` | `49.95 MiB` |
| **Simulated WAN (`50 ms RTT / 50 Mbps`, `detailOffset=0`)** | Intel `xe-lpg` iGPU | **`687.5 ms`** | `78,959` (`79,032` in `Z=0/0/0` root tile) | **`4`** | **`2.53 MiB`** |
| **Simulated WAN (`50 ms RTT / 50 Mbps`, `detailOffset=0`)** | NVIDIA RTX 5090 (`blackwell`) | **`734.1 ms`** | `78,959` (`79,032` in `Z=0/0/0` root tile) | **`4`** | **`2.53 MiB`** |

> **Why Cold WAN TTFF is `~0.69–0.73s` on a `31.81 GiB` Archive:** Opening the `1.35B`-star archive over a `50 ms RTT / 50 Mbps` (`6.25 MB/s`) link transfers only **`2.53 MiB` across `4` HTTP `206` Range requests** (`16 KiB` header/root-dir + `1 KiB` JSON metadata + `108 KiB` leaf directory + `2.42 MiB` `Z=0/0/0` root tile containing `79,032` stored rows) before presenting the first `78,959` `phot_g_mean_mag <= 14.0` stars on screen (`687.5 ms` on Intel `xe-lpg` iGPU; `734.1 ms` on NVIDIA RTX 5090).

---

## 4. Multi-Scale Steady-State Frame Rate & GPU Compute Dispatch (`1280×720`)

Stationary `1.0s` `requestAnimationFrame` throughput and per-frame WebGPU compute+resolve dispatch (`renderMs`) across five astronomical regimes on the `1.35B`-star `v0.1` Gaia archive (`180 Hz` display cap = `~175–180 FPS`):

| Viewport Regime | Pyramid `Z` | Active Tiles | Active GPU Stars | Tile VRAM (`MiB`) | Intel `xe-lpg` iGPU FPS (`renderMs`) | NVIDIA RTX 5090 dGPU FPS (`renderMs`) |
| :--- | :---: | ---: | ---: | ---: | ---: | ---: |
| **Full Sky (`zoom=1.5`)** | `Z=2` | `21` | `1,630,920` | `18.89` | **`177.9 FPS`** (`0.162 ms`) | **`177.4 FPS`** (`0.097 ms`) |
| **Galactic Core (`zoom=2.17`)** | `Z=3` | `81` | `5,307,483` | `76.38` | **`70.1 FPS`** (`0.225 ms`) | **`175.9 FPS`** (`0.148 ms`) |
| **LMC Wide (`zoom=36.0`)** | `Z=7` | `93` | **`7,224,142`** | `154.96` | **`67.4 FPS`** (`0.234 ms`) | **`174.8 FPS`** (`0.266 ms`) |
| **LMC Core (`zoom=288.0`)** | `Z=9` | `40` | `3,047,881` | `177.75` | **`127.0 FPS`** (`0.153 ms`) | **`176.2 FPS`** (`0.184 ms`) |
| **Andromeda / M31 (`zoom=48.0`)** | `Z=7` | `63` | `2,062,888` | `188.22` | **`179.6 FPS`** (`0.166 ms`) | **`178.9 FPS`** (`0.192 ms`) |

---

## 5. Commutative `0.0000%` Stationary Shimmer (`5.31M` Active Stars, Modes `0 / 1 / 2`)

Two consecutive PNG canvas captures taken after all `81` Galactic Core (`Z=3`, `5,307,483` active stars) tiles settled and completed their `300 ms` spawn fade on **both** GPU architectures:

| Render Pipeline & Mode | Lit Pixels (`1280×720`) | Intel `xe-lpg` Changed Pixels (`Max Δ`) | NVIDIA RTX 5090 Changed Pixels (`Max Δ`) |
| :--- | ---: | ---: | ---: |
| **Mode 0:** Optical `R16/G16/B16` Sky (`3,840`-ticket flux gate) | `845,377` | **`0` (`0.0000%`, `Δ=0`)** | **`0` (`0.0000%`, `Δ=0`)** |
| **Mode 1:** Log-Density Points (`viridis` `bp_rp`, `1,024` levels) | `848,858` | **`0` (`0.0000%`, `Δ=0`)** | **`0` (`0.0000%`, `Δ=0`)** |
| **Mode 2:** Unbiased Per-Pixel Mean Field (`coolwarm` `bp_rp`) | `849,732` | **`0` (`0.0000%`, `Δ=0`)** | **`0` (`0.0000%`, `Δ=0`)** |

> **Hardware Crucible Catch Fixed in `v0.1.1`:** Running `5.31M` Galactic Core stars on the `blackwell` RTX 5090 exposed a subtle `1 LSB` (`maxDelta = 1`) warp-scheduling race in `splat_optical_pixel` where the old `< 96`-star counter truncated pixels struck by `200–500` faint bulge stars (`rU ≈ 6..10` each, unsaturated `< 1024u`). Replacing the `1-star = 1-ticket` counter with a flux-proportional ticket `ceil(max(rU, gU, bU) / 16)` (`1..32`) gated at `<= 3,840` (`3,840 × 16 = 61,440 < 65,535`) increased faint-star capacity by **`40×`** (`3,840` stars/pixel) with zero `u16` carry overflow and **`0` changed pixels (`0.0000%`)** on both GPUs.

---

## 6. `row_id > 1,000,000,000` GPU `pickAt()` Parity vs. Raw Source Parquet

Three reference stars with **`row_id > 10^9`** (`> 2^30`) were traced back to their exact source shard and row offset in `s3_cache/batch_*.parquet`, centered at `zoom = 256`, and queried via `await plot.pickAt(640, 360)` on both GPUs:

| Expected `row_id` | Picked `row_id` (iGPU & dGPU) | Source Parquet Shard (`file_row_number`) | `|Δ phot_g_mean_mag|` | `|Δ Hammer X|` (`u16` quant) | `|Δ Hammer Y|` (`u16` quant) | Pick Latency (`iGPU` / `dGPU` warm) |
| ---: | ---: | :--- | ---: | ---: | ---: | ---: |
| **`1,202,742,788`** | **`1,202,742,788`** | `batch_032.parquet` (`#3,179,113`) | `0.000000` | `1.53e-5` | `1.63e-5` | `124.2 ms` / `56.8 ms` *(cold tile)* |
| **`1,228,887,815`** | **`1,228,887,815`** | `batch_033.parquet` (`#8,922,713`) | `0.000000` | `2.61e-5` | `9.31e-6` | `139.9 ms` / `6.6 ms` |
| **`1,060,650,830`** | **`1,060,650,830`** | `batch_027.parquet` (`#27,680,549`) | `0.000000` | `3.81e-5` | `9.91e-6` | **`11.5 ms` / `5.8 ms`** *(warm LRU)* |

---

## 7. 5-Gate GPU VRAM, `GPUDevice` & CPU `ArrayBuffer` Lifecycle Audit

Executed against the `1.35B`-star `v0.1` Gaia archive (`public/gaia_full.arrowtiles`) on both Intel `xe-lpg` and NVIDIA `blackwell`:
1. **Deep-Zoom LRU Eviction Plateau (Gate 2):** `396` unique `Z >= 3` tiles streamed across `18` Galactic plane waypoints with `maxTileCache = 40` → active tile VRAM plateaued at **`44.02 MiB`** (`120` live buffers), `retainedTileCpuBytes === 0` at every single waypoint, CPU recycling pool **`28.25–29.15 MiB`** (`< 64 MiB` budget), `1,239` evicted `GPUBuffer`s destroyed on-the-fly.
2. **Dataset Swap & `20×` Create/Destroy Cycles (Gates 3 & 4):** `5×` round-trip dataset swaps returned to byte-identical baseline (`1,334,628 B`, `67` buffers); `20×` `Deepgraph.create()` + `plot.destroy()` cycles destroyed `20/20` `GPUDevice`s with `0` leftover `<canvas>` elements.
3. **Negative-Control Verification & Final Teardown (Gate 5 & `crucible-1b`):** Suppressing `GPUBuffer.destroy()` on eviction immediately tripped a `116.11 MiB` (`291`-buffer) leak alarm; restoring teardown ended every suite at **`liveDevices = 0`, `liveBuffers = 0`, `liveBytes = 0`** (`349,374,636 / 349,374,636 B` across `1,190` buffers in `crucible-1b` on both GPUs; `835,636,772 / 835,636,772 B` on RTX 5090 and `835,346,216 / 835,346,216 B` on Intel `xe-lpg` across the 5-gate VRAM lifecycle suite).
