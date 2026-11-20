# ArrowTiles & DeepGraph Revival — Progress Log (2026-11)

## 2026-11-19 — Phase 0: Make the work safe (no behaviour changes)

- **Done:**
  1. Read `D:\exploratory\duckdb-extension\HANDOFF_2026-11-19_arrowtiles-revival.md`, `START_HERE.md`, and `README.md` in both repositories, and completed a full line-by-line code review + ecosystem/format research audit (`logs/2026-11-19_01_RESEARCH_all_arrowtiles-format-and-ecosystem.md` and `logs/2026-11-19_02_AUDIT_all_deep-code-review-phases-0-7.md`).
  2. Created branch `revival/2026-11-wip` from `main` in both repositories:
     - **Writer (`duckdb-arrowtiles`):** Updated `.gitignore` to ignore `.venv/`, `venv/`, `playwright-report/`, `test-results/` alongside data files (`*.arrowtiles`, `*.parquet`, `*.feather`, `*.pmtiles`). Committed uncommitted Oct 2026 work as `fcf2950` (`"WIP snapshot from Oct 2026, untested"`, 5 files, `+350 / -318`).
     - **Viewer (`deepgraph-arrowtiles-sandbox`):** Updated `.gitignore` to ignore `playwright-report/`, `test-results/`, `.pytest_cache/`, `data/`, and root/nested `*.arrowtiles`, `*.pmtiles`, `*.parquet`, `*.feather`. Committed uncommitted Oct 2026 work including `src/core/ComputeRasterizer.ts`, `tests/`, `playwright.config.ts`, and `.github/workflows/perf-ci.yml` as `e09fd85` (`"WIP snapshot from Oct 2026, untested"`, 15 files, `+3,425 / -468`).
  3. Copied and adapted useful pipeline/metadata tests out of `archive/tests/` (leaving `archive/tests/` completely untouched) into tracked `tests/` (`conftest.py`, `test_synthetic_pipeline.py`, `test_pmtiles_metadata.py`, `test_lmsys_pipeline.py`, `test_gaia_pipeline.py`, `test_legacy_duckdb_extension.py`) plus `pytest.ini`. Added `conftest.py` guard so `pytest` loads the `.venv` extension built by `maturin develop --release` rather than the stale untracked `2026-07-22` `arrowtiles_core.pyd` sitting in the repo root.
  4. Created local `.venv` (`--system-site-packages`) in `duckdb-arrowtiles` and built/installed the Rust PyO3 engine in release mode via `maturin develop --release`.
  5. Verified viewer TypeScript compilation (`npx tsc --noEmit`) and runtime HTTP serving (`npm run dev` HTTP 200 + `arrowtilesFastRangePlugin` HTTP 206 `Partial Content`).

- **Toolchain Versions Recorded (2026-11-19):**
  - **Node.js:** `v24.12.0`
  - **npm:** `11.6.2`
  - **rustc:** `rustc 1.96.1 (31fca3adb 2026-06-26)`
  - **cargo:** `cargo 1.96.1 (356927216 2026-06-26)`
  - **maturin:** `maturin 1.14.1`
  - **Python:** `Python 3.14.2` (`C:\Users\erlen\AppData\Local\Programs\Python\Python314\python.exe`; venv at `D:\exploratory\duckdb-extension\duckdb-arrowtiles\.venv`)
  - **duckdb (Python):** `1.5.3` (with `pyarrow 24.0.0`, `pmtiles 3.7.0`, `pytest 9.1.1`)
  - **Chrome:** `157.0.8103.80` (`C:\Program Files\Google\Chrome\Application\chrome.exe`)

