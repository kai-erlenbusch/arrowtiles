# ArrowTiles & DeepGraph — Engineering, Research & Audit Logs (`logs/`)

All deep research memos, read-only forensic audits, implementation plans, architectural decision records (ADRs), and post-execution walkthroughs are persisted here so institutional context lives permanently in Git rather than disappearing inside ephemeral IDE/agent session folders.

> Note: `.gitignore` uses `logs/*`, `!logs/README.md`, and `!logs/20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9]_*.md` so structured chronological engineering logs are tracked in Git while historic multi-megabyte raw session transcripts in `logs/` remain untracked on disk.

---

## 1. File Naming Convention

```text
YYYY-MM-DD_<seq>_<TYPE>_<scope>_<topic-slug>.md
```

| Segment | Format | Purpose & Controlled Values |
| :--- | :--- | :--- |
| **`YYYY-MM-DD`** | ISO-8601 date | Guarantees strict chronological sorting in File Explorer, VS Code, and GitHub even after `git clone`. |
| **`<seq>`** | `01`, `02`, ... | Two-digit daily sequence number preserving exact intra-day order when multiple logs are written on the same date. |
| **`<TYPE>`** | `UPPERCASE` | • **`RESEARCH`** — Deep research, competitor/format benchmarks, ecosystem synthesis<br>• **`AUDIT`** — Read-only forensic codebase & binary reviews, correctness/security diagnostics<br>• **`PLAN`** — Implementation plans (`/plan`), migration blueprints, phase specs<br>• **`ADR`** — Locked Architectural Decision Records<br>• **`WALKTHROUGH`** — Post-execution verification summaries & change logs |
| **`<scope>`** | `lowercase` | Primary target slice: `all`, `writer`, `viewer`, `spec`, `benchmark` |
| **`<topic-slug>`** | `kebab-case` | Concise 3–6 word hyphenated summary (no spaces, avoids `%20` link encoding). |

---

## 2. Mandatory YAML Frontmatter Header

Prepend every saved log with this lightweight metadata block so both humans and scripts can filter by `type`, `status`, or `conversation_id`:

```yaml
---
log_id: YYYY-MM-DD_01
date: YYYY-MM-DD
type: RESEARCH | AUDIT | PLAN | ADR | WALKTHROUGH
status: draft | pending-approval | approved | executed | superseded
scope: [all]
source_artifact: <original_artifact_filename_if_exported>
conversation_id: <agent_conversation_uuid_if_applicable>
---
```

---

## 3. Chronological Log Index

| Date & Seq | Type | Scope | File | Summary |
| :--- | :---: | :---: | :--- | :--- |
| `2026-11-19_01` | `RESEARCH` | `all` | [`2026-11-19_01_RESEARCH_all_arrowtiles-format-and-ecosystem.md`](2026-11-19_01_RESEARCH_all_arrowtiles-format-and-ecosystem.md) | Ecosystem & specification research across PMTiles v3, Apple Embedding Atlas, Parquet row-group streaming (`parquet-wasm`/`hyparquet`), and Three.js WebGPU buffer lifecycles. |
| `2026-11-19_02` | `AUDIT` | `all` | [`2026-11-19_02_AUDIT_all_deep-code-review-phases-0-7.md`](2026-11-19_02_AUDIT_all_deep-code-review-phases-0-7.md) | Line-by-line code review of `duckdb-arrowtiles` and `deepgraph-arrowtiles-sandbox` verifying handoff claims and uncovering 10 correctness, determinism, memory, and security findings. |
| `2026-11-19_03` | `AUDIT` | `all` | [`2026-11-19_03_AUDIT_all_comprehensive-code-review-and-archaeology.md`](2026-11-19_03_AUDIT_all_comprehensive-code-review-and-archaeology.md) | Multi-agent P0–P3 codebase audit + June–October 2026 institutional log archaeology across Rust/PyO3, DuckDB SQL, WGSL compute atomics, Vite range server, and Playwright CI. |
| `2026-11-19_04` | `RESEARCH` | `all` | [`2026-11-19_04_RESEARCH_all_ecosystem-format-duckdb15-and-licensing.md`](2026-11-19_04_RESEARCH_all_ecosystem-format-duckdb15-and-licensing.md) | 2025–2026 deep research across WebGPU scatter engines, PMTiles vs. HTTP-range Parquet vs. Lance/Vortex/MLT/COPC, DuckDB 1.5+ C-API Rust `CopyFunction`, and decoupled open-spec licensing. |
| `2026-11-19_05` | `PLAN` | `all` | [`2026-11-19_05_PLAN_all_merged-consensus-revival-plan.md`](2026-11-19_05_PLAN_all_merged-consensus-revival-plan.md) | Approved merged consensus revival plan (Phases 0–8, updated with `D7`, `D7a`, `D11` embeddable npm library + demo app architecture, and `⛔ D12`). |
| `2026-11-19_06` | `WALKTHROUGH` | `all` | [`2026-11-19_06_WALKTHROUGH_all_phase-1-spec-package-and-viewer.md`](2026-11-19_06_WALKTHROUGH_all_phase-1-spec-package-and-viewer.md) | Phase 1 completion walkthrough: `SPEC.md` v0.1, `arrowtiles/` PyO3 package, validator/reader, `<20 MiB` sample builder (`31 passed` post-hotfix), and Phase 1b WebGPU viewer compatibility (`0` console/page errors). |
| `2026-11-19_07` | `WALKTHROUGH` | `all` | [`2026-11-19_07_WALKTHROUGH_all_phase-2-deterministic-bucketer-and-completeness.md`](2026-11-19_07_WALKTHROUGH_all_phase-2-deterministic-bucketer-and-completeness.md) | Phase 2 completion walkthrough: zero-atomic 2-stage deterministic bucketer (`25.3%` faster on 100M Gaia rows: `56.39s` vs. `75.50s`), single-pass preflight, `D7a` `dropped_columns`, full `--resume` fingerprint, `44 passed` pytest suite, byte-identical 2.84M LMSys SHA-256, and `16 MiB`/`64 MiB`/`413` Vite range rules. |
| `2026-11-20_01` | `WALKTHROUGH` | `all` | [`2026-11-20_01_WALKTHROUGH_all_phase-3-explicit-priority-and-sampling.md`](2026-11-20_01_WALKTHROUGH_all_phase-3-explicit-priority-and-sampling.md) | Phase 3 completion walkthrough (paused at `⛔ D7`): portable `SplitMix64` default random priority (`48 passed` pytest suite), `--preset gaia` (`phot_g_mean_mag ASC` + dual-schema support), viewer HUD priority/sampling telemetry, and full 2.84M-row LMSys `even_coverage` vs. `proportional` WebGPU visual comparison. |
| `2026-11-20_02` | `WALKTHROUGH` | `all` | [`2026-11-20_02_WALKTHROUGH_all_phase-4-parquet-benchmark-and-log-density.md`](2026-11-20_02_WALKTHROUGH_all_phase-4-parquet-benchmark-and-log-density.md) | Phase 4 completion walkthrough (paused at `⛔ D8/D9/D10`): `D7` locked (`proportional` + `25,000` generic `tile_capacity`), viewer log-density categorical tone mapping (`clusters_14`), `SLO` cold-vs-warm diagnosis, and 5-run 100M-row Gaia + 2.84M LMSys `.arrowtiles` vs. sorted Parquet benchmark (`docs/BENCHMARK_parquet_vs_arrowtiles.md`). |
| `2026-11-20_03` | `WALKTHROUGH` | `all` | [`2026-11-20_03_WALKTHROUGH_all_phase-5a-library-refactor-and-api-draft.md`](2026-11-20_03_WALKTHROUGH_all_phase-5a-library-refactor-and-api-draft.md) | Pre-5a follow-ups & Phase 5a completion walkthrough (paused for `docs/API.md` & `⛔` dep/dead-code review): locked `D8`/`D9`/`D10`, sparse `UTINYINT` fix (`49 passed`), 5-run `50 ms`/`50 Mbps` WAN benchmark + `scripts/bench/`, pure `D11` library split (`main.ts` `112` lines, `0` boundary leaks), and `docs/API.md` draft. |
| `2026-11-20_04` | `WALKTHROUGH` | `all` | [`2026-11-20_04_WALKTHROUGH_all_phase-5b-compute-only-rtc-and-api-lock.md`](2026-11-20_04_WALKTHROUGH_all_phase-5b-compute-only-rtc-and-api-lock.md) | Phase 5b completion walkthrough (paused for review before Phase 6): `D9` Compute-Only direct `GPUBuffer` `TileGpuStore` (`5.2 MB` active VRAM, `Scatterplot`/`WebGPUAdapter` retired) + 2s WGSL axis transitions, `D10` race-free `2 × u32` (`8 B/px`) split-by-mode log-density & `16-bit` optical shaders, CPU `Float64` `RTC` deep zoom, `0` retained CPU tile buffers, `Z=0..2 > 10 MiB` writer warning (`50 passed`), and sealed `Deepgraph` public API (`0` WebGPU/console errors). |
| `2026-11-21_01` | `WALKTHROUGH` | `all` | [`2026-11-21_01_WALKTHROUGH_all_phase-6-three-removal-and-vram-lifecycle-gate.md`](2026-11-21_01_WALKTHROUGH_all_phase-6-three-removal-and-vram-lifecycle-gate.md) | Phase 6 completion walkthrough (paused for review before Phase 7): removed `three`/`@types/three` (`-64.4%` bundle to `364.78 kB` / `94.09 kB` gzip, direct `GPUDevice` + `device.destroy()`), `64`-level numeric Mode 1 precision, superseded `load()` `AbortError`, CLI `nargs="+"` (`51 passed`), committed `scripts/verify_phase5b.mjs`, and passed all 5 real-GPU `__gpuStats` VRAM/device/CPU lifecycle gates (`3 passed` Playwright specs). |
| `2026-11-21_02` | `WALKTHROUGH` | `all` | [`2026-11-21_02_WALKTHROUGH_all_phase-7-gpu-picking-layer-and-zero-shimmer.md`](2026-11-21_02_WALKTHROUGH_all_phase-7-gpu-picking-layer-and-zero-shimmer.md) | Pre-Phase-7 hygiene & Phase 7 completion walkthrough (paused for review before Phase 8): moved `gpuStats` out of library, `0.0000%`-shimmer `1,024`-level numeric Mode 1, `powerPreference` Intel-iGPU guard, race-free `1 KB` GPU `PickingLayer` + standalone `.arrowtiles` `row_id` decode (exact `ArrowTilesReader` parity on `gaia_sample` & `lmsys_sample`, `rowIdBigInt` > `2^53 - 1`, oversize chunk pass) + plain-WebGPU `HighlightOverlay` (`0` leaks). |
| `2026-11-21_03` | `WALKTHROUGH` | `all` | [`2026-11-21_03_WALKTHROUGH_all_phase-8-library-packaging-and-license-audit.md`](2026-11-21_03_WALKTHROUGH_all_phase-8-library-packaging-and-license-audit.md) | Pre-Phase-8 hover hardening & Phase 8 final walkthrough (stopped at `⛔ D12`): compressed pick LRU + 1-tile worker cache + instant GPU hover ring (`<= 1` Range req across 20 cold hovers), Vite ES-module `dist/index.js` (`98.5 kB` gzip, `lil-gui` in `devDependencies`, inlined worker `zstd.wasm`), TS 6.0 `.d.ts` external `bundler` + `nodenext` gate, pure public-API demo (`0` deep imports), `examples/embed.html`, and read-only third-party license audit. |
| `2026-11-21_04` | `WALKTHROUGH` | `all` | [`2026-11-21_04_WALKTHROUGH_all_phase-8b-multiscale-hdr-and-apache2-packaging.md`](2026-11-21_04_WALKTHROUGH_all_phase-8b-multiscale-hdr-and-apache2-packaging.md) | `D12b` Apache-2.0 licensing + `SPEC.md` `v0.1` `"tiling": "quadtree-2d"` (`52 passed`), Phase 8b zero-shimmer linear HDR Mode 0/3 resolve + multiscale sizing (`Z=10` LMC `28.5 → 114.9`, M31 `p99 52 → 172`, `Z=2/3` FPS `+2.7%/+6.2%`, `0.0000%` shimmer), and Phase 8c externalized `dist/index.js` (`47.4 kB` gzip) + `dist/standalone.js` + real Vite consumer app gate + `RowAttributeResolver` `AbortSignal` (`3 passed` Playwright specs on Intel iGPU). |
| `2026-11-21_05` | `WALKTHROUGH` | `viewer` | [`2026-11-21_05_WALKTHROUGH_viewer_phase-8b-visual-comparison-and-tuning.md`](2026-11-21_05_WALKTHROUGH_viewer_phase-8b-visual-comparison-and-tuning.md) | Restored exact pre-8b `R16 / G16 / B16` optical RGB pipeline (`0.0000` pixel diff at `Z=2` & `Z=3` `zoom=2.17`, `0.0166` at `LMC Z=7` `zoom=36`, `0.0000%` shimmer) + `zoom > 36` deep-zoom rescue (`LMC Z=8/10`, `M31`, `M33`), `46.6 kB` / `100.0 kB` gzip builds, and pre-publish `SPEC.md` `0.x` minor-version & `required_features` gates (`53 passed` pytest, `3 passed` Playwright). |
| `2026-11-21_06` | `RESEARCH` | `all` | [`2026-11-21_06_RESEARCH_all_2-5d-and-octree-tiling.md`](2026-11-21_06_RESEARCH_all_2-5d-and-octree-tiling.md) | Archaeological code review of June 2026 2.5D/octree spikes + competitive landscape & `v0.2` 2.5D pitch/bearing extrusion → `v0.3` `"tiling": "octree-3d"` volumetric PMTiles blueprint. |
| `2026-11-21_07` | `RESEARCH` | `all` | [`2026-11-21_07_RESEARCH_all_post-v0-1-format-improvements.md`](2026-11-21_07_RESEARCH_all_post-v0-1-format-improvements.md) | Post-`v0.1` roadmap research: pre-publish `0.x` minor-version & `required_features` gates, `Float64 → Float32` guarded downcast, single-file column groups via PMTiles `tile_id` subspaces, `"tile_stats"`, WGSL predicate cross-filtering, `anywidget`, and streaming `read_arrowtiles`. |
| `2026-11-21_08` | `ADR` | `all` | [`2026-11-21_08_ADR_all_d12a-package-and-repo-naming.md`](2026-11-21_08_ADR_all_d12a-package-and-repo-naming.md) | Locked `D12a` package & repository naming: `arrowtiles` on PyPI / GitHub (`kai-erlenbusch/arrowtiles`), `deepgraph` on npm / GitHub (`kai-erlenbusch/deepgraph`), and `pydeepgraph` reserved for future Python/Jupyter widgets (`"private": true` held pending `D12c`). |
| `2026-11-22_01` | `PLAN` | `all` | [`2026-11-22_01_PLAN_all_repo-cleanup-and-documentation.md`](2026-11-22_01_PLAN_all_repo-cleanup-and-documentation.md) | Two-phase pre-release plan covering dead-file & disk cleanup, chronological `logs/` bootstrap, CI alignment, `AGENTS.md`, and `v0.1.0` documentation overhaul across `deepgraph` and `arrowtiles`. |
| `2026-11-22_02` | `WALKTHROUGH` | `all` | [`2026-11-22_02_WALKTHROUGH_all_repo-cleanup-and-documentation.md`](2026-11-22_02_WALKTHROUGH_all_repo-cleanup-and-documentation.md) | Executed Phase A & B repo cleanup (~32.5 GB disk reclaimed, `logs/` & CI aligned) and `v0.1.0` `AGENTS.md` + `README.md` overhaul (`53 passed` pytest, `3 passed` Intel-iGPU E2E). |
| `2026-11-22_03` | `WALKTHROUGH` | `all` | [`2026-11-22_03_WALKTHROUGH_all_stage-2a-github-renames-ci-and-duckdb2.md`](2026-11-22_03_WALKTHROUGH_all_stage-2a-github-renames-ci-and-duckdb2.md) | Completed `D12c` Stage 2a GitHub renames (`arrowtiles` + `deepgraph`), 5-OS `abi3` wheel/sdist dry-run, `pmtiles` crate pruning, and DuckDB `2.0.1` canonical `NULL`-slot IPC determinism fix (`53 passed`, `0` warnings). |
| `2026-11-22_04` | `PLAN` | `writer` | [`2026-11-22_04_PLAN_writer_pre-v0-1-pandas-index-and-float32-polish.md`](2026-11-22_04_PLAN_writer_pre-v0-1-pandas-index-and-float32-polish.md) | Pre-`v0.1.0` writer polish plan: automatic `__index_level_<N>__` omission and guarded `Float64 → Float32` payload attribute downcasting (`--keep-float64`). |
| `2026-11-22_05` | `WALKTHROUGH` | `writer` | [`2026-11-22_05_WALKTHROUGH_writer_pre-v0-1-pandas-index-and-float32-polish.md`](2026-11-22_05_WALKTHROUGH_writer_pre-v0-1-pandas-index-and-float32-polish.md) | Implemented `__index_level_<N>__` pruning, guarded `Float64 → Float32` downcast (`-40.2%` LMSys archive size), and deterministic Windows `mmap` teardown (`59 passed`, `0` warnings). |
| `2026-11-22_06` | `ADR` | `all` | [`2026-11-22_06_ADR_all_d12b-split-licensing-cc-by-nc-and-apache2.md`](2026-11-22_06_ADR_all_d12b-split-licensing-cc-by-nc-and-apache2.md) | Amended `D12b` to split ecosystem licensing (`arrowtiles` = `Apache-2.0`, `deepgraph` = `CC-BY-NC-4.0` + commercial license via `erlenbusch@uchicago.edu`, copyright Kai Erlenbusch). |