- **Evidence:**
  - **Viewer Type-Check:**
    - Command: `Set-Location -LiteralPath "D:\exploratory\duckdb-extension\deepgraph-arrowtiles-sandbox"; npx tsc --noEmit`
    - Output: `exit code 0` (0 errors).
  - **Viewer Dev Server & Range Endpoint:**
    - Command: `npm run dev` + `curl.exe -s -I "http://localhost:5173/"` + `curl.exe -s -D - -o NUL -H "Range: bytes=0-126" "http://localhost:5173/test.arrowtiles"`
    - Output: `HTTP/1.1 200 OK` (`Content-Type: text/html`) on `/`; `HTTP/1.1 206 Partial Content` (`Content-Range: bytes 0-126/2957198`, `Content-Length: 127`) on `/test.arrowtiles`.
  - **Writer Release Build:**
    - Command: `$env:VIRTUAL_ENV = "D:\exploratory\duckdb-extension\duckdb-arrowtiles\.venv"; Set-Location -LiteralPath "D:\exploratory\duckdb-extension\duckdb-arrowtiles\arrowtiles-engine"; maturin develop --release`
    - Output: `Finished 'release' profile [optimized] target(s) in 2m 09s`, `Built wheel for abi3 Python >= 3.9`, `Installed arrowtiles_core-0.1.0` (`exit code 0`).
  - **Writer Pytest Suite:**
    - Command: `& "D:\exploratory\duckdb-extension\duckdb-arrowtiles\.venv\Scripts\python.exe" -m pytest -v`
    - Output: `6 passed, 1 skipped in 2.52s` (`test_gaia_batch_schema_and_hammer_smoke_build`, `test_lmsys_parquet_schema_columns`, `test_lmsys_smoke_build_on_sample`, `test_read_lmsys_pmtiles_metadata_and_schema`, `test_read_gaia_pmtiles_metadata_and_schema`, `test_build_generic_synthetic_roundtrip` all PASSED; `test_legacy_duckdb_loadable_extension` SKIPPED).

- **Not done / failed:**
  - **Viewer Playwright E2E (`npx playwright test --reporter=list`):** Failed at browser launch (`exit code 1`, `3ms`) with:
    `Error: browserType.launch: Executable doesn't exist at C:\Users\erlen\AppData\Local\ms-playwright\chromium_headless_shell-1228\chrome-headless-shell-win64\chrome-headless-shell.exe`
    (`ms-playwright` currently has builds `1208`, `1243`, and `1255`, plus system Chrome `157.0.8103.80`). Per Phase 0 rules (no behaviour/config changes) and Phase 6 plan (which replaces the SwiftShader headless test with a real-GPU Chrome test), we recorded this failure rather than modifying `playwright.config.ts` in Phase 0.
  - **`git push`:** Not run (stopped at ⛔ gate per owner guardrail).

- **Questions for owner:**
  1. ⛔ **Git push:** Would you like to keep both `revival/2026-11-wip` branches local for now, or approve `git push -u origin revival/2026-11-wip` on one/both repos?
  2. **Stale root binary (`duckdb-arrowtiles\arrowtiles_core.pyd`):** An untracked `arrowtiles_core.pyd` from `2026-07-22` sits in the writer repo root (`sys.path[0]`), which shadows `.venv`/`site-packages` if someone runs `python arrowtiles.py` directly from the repo root (`tests/conftest.py` already bypasses it for `pytest`). May I move `D:\exploratory\duckdb-extension\duckdb-arrowtiles\arrowtiles_core.pyd` into `archive/` (or delete it)?
  3. **Phase 1 go-ahead & Y-axis / Dictionary conventions:** In our deep code review, we found two key spec details to lock cleanly in Phase 1's `docs/SPEC.md`:
     - **Y-axis direction:** `build_gaia` currently writes top-down `y_norm` (`0` = North/top) while `build_generic` writes bottom-up `y_norm` (`0` = `min_y`), causing generic datasets to render inverted unless `Flip Y` is toggled. Should v0.1 standardize `y_u16` to match PMTiles/Web-Mercator top-down tile coordinates (`y_norm = 0` at `max_y` / North, `y_norm = 1` at `min_y` / South, matching tile `ty = 0` at top), or Cartesian bottom-up? (Recommended: **top-down matching PMTiles tile row `y`**, so tile `(z, x, y)` and intra-tile `y_u16` point in the exact same direction!)
     - **Dictionary columns in v0.1:** Currently `categorical_columns` emit a global DuckDB `ENUM` -> Arrow `DictionaryBatch` inside each tile payload, which works end-to-end in both Python and JS `apache-arrow`. Are you happy codifying "optional dictionary-encoded columns allowed when using a file-global dictionary per column" in `SPEC.md` v0.1?

## 2026-11-19 — Phase 0: independent verification (reviewer: Claude Code)

Re-ran every Phase 0 acceptance check myself instead of trusting the entry above, and reviewed `arrowtiles.py` (442 lines) and `arrowtiles-engine/src/lib.rs` (610 lines) in full. No repo source file was changed. Probe outputs went to a scratch folder outside both repos.

- **Done:**
  1. **Handoff file missing.** `D:\exploratory\duckdb-extension\HANDOFF_2026-11-19_arrowtiles-revival.md` (20,379 bytes) and `AGENT_PROMPT_2026-11-19_arrowtiles-revival.md` were on disk at 18:12 (per the earlier agent's directory listing) but were gone at 18:40. I recovered the handoff verbatim (355 lines) from the earlier agent's `read_file` output into a **new** file: `D:\exploratory\duckdb-extension\HANDOFF_2026-11-19_arrowtiles-revival.RECOVERED.md`. I could not recover `AGENT_PROMPT_*`.
  2. **No uncommitted work was lost by the WIP commits.**
     - At 18:12 the viewer showed `M` on 13 tracked files. Four of them (`src/counter.ts`, `src/global.d.ts`, `src/assets/typescript.svg`, `src/assets/vite.svg`) are not in `e09fd85`, yet the tree is clean. So they were stat-only changes (line endings) with no content diff.
     - The line counts reconcile: tracked +1,691/−468, plus new files +1,724 (`ComputeRasterizer.ts` 1,587, `memory-leak.spec.ts` 67, `perf-ci.yml` 40, `playwright.config.ts` 30, `compute_test.mjs` 0), plus `.gitignore` +10. That gives **+3,425/−468, which equals `e09fd85`**.
     - In the writer, the handoff counted +344/−318 and `fcf2950` has +350/−318. The 6 extra lines are `.gitignore` entries the Phase 0 agent added before committing.
  3. Neither repo tracks any `*.arrowtiles`, `*.parquet`, `*.pmtiles`, `*.feather` or `*.pyd` file (`git ls-files` filtered: empty in both).

- **Evidence (acceptance checks):**

  | Check | Command | Result |
  | :--- | :--- | :--- |
  | Trees clean on WIP branch | `git -C <repo> status --short --branch` | Both `## revival/2026-11-wip`, no entries. Re-checked after all runs below. |
  | Viewer type-check | `npx tsc --noEmit` (tsc 6.0.3) | exit 0, 5.9 s |
  | Viewer runs | `npm run dev -- --port 5199 --strictPort`, then `curl.exe -I` and a `Range: bytes=0-126` request | `/` → 200. `/test_categorical.arrowtiles` → `206 Partial Content`, `Content-Range: bytes 0-126/2683126`. Server stopped afterwards (no listener on 5199). |
  | Writer builds | `maturin develop --release` in `arrowtiles-engine` (venv active) | exit 0, `Finished release profile in 1.15s` (incremental), `Installed arrowtiles_core-0.1.0` |
  | Writer tests | `.venv\Scripts\python.exe -m pytest -v -rs -p no:cacheprovider` | **6 passed, 1 skipped in 3.06 s**. The skip is `test_legacy_duckdb_loadable_extension`, which always skips (a placeholder, not data-gated). |
  | Which engine the tests load | `python -I -c "import arrowtiles_core; print(arrowtiles_core.__file__)"` with the venv Python | `.venv\Lib\site-packages\arrowtiles_core\__init__.py`, built 2026-11-19 |
  | Toolchain | `node -v`, `npm -v`, `rustc/cargo/maturin --version`, Chrome `VersionInfo` | Matches the entry above: Node 24.12.0, npm 11.6.2, rustc/cargo 1.96.1, maturin 1.14.1, Python 3.14.2, duckdb 1.5.3, pyarrow 24.0.0, Chrome 157.0.8103.80 |
  | Playwright failure cause | List `%LOCALAPPDATA%\ms-playwright`; read `node_modules\playwright-core\package.json` | playwright-core **1.61.1** is installed, but only browser builds 1208/1243/1255 are present. That matches the reported "missing `chromium_headless_shell-1228`". Not fixed: `npx playwright install` downloads files and needs owner OK. Phase 6 replaces this test anyway. |

- **Writer behaviour probes.** Script: `probe_writer.py` in the session scratchpad; inputs were synthetic only. These are a baseline for Phases 1–2, not changes.

  | # | What | Result |
  | :--- | :--- | :--- |
  | P1 | DuckDB NaN semantics | `MAX(1, 2, NaN) = NaN`; NaN passes `IS NOT NULL`. **Confirms** that one NaN coordinate makes `range_x` NaN in `build_generic`, and then every row lands at (0.5, 0.5) via `lib.rs:155`. |
  | P2 | `SELECT *, … AS x_norm` when the input already has `x_norm` | DuckDB renames the new column to `x_norm_1`. The bucketer then reads the **raw** `x_norm`, so normalization is silently discarded. The CLI defaults (`--x-col x_norm`) trigger this. |
  | P3 | Coordinate round trip and tile-ID consistency (50K rows, `build_generic`) | in = out = 50,000 rows. Max decode error is 7.629e-6 tile units, within the u16 half-step (7.630e-6). The directory `(z,x,y)` agrees with the per-row `z` column (0 mismatches), so `fast_hilbert` tile IDs match the PMTiles reader's IDs. Header: `tile_type=UNKNOWN`, `compression=ZSTD`, `clustered=True`. |
  | P3y | y direction | `build_generic` puts the **smallest** raw y in tile row `ty=0` (the top, in PMTiles convention). So generic data is upside down relative to Cartesian plots. **Confirmed.** |
  | P4 | Same input built twice (50K rows, many priority ties) | sha256 `c367432b…` vs `bfaccc34…`: **different**. All 21 tiles differ in membership. |
  | P5 | Same input built twice, **unique** priorities (300K rows, 70% clustered, `max_capacity=256`, `max_zoom=14`) | Not byte-identical. **3,911 of 4,599 tiles** contain different rows. The Rust `into_par_iter` claim race alone breaks reproducibility; SQL ties are a second, separate cause. |
  | P6 | Priority contract at capacity levels (z ≥ 7) on the P5 output | 9,429 deeper tiles checked. **3,059 violate** "a full tile holds higher-priority rows than any row pushed below it". |

- **Corrections to the earlier audit** (`logs/2026-11-19_02_AUDIT_…`):
  1. **The `z_indices: HashMap` iteration order does not affect output** (`lib.rs:245–286`). Each zoom level has its own buffer and file, and rows within a level are pushed in input order. Drop this item from Phase 2. The real causes are the claim race (P5) and unbroken SQL ties (P4).
  2. **"Raw x/y columns duplicated in every tile"** is half right. The bucketer drops the columns it is given (`lib.rs:75–80`, i.e. `x_norm`/`y_norm`). For `build_generic`, the **source** columns (for example `x_umap`) do stay in every tile. The name collision is worse than stated (see P2).
  3. **New: the handoff's sampling contract conflicts with `even_coverage`.**
     - At z ≤ 6 the rule is one point per grid cell (`lib.rs:182–189`). A low-priority row in an empty cell is kept at z=0 while a high-priority row in a crowded cell is pushed deeper. That is by design.
     - So Phase 1's "a tile holds the highest-priority rows in its area" and Phase 2 test (d) must be stated **per grid cell** for `even_coverage`, and **per tile** only for `proportional`. Otherwise test (d) will fail on a correct writer.
  4. **New: `--resume` cannot work with default settings.**
     - Without `--temp-dir`, partitions go to a random `./duckdb_temp_XXXX` (`arrowtiles.py:30`), but `--resume` looks in `./duckdb_temp` (`arrowtiles.py:423–424`).
     - `TemporaryDirectory` also deletes the "preserved" partitions when the builder object is garbage-collected.
     - Resume never checks that the partitions came from the same input and parameters.
  5. **New, minor issues:**
     - A custom metadata key named `arrow_schema` would overwrite the real schema (`lib.rs:445–452`).
     - Input paths are pasted into SQL unescaped (`read_parquet('{input_parquet}')`).
     - `build_generic` crashes if a coordinate column is all-NULL (`- None` ends up in the SQL).
     - Leaf-tile size is unbounded (`lib.rs:180`). `chunk_buffer_limit` is a flush threshold, not a per-tile cap as the README implies.
  6. **New: the dev server allows path traversal.**
     - `vite.config.ts:45` URL-decodes the path, then `:55–56` calls `path.resolve(cwd, 'public', relPath)` with no containment check. With `host: true` (`:110`), any `*.arrowtiles` file on the drive is readable over the LAN while the server runs.
     - Requesting `/..%2F..%2Fduckdb-arrowtiles%2Ftest.arrowtiles` returned `206`.
  7. **Environment hazard: three different `arrowtiles_core` builds exist.**
     - Repo root `.pyd` (2026-07-22); system Python `site-packages` (2026-07-19); `.venv` (2026-11-19).
     - Both older ones predate the Oct `lib.rs` changes. `python arrowtiles.py` run from the repo root, or with system Python, silently uses an old engine.
  8. **Test portability:**
     - The tracked tests hardcode `D:\exploratory\…` paths.
     - They import `compression.zstd`, which exists only in Python ≥ 3.14, while the README says 3.10+.
     - Fine for local Phase 0, but they will not run in CI as-is.
  9. **Fact check:** `public\gaia_full.arrowtiles` is **31.0 GB** (31,016,634,401 bytes), not the 15.8 GB stated in the handoff and both READMEs. A second 30.3 GB `public\gaia.arrowtiles` also exists. I did not touch either file.

- **Not done / failed:**
  - Playwright E2E still fails at browser launch (cause above). I did not run `npx playwright install` because it is a download.

- **Independent viewer review** (read-only subagent, which did not see the earlier audit). It read in full: `main.ts`, `Scatterplot.ts`, `WebGPUAdapter.ts`, `ComputeRasterizer.ts` (1,587 lines), `Renderer.ts`, `PMTilesClient.ts`, `pmtiles.worker.ts`, `vite.config.ts`, and the test and CI config. "Spot-checked" below means I re-read the code myself.
  - **Handoff §4.3–4.5 claims:**
    - All confirmed, except that only 8 of the 17 shared `let`s (`main.ts:119–126`) are really shared. The other 8 (`main.ts:735–744`) are used only by the render loop.
    - The memory test is weaker than the handoff says. At the default zoom only 21 tiles load, and z0–2 are pinned against eviction (`PMTilesClient.ts:539–541`), so eviction can never run. In CI the gitignored `*.arrowtiles` returns 404, so the test pans an empty canvas.
  - **Correction for the Phase 6 fix:** slot geometries share the `position`/`uv` attributes (`Scatterplot.ts:853–854`). A naive `geometry.dispose()` would destroy those shared buffers for every slot. Compute-only buffers need an explicit `GPUBuffer.destroy()`.
  - **HIGH (spot-checked): additive and mean-field atomics can overflow** (`ComputeRasterizer.ts:475–543`).
    - Each splat loads the word, checks the guard, then calls `atomicAdd`. That sequence is not atomic, so the saturation guards only hold for sequential adds.
    - Additive mode: 3 or more concurrent adds of up to 256 can overflow the 10-bit B field (bits 22–31), and the overflow is lost off the top of the word. 7 or more concurrent adds can carry R into G.
    - Mean-field mode: concurrent weights can push W above 1025, and then the 20-bit sum carries into the weight field.
    - This is likely in dense regions at low zoom.
  - **HIGH (spot-checked): Arrow nulls become 0.**
    - The worker reads `.values` and ignores the validity bitmap (`pmtiles.worker.ts:139, 156`).
    - Writer side (my check): DuckDB NULLs stay Arrow nulls; they are not NaN. So nullable Gaia columns (`radial_velocity`, `teff_gspphot`, `parallax`, `pm*`) render as 0.0.
  - **HIGH (spot-checked): `loadDataset` race.**
    - The old client is destroyed at `main.ts:138` but stays assigned until `:199`, across the awaits at `:142`/`:144`. Meanwhile the render loop keeps querying the dead client.
    - A second drag-and-drop during a load creates two clients and leaks the first one's workers and GUI.
  - **HIGH: VRAM and CPU grow per active field.** Each field gets a 1 MiB GPU buffer plus a 1 MiB CPU array per slot, and neither is ever freed. The on-screen VRAM number is made up (`tiles*2.4`, `main.ts:846`).
  - **MED:**
    - Flip Y gets out of sync with tile culling after the HR lens (`main.ts:289` vs `:323`).
    - Failed tiles are retried with no backoff or negative cache (`PMTilesClient.ts:699–704`).
    - The compute path does its coordinate math in f32, so points snap to a grid above zoom ~2^13 (`ComputeRasterizer.ts:598–615`). The mesh path computes in f64 and is fine.
    - `p-queue.clear()` leaves promises pending forever.
    - A field change on datasets with more than 12 columns clears every tile.
  - **LOW:**
    - Worker error paths: no `reqId` on init failure, and no `onerror`.
    - Root bounds are chosen by filename (`'gaia'` substring).
    - Overlapping axis transitions start two animation loops.
    - Dead code and deps: `ui.ts`, `counter.ts`, 0-byte `compute_test.mjs`, the `rawPayload` pool (which also retains up to 50 unused buffers), Sentry, `gl-matrix`, `stats.js`. `fflate` is imported but only installed transitively.
  - **Viewer questions answered from the writer side:**
    - Every row is in exactly one tile (P3: in = out), so drawing levels 0..z together is correct.
    - Category dictionaries are file-global (one DuckDB ENUM), so taking the first dictionary seen is safe for `build_generic` files.
    - The y convention is top-down in `build_gaia` and bottom-up in `build_generic` (P3y).
  - **Picking (Phase 7) prerequisites found:**
    - There is no row-ID column.
    - The compute path scrambles the row index, though invertibly within 2,048-row blocks.
    - The CPU attribute mirrors are all zeros.
    - The worker drops columns it was not asked for.
    - Rows past 262,144 in a leaf tile are dropped.
    - Both shaders add hash-based jitter.
  - **Splitting `main.ts` (Phase 5) prerequisites found:**
    - View state lives in three places: `state`, the `current*` lets, and public mutable `Scatterplot` fields (`modeUniform` doubles as an is-Gaia flag).
    - There are `window.*` globals.
    - `animatedEpochKyr` is used at `main.ts:657/662` before its declaration at `:667`.

- **Questions for owner:**
  1. The handoff file disappeared from `D:\exploratory\duckdb-extension\` between 18:12 and 18:40. Was that you? Should the recovered copy become the working reference?
  2. ⛔ `git push` of `revival/2026-11-wip` (both repos): still not run, awaiting your call.
  3. May I move the stale root `duckdb-arrowtiles\arrowtiles_core.pyd` into `archive\`? (Same question as above; I agree with it.) The 2026-07-19 copy in system Python's `site-packages` has the same problem; uninstalling it is your call.
  4. `logs/` is gitignored, so the audit and research files this log cites are not versioned. Should reviews live in tracked `docs/reviews/` instead?


## 2026-11-19 — Phase 0 (finish): cleanup, dev-server hardening, MuniLM logs & portable tests

- **Done:**
  1. **Restored `docs/PROGRESS_2026-11.md` (`D1`):** Ran `git checkout -- docs/PROGRESS_2026-11.md` to restore the 117-line independent verification and P1–P6 baseline probe record from commit `8c04c98` (verified 166 lines prior to appending this entry).
  2. **Archived stale root binary (`D2`):** Moved `D:\exploratory\duckdb-extension\duckdb-arrowtiles\arrowtiles_core.pyd` (`2026-07-22`) to `archive/arrowtiles_core_2026-07-22.pyd` so `sys.path[0]` can no longer shadow `.venv` builds.
  3. **Configured MuniLM `logs/` tracking (`Patch 5`):** Updated `duckdb-arrowtiles/.gitignore` with surgical rules (`logs/*`, `!logs/README.md`, `!logs/20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9]_*.md`), persisted `2026-11-19_03_AUDIT_all_comprehensive-code-review-and-archaeology.md`, `2026-11-19_04_RESEARCH_all_ecosystem-format-duckdb15-and-licensing.md`, and the merged consensus plan `2026-11-19_05_PLAN_all_merged-consensus-revival-plan.md`, and updated `logs/README.md`. Verified `0` historic raw transcript files are staged.
  4. **Hardened Vite range middleware (`deepgraph-arrowtiles-sandbox/vite.config.ts`):** Bound `server.host` to `'127.0.0.1'` by default, wrapped `decodeURIComponent` in `try/catch` (`400`), enforced directory containment via `path.relative` before `Range` evaluation (`403`), capped single range reads to `16 MiB` (`16,777,216` bytes), and revalidated `stat.size` + `stat.mtimeMs` on cached file descriptors.
  5. **Made writer `pytest` suite portable (`duckdb-arrowtiles/tests/`):** Replaced hardcoded `D:\` paths with workspace-relative fixtures + env-var overrides (`ARROWTILES_*`) that cleanly `pytest.skip` when absent, added a cross-Python 3.10–3.14 `zstd_decompress` helper (`compression.zstd` -> `pyarrow` streaming Zstd fallback), and asserted in `conftest.py` (plus explicit `test_arrowtiles_core_loaded_from_venv`) that `arrowtiles_core.__file__` resolves inside `.venv`.

- **Evidence:**
  - **Writer `pytest` Suite:**
    - Command: `& "D:\exploratory\duckdb-extension\duckdb-arrowtiles\.venv\Scripts\python.exe" -m pytest -v -rs -p no:cacheprovider`
    - Output: `7 passed, 1 skipped in 2.09s` (including new `test_arrowtiles_core_loaded_from_venv` + PyArrow Zstd parity check; missing-file fixture override verified `1 passed, 1 skipped in 0.06s`).
  - **Viewer TypeScript Check:**
    - Command: `Set-Location -LiteralPath "D:\exploratory\duckdb-extension\deepgraph-arrowtiles-sandbox"; npx tsc --noEmit`
    - Output: `exit code 0` (0 errors).
  - **Hardened Vite Dev Server Checks (`127.0.0.1:5198`):**
    - Listener check (`Get-NetTCPConnection -LocalPort 5198 -State Listen`): bound exclusively to `127.0.0.1:5198` (not `0.0.0.0`); listener verified closed after shutdown.
    - Traversal with & without `Range` (`curl.exe --path-as-is ... "http://127.0.0.1:5198/..%2F..%2Fduckdb-arrowtiles%2Ftest.arrowtiles"`): `HTTP/1.1 403 Forbidden`.
    - Malformed URL encoding (`curl.exe --path-as-is ... "http://127.0.0.1:5198/%E0%A4%A.arrowtiles"`): `HTTP/1.1 400 Bad Request`.
    - Open-ended range on 31.0 GB archive (`curl.exe -H "Range: bytes=0-" "http://127.0.0.1:5198/gaia_full.arrowtiles"`): `HTTP/1.1 206 Partial Content`, `Content-Range: bytes 0-16777215/31016634401`, `Content-Length: 16777216` (16 MiB cap).
    - Standard 127-byte header range on `test.arrowtiles`: `HTTP/1.1 206 Partial Content`, `Content-Range: bytes 0-126/2957198`, `Content-Length: 127`.

- **Not done / failed:**
  - **`git push`:** Not run (awaiting owner approval per `⛔` guardrail).

- **Questions for owner (before Phase 1):**
  1. **⛔ D6 (Phase 1 samples in Git):** When Phase 1 builds `gaia_sample.arrowtiles`, `lmsys_sample.arrowtiles`, and the edge-case sample (`< 20 MB` each), do you want them kept untracked/generated via script (`samples/` gitignored) or committed to Git?
  2. **Go-ahead for Phase 1:** Ready to start **Phase 1** (`docs/SPEC.md` v0.1, `arrowtiles/` package + `pyproject.toml`, dense `row_id`, `UInt8`/`UInt16` categories, `max_tile_rows` up to `z = 20`, reference `reader`/`validate`, and Phase 1b viewer compatibility + `header.maxZoom` plumbing)?
