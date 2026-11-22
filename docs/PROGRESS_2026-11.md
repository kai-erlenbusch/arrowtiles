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


## 2026-11-19 — Phase 1 (Step 1 checkpoint): `docs/SPEC.md` v0.1 & pre-Phase-1 review guardrails

- **Done:**
  1. **Added post-verification errata headers to tracked audit logs:** Updated `logs/2026-11-19_02_AUDIT_all_deep-code-review-phases-0-7.md` and `logs/2026-11-19_03_AUDIT_all_comprehensive-code-review-and-archaeology.md` with prominent `> [!WARNING]` errata blocks correcting `z_indices` HashMap determinism, single-`u32` atomic overflow, `x_norm` source column behavior, `D4` integer category codes, apparent G-band `abs_m` (`0` rows `<= 0` across 1.35B rows), per-splat ACES+sRGB transfer parity, and dropping `B-13` GIL release.
  2. **Folded all 7 pre-Phase-1 guardrails + `D6` into the consensus plan (`logs/2026-11-19_05_PLAN_all_merged-consensus-revival-plan.md`):**
     - `lib.rs` returns `PyValueError` on unparseable/non-object/reserved-key `custom_metadata`.
     - Exclude `row_id` from automatic GPU attribute pre-requests in `main.ts` + guard `bigint -> Number` in `pmtiles.worker.ts` for any 64-bit integer column.
     - Two-tier capacity (`tile_capacity` at `z < nominal_max_zoom` vs. `max_tile_rows` at `z >= nominal_max_zoom` spilling up to `z = 20`), `PmTilesWriter.max_zoom(actual_max_z)`, and single Hilbert evaluation at `z = 20`.
     - Seed `scatterplot.setDictionaries` from `metadata.stats[col].categories` on load, guard `NaN` in `Scatterplot.ts` alongside `ComputeRasterizer.ts`, and require an explicit deterministic `id_col` for direct `build(input_query=...)` callers.
     - `validate` reports `max_compressed_tile_bytes` and warns/flags against the `16 MiB` range cap.
     - `D6` locked: gitignore `samples/` and generate Gaia/LMSys samples via script + synthetic edge-case sample in `pytest`.
  3. **Authored `docs/SPEC.md` (`v0.1`, 108 lines / ~2.2 pages):** Covers container identity, schema-stripped Arrow IPC framing (no `DictionaryBatch`), top-down `y_norm` + `bounds`, dense `row_id` & `total_rows + dropped_rows == input_rows`, `tile_capacity` vs. `max_tile_rows` spillover to `z = 20`, `proportional` vs. `even_coverage` priority contracts, finite-only `stats`, optional `view` hints, and reserved identifiers.
  4. **Stopped before touching any Phase 1 writer or viewer code** per review checkpoint #7.

- **Evidence:**
  - `docs/SPEC.md` line count: `108` lines (`<= 3` pages target met).
  - Writer `pytest` suite (`-v -rs -p no:cacheprovider`): unchanged (`7 passed, 1 skipped`).
  - Both repositories clean on `revival/2026-11-wip` (zero Python/Rust/TS source files modified in this checkpoint).

- **Questions for owner:**
  1. **Review `docs/SPEC.md`:** Any edits or tightening needed in `docs/SPEC.md` before I implement the Phase 1 writer (`arrowtiles/` package + `lib.rs`), reference reader, validator, sample builder, and Phase 1b viewer compatibility?
  2. **⛔ `git push`:** Let me know if you want `revival/2026-11-wip` pushed as an off-machine backup (note: tracked logs contain local `C:\Users\erlen\...` / `D:\...` paths and session UUIDs if either remote repo is public).


## 2026-11-19 — Phase 1 (finish): `arrowtiles/` v0.1 package, validator, reader, sample builder, and Phase 1b viewer compatibility

- **Done:**
  1. **Packaged `arrowtiles/` (`pyproject.toml` + `arrowtiles._core`):**
     - Added `pyproject.toml` (`module-name = "arrowtiles._core"`, `python-packages = ["arrowtiles"]`, CLI script `arrowtiles = "arrowtiles.__main__:main"`), added `*.pdb` alongside `*.pyd` in `.gitignore`, and removed legacy root `arrowtiles.py`.
     - Built `arrowtiles/_core.pyd` via `maturin develop --release` with **0 compiler warnings** (`set_max_row_group_row_count(Some(100_000))`).
  2. **Upgraded Rust engine (`arrowtiles-engine/src/lib.rs`) to `SPEC.md` v0.1:**
     - Two-tier capacity: `tile_capacity` at `z < nominal_max_zoom` (`even_coverage` `G x G` bitset at `z <= 6` where default `G = isqrt(tile_capacity)`, `proportional` counters otherwise) and `max_tile_rows` at `z >= nominal_max_zoom` spilling overflow up to `z = 20`.
     - Fails cleanly when a `z = 20` tile exceeds `max_tile_rows` unless `allow_oversize_leaves=True` (in which case `metadata.max_tile_rows` records the observed maximum).
     - Single Hilbert evaluation at `z = 20` (`fast_hilbert::xy2h(ix_20, iy_20, 20)`) deriving all coarser levels via 2-bit shifts (`PYRAMID_SIZE_BY_ZOOM[z] + (h_20 >> (2 * (20 - z)))`), guarded by `verify_hilbert_shift_invariants()` across exhaustive `z = 1..5` + 20,000 SplitMix64 samples (`0` violations vs. `pmtiles::TileCoord`).
     - Enforces non-nullable `row_id: UInt64`, `x_u16: UInt16`, `y_u16: UInt16`, `z: UInt8` in the exported IPC `Schema`, rejects `DictionaryType`, rejects unparseable/non-object/reserved-key `custom_metadata` with `PyValueError`, checks monotonic `final_tile_id`, sets `.min_zoom(0).max_zoom(actual_max_z)`, and writes atomically via `<output>.tmp` -> `<output>`.
  3. **Implemented v0.1 Python builder, reference reader, validator, and sample script (`arrowtiles/` + `scripts/build_samples.py`):**
     - `arrowtiles/builder.py`: Deterministic `--temp-dir` (`./duckdb_temp`), removed `allow_unsigned_extensions`, added `close()`/context manager, SQL quote/path escaping, lexicographically sorted `parquet_file_metadata` dense `row_id = base_offset + file_row_number`, explicit `id_col` requirement for custom SQL queries, finite-only coordinate filtering (`dropped_rows`) and finite-only `stats` (`allow_nan=False`), `NULL`/`NaN`-last sorting in both `ASC` and `DESC`, `UInt8` (`1..256`) / `UInt16` (`257..65,535`) integer category encoding (`D4`), top-down `y_norm = (max_y - y) / span_y` (`D3`), internal `__at_*` coordinate/sort aliases avoiding collisions with user `x_norm` columns, and `partitions/manifest.json` for `--resume`.
     - `arrowtiles/reader.py`: `ArrowTilesReader` validating `format`/`version` (rejecting unknown major version, warning on v0.0), vectorized `x_decoded`/`y_decoded` coordinate reconstruction, and optional category label decoding preserving `NULL`s.
     - `arrowtiles/validator.py`: `validate_file` & `python -m arrowtiles validate` verifying PMTiles v3 header (`clustered`, `min_zoom == 0`, `max_zoom == actual_max_z`), v0.1 metadata/schema invariants, streaming tile IPC framing, `sum(tile_rows) == total_rows`, `total_rows + dropped_rows == expected_input_rows`, `<= max_tile_rows`, global `row_id` uniqueness, and reporting `max_compressed_tile_bytes` against the `16 MiB` HTTP range cap.
     - `scripts/build_samples.py`: Generates gitignored `< 20 MB` v0.1 samples under `samples/` (`gaia_sample.arrowtiles` at `4.26 MiB` / `149,942` full-sky stars; `lmsys_sample.arrowtiles` at `0.77 MiB` / `100,000` rows).
  4. **Implemented Phase 1b Viewer Compatibility (`deepgraph-arrowtiles-sandbox/src/`):**
     - `PMTilesClient.ts`: Replaced hardcoded `z <= 14` cap with `archiveMaxZoom` read from the PMTiles header (`actual_max_z` on v0.1; `14` fallback when legacy v0.0 header reports default `22`) and capped non-spatial quadtree traversal (`!isSpatialX && !isSpatialY`) at `z <= 2` (`F-07`).
     - `pmtiles.worker.ts`: Decoded Arrow `nullBitmap -> NaN` (`chunk.nullCount > 0`, respecting `chunk.offset`), filled missing columns with `NaN`, and converted `BigInt64Array`/`BigUint64Array` values via `Number(...)`.
     - `Scatterplot.ts` & `ComputeRasterizer.ts`: Expanded categorical palette from 10 to 64 distinct colors + deterministic golden-ratio HSV fallback for codes `>= 64`, guarded `NaN` / `< 0` categorical values to neutral gray `(0.42, 0.42, 0.46)` before clamping (fixing `NULL` categories rendering as Category `0` in both Compute Atomic and Hardware Instanced engines; used TSL `mix` rather than `select` around `TextureNode` to avoid a Three.js `0.172.0` `generateUV` conditional-setup bug).
     - `main.ts`: Added `format`/`version` check (warning on v0.0, rejecting unknown major), true aspect ratio from `metadata.bounds`, nested `metadata.view` support, `metadata.stats[col].categories` seeding on load, exclusion of `'row_id'`/`'z'`/`Utf8` from `schemaFields`, automatic `computeMode = 1` when coloring by categorical columns, and `state.flipY = false` reset across Gaia Sky Lenses (`F-06`).

- **Evidence:**
  - **Writer `pytest` Suite (`13 passed, 1 skipped`):**
    - Command: `& "D:\exploratory\duckdb-extension\duckdb-arrowtiles\.venv\Scripts\python.exe" -m pytest -v -rs -p no:cacheprovider`
    - Output: `13 passed, 1 skipped in 3.28s` (covers Hilbert bit-shift invariants across 20,000+ cases, synthetic edge-case archive with `NaN`/`Inf`/`NULL` coords + colliding `x_norm` + 20-category `UInt8` + 300-category `UInt16` + coordinate round-trip within `span / (2 * 65535 * 2^z)`, leaf spillover past `nominal_max_zoom` + `z=20` exact-duplicate overflow guard, reserved column & invalid/reserved `custom_metadata` errors in Python and Rust, multi-file dense `row_id`, and legacy `v0.0` compatibility).
  - **Validator & `max_compressed_tile_bytes` Measurements:**
    - `samples/gaia_sample.arrowtiles` (`v0.1`, `4.26 MiB`): `[PASS] spec=0.1 tiles=342 rows=149,942 dropped=0 zoom=0..7 (header=7) max_tile_rows=19,477 max_compressed_tile=566,728 B (0.54 MiB at (0, 0, 0))`.
    - `samples/lmsys_sample.arrowtiles` (`v0.1`, `0.77 MiB`): `[PASS] spec=0.1 tiles=137 rows=100,000 dropped=0 zoom=0..5 (header=5) max_tile_rows=19,768 max_compressed_tile=137,717 B (0.13 MiB at (0, 0, 0))`.
    - `public/gaia_full.arrowtiles` (`legacy v0.0`, first 50 coarse tiles): `[PASS (legacy v0.0)] tiles=50 rows=10,656,888 max_tile_rows=262,144 max_compressed_tile=7,266,623 B (6.93 MiB at (2, 1, 1))`.
    - `public/lmsys_full.arrowtiles` (`legacy v0.0`, all 31,473 tiles): `[PASS (legacy v0.0)] tiles=31,473 rows=2,835,490 zoom=0..10 (header=22) max_tile_rows=56,201 max_compressed_tile=26,367,067 B (25.15 MiB at (3, 4, 4))` — empirically confirming the reviewer's warning that legacy `v0.0` archives embedding raw chat text `content` can exceed `16 MiB` (`25.15 MiB`), whereas `v0.1` numeric+categorical tiles stay `< 1 MiB` (`<= 7 MiB` on 262k-row Gaia tiles).
  - **Viewer TypeScript, Production Build & Live Chrome WebGPU Verification:**
    - `npx tsc --noEmit`: `exit code 0`.
    - `npm run build`: `exit code 0` (`dist/` built cleanly).
    - Live Chrome WebGPU Playwright check (`scratch/verify_phase1_viewer.mjs`): `exit code 0`, `pageErrors: []`, `consoleErrors: []`, legacy `v0.0` warning verified on `gaia_full.arrowtiles` (`archiveMaxZoom: 14`, `4.33M` stars at `155 FPS`), `v0.1` `gaia_sample.arrowtiles` rendered (`archiveMaxZoom: 7`, `row_id`/`z` excluded from GPU attributes, HR Diagram capped at `maxZ = 2`, `flipY` reset to `false` on Sky Lens switch), and `v0.1` `lmsys_sample.arrowtiles` rendered with `model` categorical legend in both `Compute (Atomic)` and `Hardware Instanced` at `240 FPS`.
    - Screenshots saved for visual review:
      - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase1_legacy_gaia_full.png`
      - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase1_v01_gaia_sample.png`
      - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase1_v01_lmsys_sample.png`

- **Not done / failed:**
  - **`git push`:** Not run (holding local commits on `revival/2026-11-wip` unless explicitly requested per `⛔` guardrail).

- **Questions for owner (before Phase 2):**
  1. **Phase 1 Visual & Code Review:** Please inspect the Phase 1 commits and the three WebGPU screenshots (`phase1_legacy_gaia_full.png`, `phase1_v01_gaia_sample.png`, `phase1_v01_lmsys_sample.png`). Shall we proceed to **Phase 2 (Fast, Correct Priority Pyramids — 2-stage batch bucketer, single-pass SQL preflight, and priority-invariant benchmark)**?


## 2026-11-19 — Phase 1 (post-review hotfix): `max_zoom <= 6` `coarse_counts` fix & Phase 2–5 review sync

- **Done:**
  1. **Fixed `max_zoom <= 6` out-of-bounds panic in `even_coverage` mode (`arrowtiles-engine/src/lib.rs:222`):** Unconditionally initialized `coarse_counts` (`5,461` `AtomicU32` slots = `21.3 KB`) so leaf/spill tiles at `z == nominal_max_zoom <= 6` never index an empty vector at `lib.rs:348`.
  2. **Added 18-case regression matrix (`tests/test_phase1_spec_and_edge_cases.py`):** Verified RED failure (`index out of bounds: the len is 0`) on the unpatched binary for `max_zoom=4, sampling='even_coverage'`, rebuilt via `maturin develop --release`, and verified GREEN across every `max_zoom = 0..8` in both `'even_coverage'` and `'proportional'` modes with dense-cluster spillover + `validate_file` checks.
  3. **Synced combined review additions into `logs/2026-11-19_05_PLAN_all_merged-consensus-revival-plan.md`:** Folded full `--resume` fingerprinting + `resume=True` test, single-pass SQL preflight, byte-identical output pass/fail gate, `> 16 MiB` `v0.1` tile error + category code bounds check, `64 MiB` explicit range / `413` error in `vite.config.ts`, free-text column policy (`⛔ D7a`), Phase 3 SplitMix64 random priority, and Phase 5 canonical `effectiveFlipY` into the governing plan.

- **Evidence:**
  - Command: `& "D:\exploratory\duckdb-extension\duckdb-arrowtiles\.venv\Scripts\python.exe" -m pytest -v -rs -p no:cacheprovider`
  - Output: `31 passed, 1 skipped in 5.40s`.

- **Questions for owner (before Phase 2):**
  1. **⛔ `D7a` (Free-text columns in `build_generic`):** Confirm dropping string columns whose distinct count exceeds `max_categories` (`4,096`) by default (with a clear diagnostic log line) unless explicitly named in `columns=` / `--columns`?
  2. **Legacy `lmsys_full.arrowtiles` vs. `v0.1` LMSys rebuild:** Keep `public/lmsys_full.arrowtiles` untouched in place (while `vite.config.ts` serves explicit ranges up to `64 MiB` and returns `413` above cap), or also build a clean `v0.1` `lmsys_v01.arrowtiles` alongside it without raw chat `content`?
  3. **Go-ahead for Phase 2:** Ready to start **Phase 2**?


## 2026-11-19 — Phase 2 (finish): Deterministic 2-stage bucketer, single-pass preflight, `D7a` `dropped_columns`, full `--resume` fingerprint, 100M Gaia benchmark & 2.84M LMSys SHA-256 verification

- **Done:**
  1. **Owner Decisions Locked (`D7a` & Range/Tile Caps):**
     - `D7a`: Drop high-cardinality string columns (`distinct > max_categories`, default `4,096`) by default unless explicitly listed in `columns=` / `--columns`, emit a clear log line, and record `"dropped_columns": [...]` in metadata (added to `SPEC.md` & `RESERVED_METADATA_KEYS`).
     - Tile-size & range alignment: Warn at `> 16 MiB` and error at `> 64 MiB` on `v0.1` in `validator.py` (updated `SPEC.md` §2.5 & §5.2 `z <= 6` with `z < nominal_max_zoom`); in `vite.config.ts`, keep `16 MiB` cap on open-ended `bytes=start-`, serve explicit `bytes=start-end` up to `64 MiB`, and return `413 Payload Too Large` above `64 MiB` (never silently truncating).
  2. **Deterministic Zero-Atomic 2-Stage Batch Bucketer (`arrowtiles-engine/src/lib.rs`, `Cargo.toml`):**
     - Removed `dashmap` and all atomic contention in `run_bucketer`: Stage A computes stateless `(ix_20, iy_20, h_20)` in parallel via Rayon; Stage B claims `Vec<u64>` (`coarse_bitsets`), `Vec<u32>` (`coarse_counts`, `mid_counts`), and `HashMap<u64, u32>` (`deep_counts`) sequentially in strict `(priority_key, row_id ASC)` order, writing directly into Arrow scalar buffers.
  3. **Single-Pass SQL Preflight & Full SHA-256 `--resume` Fingerprint (`arrowtiles/builder.py`):**
     - Eliminated the duplicate `COUNT(*)` / stats scan across `build_generic`, `build_gaia`, and direct `ArrowTilesBuilder.build()` calls.
     - Upgraded `partitions/manifest.json` (`arrowtiles-partitions-v2`) to hash the resolved input file list (`path`, `size`, `mtime_ns`) + every build setting (`nominal_max_zoom`, `tile_capacity`, `max_tile_rows`, `sampling`, `grid_size`, `priority`, `id_col`, `retained_columns`, `categorical_columns`, `dropped_columns`, `allow_oversize_leaves`), invalidating stale partitions automatically on any mismatch.
     - Enforced `sort_keys=True` on all JSON metadata for byte-for-byte deterministic output.
  4. **Validator Category-Code Bounds & Worker `Type.Bool` Support (`validator.py`, `pmtiles.worker.ts`):**
     - Added per-tile `0 <= code < len(categories)` check on categorical columns and `dropped_columns` schema-absence check in `validator.py`.
     - Added Arrow `Type.Bool` bit-unpacking in `pmtiles.worker.ts` (`getFloat32Col`) so boolean columns on full LMSys decode accurately to `0.0` / `1.0` (`NaN` for nulls).
  5. **Added Phase 2 Determinism & Completeness Suite (`tests/test_determinism_and_completeness.py`) & Built `samples/lmsys_full_v01.arrowtiles` (`scripts/build_samples.py --include-lmsys-full`):**
     - Covers byte-identical SHA-256 rebuilds (unique, all-tied, and seeded-random priorities in both sampling modes), strict per-cell ($z \le 6 \land z < \text{nominal\_max\_zoom}$) and per-tile descendant priority monotonicity at `nominal_max_zoom = 4` and `8` (`ASC` & `DESC`), real `resume=True` byte-identical output + stale-manifest invalidation, `D7a` free-text drop + `columns=` opt-in, and out-of-range category code rejection.

- **Evidence:**
  - **100,000,000-Row Gaia Pass 1 Throughput Benchmark (`s3_cache/batch_000..002.parquet`, pre-sorted 100M stream -> `run_bucketer`; temp dir deleted after run):**
    - Phase 1 Atomic Bucketer (`25a1a93`): **`75.503 s`** (`1.324 M rows/s`, `actual_max_z = 8`).
    - Phase 2 Deterministic 2-Stage Bucketer: **`56.394 s`** (`1.773 M rows/s`, `actual_max_z = 8`) — **25.3% faster (`+33.9%` higher throughput)** than the atomic bucketer while eliminating nondeterminism completely.
  - **Full `2,835,490`-Row LMSys `v0.1` Double-Build & Validation (`samples/lmsys_full_v01.arrowtiles`, `public/lmsys_full.arrowtiles` untouched):**
    - `D7a` automatically dropped `"conversation_id"` (`766,507` distinct) and `"content"` (`2,292,301` distinct), shrinking the archive from `841.5 MB` (legacy `v0.0`) to **`291,047,532` bytes (`277.6 MiB`)** and reducing `max_compressed_tile_bytes` from `25.15 MiB` to **`8,195,007` B (`7.82 MiB` at `(3, 3, 4)`)**.
    - `validate`: `ok: true`, `10,917` tiles, `2,835,490` rows, `zoom = 0..7` (`header = 7`), `warnings: []`, `errors: []`.
    - Independent 2nd build SHA-256 match: both builds produced **`552f70129e3a53497acb11b59ae2ebbaf12f1c1221d303d1b70596c36b5dcd45`** (exact byte-for-byte match across all `2,835,490` rows).
  - **Writer `pytest` Suite:**
    - Command: `& "D:\exploratory\duckdb-extension\duckdb-arrowtiles\.venv\Scripts\python.exe" -m pytest -v -rs -p no:cacheprovider`
    - Output: **`44 passed, 1 skipped in 8.29s`**.
  - **Viewer TypeScript, Production Build & Dev Server `16 MiB` / `64 MiB` / `413` Verification (`127.0.0.1:5199`):**
    - `npx tsc --noEmit` & `npm run build`: `exit code 0`.
    - Open-ended `Range: bytes=0-` on `gaia_full.arrowtiles`: `206 Partial Content`, `len = 16,777,216` (`bytes 0-16777215/31016634401`).
    - Explicit `25.15 MiB` `Range: bytes=17791-26384857` on `lmsys_full.arrowtiles` (tile `3/4/4`): `206 Partial Content`, `len = 26,367,067` (served in full, zero truncation).
    - Explicit `70 MiB` `Range: bytes=0-73400320` on `gaia_full.arrowtiles`: **`413 Payload Too Large`** (`Payload Too Large: Explicit byte range exceeds 64 MiB limit`).

- **Not done / failed:**
  - **`git push`:** Not run (holding local commits on `revival/2026-11-wip` unless explicitly requested per `⛔` guardrail).

- **Questions for owner (before Phase 3):**
  1. **Phase 2 Review:** Please review the Phase 2 commits, the 100M-row Gaia benchmark (`56.39s` vs. `75.50s`), and the byte-identical 2.84M-row `lmsys_full_v01` verification. Ready to proceed to **Phase 3 (Explicit Priority & Sampling — SplitMix64 random default, `--preset gaia` with `phot_g_mean_mag`, HUD priority/sampling display, and visual `⛔ D7` `even_coverage` vs. `proportional` comparison on LMSys)**?


## 2026-11-20 — Phase 3 (finish, paused at `⛔ D7`): Portable `SplitMix64` random priority default, `--preset gaia` (`phot_g_mean_mag`), HUD priority/sampling telemetry & 2.84M LMSys `even_coverage` vs. `proportional` comparison

- **Done:**
  1. **Portable `SplitMix64` Default Priority (`docs/SPEC.md` §6.1, `arrowtiles-engine/src/lib.rs`, `arrowtiles/builder.py`):**
     - Specified the exact unsigned 64-bit `splitmix64(row_id, seed)` mixing function in `docs/SPEC.md` §6.1 (`0x9E3779B97F4A7C15`, `0xBF58476D1CE4E5B9`, `0x94D049BB133111EB`).
     - Replaced DuckDB's version-dependent `hash(...)` with `_duckdb_splitmix64_sql(...)` evaluated in 128-bit unsigned `UHUGEINT` with `xor(...)` and `& CAST(18446744073709551615 AS UHUGEINT)` wrapping (avoiding DuckDB SQL hex-literal, `^` exponentiation, and `UBIGINT` overflow traps), plus matching `splitmix64_py` in Python and `#[pyfunction] splitmix64_hash` in Rust.
     - Removed `sort_col="abs_m"` default in `ArrowTilesBuilder.build(...)`: omitting `sort_col` now defaults to `{"kind": "random", "seed": 42}` everywhere.
  2. **Explicit `--preset gaia` (`phot_g_mean_mag ASC`) & Flexible Schema (`arrowtiles/builder.py`, `arrowtiles/__main__.py`):**
     - `build_gaia(...)` inspects input Parquet columns via `DESCRIBE` so both raw ESA Gaia DR3 names (`phot_g_mean_mag`, `bp_rp`) and local `s3_cache` names (`magnitude`, `bv`) are accepted seamlessly (falling back cleanly to `NULL::FLOAT` when optional astrophysics columns are absent).
     - Emits canonical `phot_g_mean_mag: Float32` sorted `ASC` (`view.sizeField = "phot_g_mean_mag"`), and forwards `sampling`, `grid_size`, `allow_oversize_leaves`, and `custom_config` from `python -m arrowtiles build --preset gaia`.
  3. **Viewer `phot_g_mean_mag` / Legacy `abs_m` Dual Support & HUD Priority/Sampling Display (`Scatterplot.ts`, `ComputeRasterizer.ts`, `main.ts`, `vite.config.ts`):**
     - Added `scatterplot.gaiaMagField` (`'phot_g_mean_mag'` when present in schema, else `'abs_m'`) across `getActiveColumns`, `getMaterialSignature`, `createMainMaterial`, `computeSlotMagBins`, `ComputeRasterizer.render`, `gaiaFallbacks`, Sky Lenses 10 & 1, and HR Diagram `yField`.
     - Added `#tel-pyramid` line in the viewer HUD displaying active `Priority` & `Sampling` via `.textContent` (e.g., `Priority: random (seed=42) | Sampling: even_coverage (316x316)`, `Priority: phot_g_mean_mag ASC | Sampling: even_coverage (158x158)`, or `Priority: legacy v0.0 | Sampling: legacy v0.0`).
     - Added safe `?file=/...arrowtiles` query param + `/samples/<name>.arrowtiles` range serving from `../duckdb-arrowtiles/samples` in `vite.config.ts` so `samples/` archives can be inspected live without copying binaries into `public/`.
  4. **Built Full `2,835,490`-Row LMSys `⛔ D7` Comparison Pair (`scripts/build_samples.py --build-d7-comparison`):**
     - Rebuilt `samples/gaia_sample.arrowtiles` (`phot_g_mean_mag ASC`) and `samples/lmsys_sample.arrowtiles` (`random(seed=42)`), plus built `samples/lmsys_d7_even_coverage.arrowtiles` and `samples/lmsys_d7_proportional.arrowtiles` on all `2,835,490` rows of `lmsys.parquet` with `SplitMix64(seed=42)` priority (`samples/lmsys_full_v01.arrowtiles` and `public/lmsys_full.arrowtiles` kept untouched).

- **Evidence:**
  - **Writer `pytest` Suite (`48 passed, 1 skipped`):**
    - Command: `& "D:\exploratory\duckdb-extension\duckdb-arrowtiles\.venv\Scripts\python.exe" -m pytest -v -rs -p no:cacheprovider`
    - Output: **`48 passed, 1 skipped in 14.71s`** (includes `tests/test_phase3_priority_and_presets.py` verifying bit-exact equivalence between Rust `splitmix64_hash`, Python `splitmix64_py`, and DuckDB 1.5.3 `UHUGEINT` SQL across golden vectors, boundary `u64`/`i64` pairs, and 1,000 random 64-bit `row_id`s; exact top-25 `SplitMix64` root-tile selection; `--preset gaia` on both `(phot_g_mean_mag, bp_rp)` and `(magnitude, bv)` schemas + CLI flag forwarding; and explicit `tile_capacity` / `sampling` passthrough).
  - **2.84M-Row LMSys `⛔ D7` Comparison Metrics (`SplitMix64(seed=42)`, `tile_capacity=100,000`):**
    - `samples/lmsys_d7_even_coverage.arrowtiles`: `[PASS] spec=0.1`, **`298,682,719` B (`284.85 MiB`)**, SHA-256 `f77e6ab5f89573fcf8bc30c56fa1b9b1beade1d37f806147b0d457cd5dfbe64c`, **`10,768` tiles**, `zoom = 0..7`, `max_tile_rows = 79,008`, `max_compressed_tile = 8,437,095 B` (`8.05 MiB` at `(3, 3, 4)`). At `Z=2` overview: `21` tiles, `0.29M` points rendered (preserves outer islands & core color detail); at `Z=4` cluster zoom: `85` tiles, `1.61M` points rendered.
    - `samples/lmsys_d7_proportional.arrowtiles`: `[PASS] spec=0.1`, **`292,552,296` B (`279.00 MiB`)**, SHA-256 `aa41e950d0dcf56d8c183c0acff002b6ad9a65c9a707cc96e184ab9c80fc88ee`, **`61` tiles**, `zoom = 0..4`, `max_tile_rows = 100,000`, `max_compressed_tile = 10,735,648 B` (`10.24 MiB` at `(2, 1, 2)`). At `Z=2` overview: `21` tiles, `1.25M` points rendered (true statistical density, bright saturated core, 176x fewer tiles); at `Z=4` cluster zoom: `49` tiles, `2.56M` points rendered.
  - **Viewer TypeScript, Production Build & Live Chrome WebGPU Verification (`scratch/capture_phase3_d7.mjs`):**
    - `npx tsc --noEmit` & `npm run build`: `exit code 0`.
    - Live Chrome WebGPU check across `gaia_full.arrowtiles` (`legacy v0.0`, `abs_m`), `gaia_sample.arrowtiles` (`v0.1`, `phot_g_mean_mag` + HR Diagram `yField == 'phot_g_mean_mag'`), `lmsys_d7_even_coverage.arrowtiles` (`Z=2` & `Z=4`), and `lmsys_d7_proportional.arrowtiles` (`Z=2` & `Z=4`): `exit code 0`, `pageErrors: []`, `consoleErrors: []`.
    - Screenshots saved for `⛔ D7` owner review:
      - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase3_d7_lmsys_even_coverage_z2.png`
      - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase3_d7_lmsys_proportional_z2.png`
      - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase3_d7_lmsys_even_coverage_z4.png`
      - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase3_d7_lmsys_proportional_z4.png`
      - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase3_v01_gaia_sample_phot_g.png`

- **Not done / failed:**
  - **`git push`:** Not run (holding local commits on `revival/2026-11-wip` unless explicitly requested per `⛔` guardrail).

- **Questions for owner (`⛔ D7` Stop Gate before Phase 4):**
  1. **⛔ `D7` (Default Sampling Mode for Generic Builds):** Having compared full 2.84M-row LMSys (`SplitMix64(seed=42)`) in **`even_coverage`** (`316x316` sub-grid at `z <= 6`: preserves sparse outer islands & core color contrast at overview; `10,768` tiles, `zoom 0..7`) vs. **`proportional`** (`100,000` rows/tile: true i.i.d. statistical density & only `61` tiles / `zoom 0..4`, with brighter additive saturation in dense cores), which mode should be the default `--sampling` for generic builds (`even_coverage` vs. `proportional`), while keeping `even_coverage` on `--preset gaia`?
  2. **Go-ahead for Phase 4:** Once `D7` is locked, ready to proceed to **Phase 4 (Parquet vs. `.arrowtiles` Benchmark across samples, full LMSys 3-of-38 & full schema, and `>= 100M` Gaia rows -> `⛔ D8, D9, D10`)**?


## 2026-11-20 — Phase 4 (finish, paused at `⛔ D8 / D9 / D10`): `D7` locked (`proportional` + `25,000` generic `tile_capacity`), categorical log-density tone mapping (`clusters_14`), `SLO` cold-vs-warm diagnosis, and `.arrowtiles` vs. HTTP-range Parquet benchmark (`100M` Gaia + `2.84M` LMSys)

- **Done:**
  1. **Owner Decision `D7` Locked + Generic `tile_capacity` Sweep (`arrowtiles/builder.py`, `arrowtiles/__main__.py`, `docs/SPEC.md`):**
     - Locked **`proportional`** as the default sampling mode for generic builds (`ArrowTilesBuilder.build`, `build_generic`, and `python -m arrowtiles build`), while keeping **`even_coverage`** (`100,000` capacity) on `build_gaia` / `--preset gaia`.
     - Benchmarked `proportional` `tile_capacity` across `100k`, `50k`, and `25k` on all `2,835,490` LMSys rows (`SplitMix64(seed=42)`) and locked **`DEFAULT_TILE_CAPACITY = 25_000`** (`0.46M` overview points and `40.38 MiB` at `Z=0..2` vs. `1.25M` points and `118.07 MiB` at `100k`; `221` total tiles, `max_compressed_tile = 2.56 MiB`, `3.64x` faster warm burst P95).
     - Added `--categorical-cols` / `categorical_cols` to `build_generic` for explicit integer cluster encoding (`UInt8`/`UInt16`), added 5 literal 64-bit `SplitMix64` golden test vectors (`0xE220A8397B1DCDAF`, `0xBDD732262FEB6E95`, `0xBA69EC90EB4FEF88`, `0xF3203E9039F4A821`, `0xF1C1278DBFA2126B`) in `tests/test_phase3_priority_and_presets.py`, and recorded the `v0.2` per-tile density/category-count summary grid roadmap item under `"tile_stats"` in `docs/SPEC.md` §6.4.
  2. **Viewer Log-Density Categorical Tone Mapping & `clusters_14` `D7` Screenshots (`ComputeRasterizer.ts`, `Scatterplot.ts`, `main.ts`):**
     - Widened `ComputeRasterizer` `accumBuffer` to `3 × u32` (`12 B/px`, clamped to `maxStorageBufferBindingSize`) and implemented **log-density categorical tone mapping** (`brightness = log2(1 + count) / log2(1 + refCount)`, `colour = mean category RGB`), eliminating additive white-out saturation across dense UMAP cores; also switched `Hardware Instanced` categorical blending to `OneMinusSrcAlphaFactor` and auto-registered discrete integer `clusters_*` columns in `main.ts`.
     - Re-captured matched-camera `Z=2` and `Z=4` WebGPU screenshots colored by `clusters_14` across `proportional (25k)`, `proportional (100k)`, and `even_coverage (100k)` (`0` console/page errors).
  3. **Diagnosed Red `SLO Status (P95 < 50ms)` (`306–704 ms`):**
     - Isolated cold page-load vs. warm pan/zoom telemetry: cold first-batch `workerMs` is `204.7–344.5 ms` (main-thread `tWorkerStart` stamped before Vite worker module load + `zstd.wasm` compilation, vs. `6.7–22.1 ms` warm) and `t0` includes cold root/leaf directory decompression; because the rolling window holds `50` tiles while `Z=0..2` loads `21` tiles, `p95` (`index 19/21`) stays pinned to the cold boot spike. At `100k` capacity on 36-col LMSys there was also a real payload cost (`155.2 ms` warm median / `430.3 ms` warm P95), reduced to `76.2 ms` warm median (`22.1 ms` worker) / `118.2 ms` warm 64-tile burst P95 at `25k` capacity.
  4. **Executed Full Phase 4 `.arrowtiles` vs. Sorted HTTP-Range Parquet Benchmark (`docs/BENCHMARK_parquet_vs_arrowtiles.md`):**
     - Benchmarked `.arrowtiles` (`v0.1`) against **Layout 1 (`parquet_tile_rg`: 1 RG/tile + index)** and **Layout 2 (`parquet_page_idx`: `250k`-row RGs + Parquet V2 Page Index `OffsetIndex` + index)** across `gaia_sample` (`150k`), `lmsys_sample` (`100k`), `lmsys_full` (`2.84M`, 3-of-38 projection & 36-col full schema), and `gaia_100m` (`100,000,000` Gaia stars, 4-col optical & 9-col full schema) in Chrome Web Workers (`6` workers, shared `@bokuweb/zstd-wasm` WASM Zstd, `Cache-Control: no-store`, 5 runs each reporting Median + P95), then cleaned up the `~8 GB` temporary 100M benchmark files on `D:`.

- **Evidence:**
  - **Writer `pytest` Suite:** `48 passed, 1 skipped in 10.58s`.
  - **Viewer TypeScript & Production Build:** `npx tsc --noEmit` (`exit code 0`) and `npm run build` (`exit code 0`, built in `58.59s`).
  - **Headline Benchmark Numbers (see full tables in `docs/BENCHMARK_parquet_vs_arrowtiles.md`):**
    - `gaia_100m` (`100,000,000` rows, `9,573` tiles, 4-col optical):
      - `.arrowtiles`: `2.441 GiB` file, **`6.8 ms` handshake (`17.0 KB`, `2` reqs)**, **`180.8 ms` TTFF (`24` reqs)**, `20.5 MB` peak JS+buffers.
      - `parquet_tile_rg`: `2.547 GiB` file, **`5,021.8 ms` handshake (`8,641.6 KB` footer+index)**, `5,147.8 ms` TTFF (`46` reqs), `121.2 MB` peak JS+buffers.
      - `parquet_page_idx`: `2.536 GiB` file, `112.8 ms` handshake (`839.9 KB`), `289.6 ms` TTFF (**`147` HTTP reqs**; `460.0 ms` / **`243` reqs** on 9-col Gaia).
    - `lmsys_full` (`2,835,490` rows, `221` tiles, `36` payload cols):
      - Full 36-col schema: `.arrowtiles` **`249.3 ms` TTFF (`23` reqs)** / **`113.7 ms` Deep Zoom (`16` reqs)** vs. `448.3 ms` / `134.3 ms` (`parquet_tile_rg`) and `1,116.6 ms` (`839` reqs) / `836.0 ms` (`684` reqs) (`parquet_page_idx`).
      - 3-of-38 projection (`x_u16, y_u16, clusters_14`): `parquet_page_idx` **`158.1 ms` TTFF (`4.62 MiB`, `113` reqs)** and `parquet_tile_rg` `235.6 ms` TTFF / **`37.5 ms` Deep Zoom (`1.30 MiB`, `32` reqs)** vs. monolithic 36-col `.arrowtiles` `212.1 ms` TTFF (`40.39 MiB`, `23` reqs) / `107.5 ms` Deep Zoom (`24.11 MiB`, `16` reqs).
  - **Updated `clusters_14` Log-Density Screenshots:**
    - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase4_d7_clusters14_proportional_25k_z2.png`
    - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase4_d7_clusters14_proportional_25k_z4.png`
    - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase4_d7_clusters14_proportional_100k_z2.png`
    - `C:\Users\erlen\.gemini\antigravity\brain\e91adbce-084e-445b-98b1-a434c428c86d\phase4_d7_clusters14_even_coverage_z2.png`

- **Not done / failed:**
  - **`git push`:** Not run (holding local commits on `revival/2026-11-wip` unless explicitly requested per `⛔` guardrail).

- **Questions for owner (`⛔ D8 / D9 / D10` Stop Gate before Phase 5):**
  1. **⛔ `D8` (Container Choice):** Keep **`.arrowtiles` (`v0.1`)** as our primary spatial pyramid container (pairing wide 30+-column tables with `--columns` or `v0.2` `"layers"` / sidecar Parquet attribute lookup), or pivot to sorted Parquet?
  2. **⛔ `D9` (Renderer Architecture for Phases 5–6):** Unify on **`ComputeRasterizer` ("Compute-Only")** (moving 2s axis transitions into WGSL and retiring `Scatterplot` Three.js instanced point meshes for clean direct `GPUBuffer` VRAM management), or keep Dual-Renderer (`Compute (Atomic)` + `Hardware Instanced`)?
  3. **⛔ `D10` (Continuous / Optical Tone Mapping):** Keep per-point ACES + sRGB transfer in Gaia Mode 0 & Star Trails Mode 3 (widening channels to `16-bit` in Phase 5b to preserve the tuned Milky Way look), or move continuous/optical tone mapping into the Resolve pass?


## 2026-11-20 — Plan Update (`D11` / `⛔ D12`): Embeddable npm Library + Demo App Architecture & Phase 8 Packaging

- **Done:**
  1. **Recorded Owner Decision `D11` (`2026-11-20`) in `logs/2026-11-19_05_PLAN_all_merged-consensus-revival-plan.md`:** Deepgraph viewer ships as an **embeddable npm library + demo app** (Deepscatter / cosmos.gl model).
  2. **Updated Phase 5a in `05_PLAN`:**
     - Library modules (`DatasetSession`, `ViewState`, `RenderLoop`, `ViewerLayer`) must not import `lil-gui`, read URL params, or touch the DOM beyond the `container` element passed in (`ControlsPanel` / `lil-gui` and URL handling belong strictly to the demo app).
     - Zero Gaia special cases in library code: dataset behavior comes strictly from `metadata.view` or a caller-provided `preset` object.
     - Draft (do not publish) minimal public API contract in `docs/API.md` (`Deepgraph.create(container, { url, encoding, preset? })`, `plot.setEncoding(...)`, `plot.on('click' | 'hover' | 'select', handler)`, `plot.destroy()`), and **stop for review of `docs/API.md` alongside the Phase 5a refactor**.
  3. **Added Phase 8 (Packaging, after Phase 7) & Stop Gate `⛔ D12` in `05_PLAN`:**
     - Library entry point + TypeScript `.d.ts` declarations, Vite ES module library build, documented peer/bundled dependency decisions, demo app rebuilt strictly on the public API (no deep imports), single-HTML embed example, finalized API docs, and `LICENSE` check.
     - Package name and npm publishing gated on explicit owner decision **`⛔ D12`** (never publish without approval).


## 2026-11-20 — Pre-Phase-5a Follow-Ups & Phase 5a (finish, paused at `docs/API.md` & `⛔` Dead-Code/Dep Cleanup Review): Locked `D8`/`D9`/`D10`, Throttled WAN Benchmark (`50 ms` RTT, `50 Mbps`), Sparse `UTINYINT` Fix, Pure Embeddable Library Split (`D11`), and `docs/API.md` Draft

- **Done:**
  1. **Locked Owner Decisions `D8`, `D9`, and `D10` (`2026-11-20`) in `05_PLAN`, `SPEC.md`, and `BENCHMARK_parquet_vs_arrowtiles.md`:**
     - **`D8`:** Kept **`.arrowtiles` (`v0.1`)** as the primary spatial pyramid container, promoted column-group `"layers"` sidecars for wide tables to a **required `v0.2` roadmap item** (`SPEC.md` §6.4), locked standalone `.arrowtiles` `row_id` + retained-column decoding in Phase 7 (`resolveRowAttributes` hook for optional sidecar Parquet cold attributes), committed the reproducible browser benchmark harness under [`scripts/bench/`](file:///D:/exploratory/duckdb-extension/duckdb-arrowtiles/scripts/bench), and ran the throttled WAN (`50 ms` RTT, `50 Mbps`) `lmsys_full` benchmark.
     - **`D9`:** Locked **Compute-Only** for Phase 5b (retiring `Scatterplot` Three.js instanced meshes & `WebGPUAdapter.ts`, owning `GPUBuffer`s directly, moving 2s axis transitions into WGSL, and adding a plain-WebGPU point highlight overlay in Phase 7/8).
     - **`D10`:** Locked **Split-by-Mode** for Phase 5b (per-point ACES + sRGB scoped to Gaia optical Modes 0 & 3; generic numeric Mode 1 moved to Resolve-pass log-density tone mapping alongside categorical Mode 1; race-free interval-gated `prevW = atomicAdd(&accumBuf[base2], w)` in `2 × u32` `8 B/px` `accumBuffer` + adapter `maxStorageBufferBindingSize`).
  2. **Fixed Sparse/1-Based `UTINYINT` / `USMALLINT` `--categorical-cols` Remapping (`arrowtiles/builder.py:496`):**
     - Removed `and self._base_duckdb_type(schema_map[col]) not in ("UTINYINT", "USMALLINT")` so `cat_lookup_tables` is always joined whenever `col in cat_lookup_tables`, ensuring sparse unsigned integer category IDs (e.g. `[10, 20, 30]`, `[100, 250, 1000]`) remap cleanly to dense `0..K-1` codes.
     - Added regression test `test_sparse_utinyint_usmallint_categorical_cols` in `tests/test_phase3_priority_and_presets.py`.
  3. **Executed 5-Run Throttled WAN Benchmark (`50 ms` RTT, `50 Mbps` via Chrome CDP on `lmsys_full`) & Cleaned Temp Data:**
     - Appended Section `5.4` to `docs/BENCHMARK_parquet_vs_arrowtiles.md` and deleted `samples/_tmp_phase4_parquet_bench/` afterward.
  4. **Executed Phase 5a — Pure Structural Refactor + `D11` Embeddable Library Boundary + `docs/API.md` Draft (`deepgraph-arrowtiles-sandbox`):**
     - Split `src/main.ts` (`1,112` lines -> **`112` lines**) into clean **library modules** (`src/lib/types.ts`, `src/lib/DatasetSession.ts`, `src/lib/ViewState.ts`, `src/lib/RenderLoop.ts`, `src/lib/ViewerLayer.ts`, `src/index.ts`) and **demo-app modules** (`src/demo/gaiaPreset.ts`, `src/demo/ControlsPanel.ts`, `src/main.ts`).
     - Enforced strict `D11` boundary: zero `lil-gui`, zero `window.location` / `URLSearchParams`, zero DOM access outside `container` (with `ResizeObserver` + container-relative wheel zoom + full `Renderer.dispose()` cleanup), zero Three.js types in public API signatures, and zero Gaia strings/heuristics in library modules (`ViewState.effectiveFlipY` drives both `PMTilesClient` and `Scatterplot` `yRange`).
     - Added `"typecheck": "tsc --noEmit"` and explicit `"fflate": "^0.8.3"` in `package.json`, and drafted [`docs/API.md`](file:///D:/exploratory/duckdb-extension/deepgraph-arrowtiles-sandbox/docs/API.md) for review.

- **Evidence:**
  - **Writer `pytest` Suite (`49 passed, 1 skipped`):**
    - Command: `& "D:\exploratory\duckdb-extension\duckdb-arrowtiles\.venv\Scripts\python.exe" -m pytest -v -rs -p no:cacheprovider`
    - Output: **`49 passed, 1 skipped in 10.94s`** (including `test_sparse_utinyint_usmallint_categorical_cols`).
  - **Throttled WAN Benchmark (`lmsys_full`, `50 ms` RTT, `50 Mbps`, `5` runs Median / P95):**
    - `proj_3_of_38`: `.arrowtiles` (`36`-col monolithic) `HS = 157.3 / 159.3 ms`, `TTFF = 7,223.3 / 7,265.8 ms` (`40.39 MiB`, `23` reqs), `Deep = 4,208.1 / 4,220.4 ms`; `parquet_tile_rg` `HS = 684.0 / 693.7 ms`, **`TTFF = 1,322.5 / 1,332.7 ms`** (`3.13 MiB`, `46` reqs), **`Deep = 514.1 / 541.4 ms`**; `parquet_page_idx` `HS = 258.9 / 264.4 ms`, `TTFF = 1,901.7 / 1,940.4 ms` (`4.62 MiB`, `113` reqs — slower than `parquet_tile_rg` due to `50 ms` RTT amplification), `Deep = 1,273.4 / 1,301.8 ms` (`90` reqs).
    - `full_schema_36`: `.arrowtiles` **`HS = 154.7 / 157.3 ms`**, **`TTFF = 7,238.9 / 7,300.7 ms`** (`23` reqs), `Deep = 4,220.3 / 4,243.8 ms`; `parquet_tile_rg` `HS = 523.9 / 574.8 ms`, `TTFF = 7,401.0 / 7,446.2 ms` (`38` reqs), `Deep = 4,142.8 / 4,162.7 ms`; `parquet_page_idx` `HS = 245.6 / 257.4 ms`, **`TTFF = 16,151.9 / 16,413.5 ms`** (`839` reqs — `2.23x` slower), `Deep = 11,957.4 / 12,166.4 ms` (`684` reqs — `2.83x` slower).
  - **Phase 5a Viewer Verification (`npm run typecheck`, `npm run build`, `D11` Grep, Live Chrome WebGPU `verify_phase5a.mjs`):**
    - `src/main.ts` line count: **`112` lines** (`< 150`).
    - `D11` boundary grep across `src/lib/*.ts` and `src/index.ts` for `lil-gui`, `window.location`, `URLSearchParams`, `getElementById`, `querySelector`, `document.body`, and Gaia constants: **`0` matches**.
    - `npm run typecheck` (`tsc --noEmit`) & `npm run build`: **`exit code 0`**.
    - Live headed Chrome WebGPU (`verify_phase5a.mjs`): verified `gaia_full.arrowtiles` + `?file=//` protocol-relative URL rejection, `gaia_sample.arrowtiles` (`phot_g_mean_mag ASC` + HR Diagram `effectiveFlipY = true` -> Sky in Colour `effectiveFlipY = false`), `lmsys_sample.arrowtiles`, `lmsys_d7_proportional_25k.arrowtiles` (`plot.setEncoding({ color: { field: 'clusters_14' } })`), and standalone `Deepgraph.create(box, { url })` + `plot.destroy()` in an isolated `640x480` `<div>` (`lilGuiInDom: 0`, `maxLoadedPts: 97,163`, `canvasCountAfter: 0`, `pageErrors: []`, `consoleErrors: []`).

- **Not done / failed:**
  - **`git push` / `npm publish`:** Not run (holding local commits on `revival/2026-11-wip` per `⛔` guardrails).
  - **Unused dependencies & dead files (`⛔` confirmation requested before removal):** Retained `@sentry/browser`, `@sentry/tracing`, `gl-matrix`, `@types/gl-matrix`, `stats.js`, `@types/stats.js`, and dead files `src/counter.ts`, `src/ui.ts`, `tests/compute_test.mjs` pending owner confirmation below.

- **Questions for owner (Phase 5a Stop Gate before Phase 5b):**
  1. **`docs/API.md` & Phase 5a Library Split (`D11`):** Does the drafted public API in `deepgraph-arrowtiles-sandbox/docs/API.md` (`Deepgraph.create(container, { url, encoding, preset, resolveRowAttributes })`, `setEncoding`, `load`, `on('click' | 'hover' | 'select' | 'telemetry' | 'load' | 'error')`, `destroy()`) look good to carry forward into Phases 5b–8?
  2. **⛔ Unused Dependencies & Dead Files Confirmation (`05_PLAN` §7.5):** Confirmed `0` imports across `src/` for `@sentry/browser`, `@sentry/tracing`, `gl-matrix`, `@types/gl-matrix`, `stats.js`, `@types/stats.js`, `src/counter.ts`, `src/ui.ts`, and `tests/compute_test.mjs` (`p-queue` *is* actively used in `PMTilesClient.ts` and stays). Confirm removing those 6 unused packages and 3 dead files at the start of **Phase 5b**?


## 2026-11-20 — Phase 5b (finish, paused for review before Phase 6): Compute-Only Direct `GPUBuffer` Pipeline (`D9`), Race-Free `2 × u32` Split-by-Mode Shaders (`D10`), CPU `Float64` `RTC` Deep Zoom, Zero-Retention Tile Lifecycle, and Public API Lock (`D11`)

- **Done:**
  1. **Folded All 5 Phase 5a Review Refinements & Public API Lock (`docs/API.md`, `src/index.ts`, `src/lib/`):**
     - Sealed `src/index.ts` to export **only** `Deepgraph` (`create`, `isSupported`) + public TypeScript types (`ViewerLayer`, `DatasetSession`, `ViewState`, and `RenderLoop` are internal; workspace harness access uses an unexported `INTERNAL_DIAGNOSTICS` `Symbol` in `src/lib/diagnostics.ts`).
     - Hid internal `x_u16` / `y_u16` column names from the public API: omitting `x`/`y` uses archive spatial positions, `setEncoding({ x: null, y: null })` resets chart axes back to spatial positions, and `ViewState` honors custom `domain`, `range`, and `transform` on `encoding.x` and `encoding.y` (fixing chart-column vs. top-down `y_u16` `flipY` range orientation so HR Diagrams place bright `M_G = 3` stars at the top).
     - Moved astronomy/flow domain specifics (`esa_*` scales, `'trails'`/`'streamlines'`, `metricType`, `auxFields`, `magnitudeFields`, `opticalColorField`, `legacyFlipY`, `trailMode`, `trailTimeKyr`, `minParallax`, `animateFlow`) under `ExperimentalOptions` (`preset.experimental` / `setViewOptions({ experimental })`), allowed `preset` to be a resolver `(rawMetadata, source) => DeepgraphPreset | undefined`, renamed `gaiaMagField` -> `magnitudeField`, removed `'instanced'` / `RenderEngineMode` / `'dictionaries'` / `PointHitEvent.tile`, switched `PointHitEvent.rowId` to `number` (+ optional `rowIdBigInt?: bigint`), converted `getViewport()`/`setViewport()` to **data coordinates**, added `plot.fitView()`, and added `!queryFile.includes('\\')` in `src/main.ts`.
     - Guarded mid-flight `ViewerLayer.load()` against concurrent `destroy()` or newer `load()` calls so any late `DatasetSession.open()` immediately disposes its workers without leaking state.
  2. **Removed Confirmed Unused Dependencies & Dead Files (`package.json`, `src/`, `tests/`):**
     - Removed `@sentry/browser`, `@sentry/tracing`, `gl-matrix`, `@types/gl-matrix`, `stats.js`, and `@types/stats.js` from `package.json` (`p-queue` retained).
     - Deleted dead files `src/counter.ts`, `src/ui.ts`, and `tests/compute_test.mjs`, and retired `src/Scatterplot.ts` and `src/WebGPUAdapter.ts` (`0` references to `backend.get`, `InstancedBufferGeometry`, or `MeshBasicNodeMaterial` remain).
  3. **Implemented `D9` Compute-Only Direct `GPUBuffer` Store & 2-Second WGSL Axis Transitions (`src/core/TileGpuStore.ts`, `src/core/ComputeRasterizer.ts`, `src/core/Renderer.ts`):**
     - Created `TileGpuStore.ts` managing exact-sized `GPUBuffer`s per tile and active column directly on `GPUDevice` (cutting active tile VRAM on 21-tile `0.46M`-point LMSys from `>300 MB` pre-allocated instanced geometry down to **`5.2 MB VRAM`**), with `ComputeRasterizer.dispose()` freeing all pipeline uniform/palette/dummy/accumulation `GPUBuffer`s on `plot.destroy()`.
     - Moved smooth 2-second cubic-smoothstep axis transitions (`mix(prevRelPos, currRelPos, transitionT)`) directly into `ComputeRasterizer.ts` while keeping `@compute` bindings at **`2` uniform buffers + `8` storage buffers** (`<=` universal WebGPU baseline limit of `8` storage buffers per stage by moving the 64-entry categorical palette to a `256 B` uniform buffer).
     - Fixed `computeSlotMagBins` (`Number.isFinite(m)` instead of `m > 0`) so bright stars with negative/zero magnitudes (`M_G <= 0`, e.g. Sirius `-1.46`) map into bin `0` and are never culled (`F-12`).
     - Added CPU `Float64` Relative-to-Center (`RTC`) deep-zoom projection (`rtcBaseX/StepX`, `rtcBaseY/StepY`) preserving full sub-pixel precision past `z = 20` (`F-07`), clamped `zoomT` to `[0, 1]`, and guarded `cpy < u.screenHeight` on Mode 4 streamline seeding.
  4. **Implemented `D10` Unified `2 × u32` (`8 B/px`) Race-Free Split-by-Mode Accumulation (`src/core/ComputeRasterizer.ts`):**
     - Unified `accumBuffer` at `2 × u32` (`8 B/px` = `112.5 MiB` at `5120×2880` 5K Retina `< 128 MiB` WebGPU default binding limit, paired with adapter `maxStorageBufferBindingSize` requested on device init):
       - **Modes 0 & 3 (Optical Sky & Star Trails):** `16-bit` fixed-point RGB (`word0 = R16 | G16<<16`, `word1 = B16`, scale `1024.0`, `64×` dynamic range) with per-point ACES + sRGB.
       - **Mode 1 (Both Categorical & Generic Numeric Points):** `word0` accumulates exact `u32` weighted hit counts via `let prevW = atomicAdd(&accumBuf[base2], w);`, and `word1` (`R10 | G10<<10 | B10<<20`) is strictly interval-gated on `prevW < 64u` (`wRgb = min(w, 64u - prevW)` -> max channel sum `64 * 15 = 960 < 1024`, mathematically zero TOCTOU race and zero 10-bit carry), resolved via `log2(1 + count)` brightness + mean RGB.
       - **Mode 2 (Mean Field) & Mode 4 (3D Motion + LIC Streamlines):** Separated `valSum_u32` (`word0`) from `weightSum` (`word1`, `24-bit` + `8-bit` `lineHits` in Mode 4), eliminating `16-bit` overflow/carry.
  5. **Hardened Streaming Worker, Memory Release & Build-Time Wide-Table Guardrails (`PMTilesClient.ts`, `pmtiles.worker.ts`, `duckdb-arrowtiles`):**
     - `pmtiles.worker.ts` eagerly compiles `zstd.wasm` on worker startup and reports warm `decodeMs`; `PMTilesClient.ts` uses a single `PMTiles` instance (`getHeaderAndMetadata()` + `configureArchive()`), calls `onTileUnloaded` before recycling buffers in `setRequestedColumns()` (`F-09`), caps column buffer pools (`16`/col), releases CPU `tile.columns` immediately after GPU upload (`0` retained CPU column arrays on uploaded tiles), separates `coldBootMs` from steady-state `steadyTotals`, and applies exponential retry backoff + 4-attempt negative caching on failed tiles.
     - `duckdb-arrowtiles` (`lib.rs`, `builder.py`, `README.md`): tracks compressed bytes across `Z = 0..2` overview tiles, emits a build-time warning when `Z = 0..2` exceeds `10 MiB` recommending `--columns`, logs a non-fatal JS `Number.MAX_SAFE_INTEGER` notice when `--id-col > 2^53 - 1`, and documents `--columns` prominently in `README.md`.

- **Evidence:**
  - **Writer `pytest` Suite (`50 passed, 1 skipped`):**
    - Command: `.venv\Scripts\python.exe -m pytest -v -rs -p no:cacheprovider`
    - Output: **`50 passed, 1 skipped`** (including `test_overview_bytes_warning_and_uint64_large_id_col`).
  - **Viewer Static Hygiene, Typecheck & Production Build:**
    - `npm run typecheck` (`tsc --noEmit`) & `npm run build` (`vite build`): **`exit code 0`**.
    - Grep across `src/**/*.ts` for retired symbols (`Scatterplot`, `WebGPUAdapter`, `backend.get`, `getAttributeGPUBuffer`, `writeToDeviceQueue`, `InstancedBufferGeometry`, `MeshBasicNodeMaterial`, `gaiaMagField`, `RenderEngineMode`): **`0` matches**.
    - Grep across `src/lib/*.ts` and `src/index.ts` for DOM/GUI/URL touches: **`0` matches**.
  - **Live Headed Chrome WebGPU Verification (`verify_phase5b.mjs` — `exit code 0`, `0` WebGPU validation/uncaptured errors, `0` console/page errors):**
    - **Check 1 & 2 (Sealed Barrel, Standalone Embed & Mid-Flight `load()+destroy()` Race):** `Object.keys(await import('/src/index.ts')) === ['Deepgraph']`, `Deepgraph.isSupported() === true`, `lilGuiInDom === 0`, mid-flight `load()` + immediate `destroy()` rejected cleanly (`"Deepgraph instance was destroyed during dataset load."`) with `0` lingering `<canvas>` elements.
    - **Check 3 (URL Sanitization):** Both `?file=//evil.example/x.arrowtiles` and `?file=/%5Cevil.arrowtiles` rejected safely.
    - **Check 4 (`gaia_full.arrowtiles` Modes `0, 2, 3, 4` + `M_G <= 0` Fix):** Mode 0 (`490,625` lit pixels, `whiteRatio = 0.00098`), negative/zero magnitudes `[-1.46, 0.0, 25.0]` placed both bright stars (`bin0Count === 2`) into bin `0`, and Modes `2`, `3`, and `4` each dispatched with `0` WebGPU validation errors.
    - **Check 5, 6, 7 (`gaia_sample.arrowtiles` 2s WGSL Transition, Custom Axis Domain/Range, `x: null` Reset, Data-Coord Viewport & `zoom = 131,072` `RTC`):** Verified custom `x`/`y` `{ domain, range, transform }` (`y.range = [1.6, -1.6]` with `flipY: true`), active transition at `+350 ms` (`transitionT = 0.081`) completing cleanly (`transitionT = 1.0`), `setEncoding({ x: null, y: null })` resetting without exposing `x_u16`/`y_u16`, exact data-coordinate `setViewport`/`getViewport` round-trip (`x = 1.414214, y = -0.707107 -> worldCam = (1.0, -0.5)`), and `zoom = 131,072` `RTC` deep zoom with `0` validation errors.
    - **Check 8 (`lmsys_d7_proportional_25k.arrowtiles` Mode 1 Categorical & Numeric Log-Density + Zero Retained CPU Columns):** Categorical `clusters_14` (`55,178` colorful pixels, `whiteRatio = 0.0039`) and numeric `num_of_tokens` (`64,526` colorful `viridis` pixels, `whiteRatio = 0.0039`) at **`240 FPS`**, **`0.1 ms` render**, **`5.2 MB` active tile VRAM**, lazy active columns `['xy_u16', 'clusters_14', 'num_of_tokens']` (`3` of `36` payload cols), and **`0` retained CPU column arrays** across all `21` uploaded tiles before and after column swap.

- **Not done / failed:**
  - **`git push` / `npm publish`:** Not run (holding local commits on `revival/2026-11-wip` per `⛔` guardrails).

- **Questions for owner (Phase 5b Stop Gate before Phase 6):**
  1. **Phase 5b Code & Visual Review:** Ready to proceed to **Phase 6 (Real Headed-Browser WebGPU VRAM & CPU Retention Lifecycle Gate — `window.__gpuStats` + `20×` `Deepgraph.create()`/`plot.destroy()` leak test + negative control)**?


## 2026-11-21 — Phase 6 (finish, paused for review before Phase 7): Complete Three.js Removal (`D9`), `64`-Level Numeric Log-Density Precision, Superseded `load()` `AbortError`, CLI `nargs="+"`, and Real-GPU `__gpuStats` Lifecycle Gate (`3 passed`)

- **Done:**
  1. **Finished `D9` — Removed `three` & `@types/three` Completely from the Library (`package.json`, `vite.config.ts`, `tsconfig.json`, `src/core/Renderer.ts`, `src/core/ComputeRasterizer.ts`, `src/lib/RenderLoop.ts`, `src/lib/ViewerLayer.ts`):**
     - Replaced `THREE.WebGPURenderer`, `OrthographicCamera`, and `OrbitControls` with ~310 lines of zero-dependency native WebGPU in `src/core/Renderer.ts`: directly owns `<canvas>` (`touch-action: none`), `navigator.gpu.requestAdapter()` / `adapter.requestDevice({ requiredLimits })`, `GPUCanvasContext` (`configure` / `unconfigure`), pure `Float64` `Camera2D` + pointer-capture drag pan (`pointerdown`/`move`/`up`/`cancel`/`lostpointercapture`) + wheel zoom-to-cursor, and native `requestAnimationFrame`.
     - Eliminated `100%` of `renderer.backend.device` private coupling; `ViewerLayer.destroy()` / `Renderer.dispose()` now synchronously unconfigures the swapchain context and calls `device.destroy()`.
     - Added explicit `DeepgraphStatic` interface annotation on `export const Deepgraph: DeepgraphStatic` (`tsc --noEmit --declaration` exits `0` with zero private class traversal), declared `@webgpu/types` in `devDependencies`, and set `build.copyPublicDir = false` in `vite.config.ts` so `vite build` never copies multi-GB `public/*.arrowtiles` into `dist/`.
     - Production JS bundle dropped by **64.4%**: `1,024.89 kB` (`274.74 kB` gzip) -> **`364.78 kB` (`94.09 kB` gzip)**, building in **`258 ms`**.
  2. **Phase 5b Review Polish & Reproducibility Fixes:**
     - **Superseded `load()` (`AbortError`):** `ViewerLayer.load()` now rejects superseded in-flight loads (`gen !== this.loadGeneration && !this.destroyed`) with `new DOMException('Dataset load superseded', 'AbortError')` instead of resolving with stale/other metadata; `src/main.ts` ignores `AbortError` cleanly on rapid UI switches.
     - **Committed `scripts/verify_phase5b.mjs`:** Saved the standalone 8-check Phase 5b WebGPU verification harness under `deepgraph-arrowtiles-sandbox/scripts/verify_phase5b.mjs` (updated with superseded `load()` `AbortError` and post-`destroy()` `__gpuStats` checks).
     - **Mode 1 `64`-Level (`6-bit`) Numeric Color Precision & `docs/API.md`:** Kept `64` weight units × `15` (`960 < 1,024`) for categorical Mode 1 (`isCat = true`) and switched numeric Mode 1 (`isCat = false`) to `16` weight units × `63` (`16 * 63 = 1,008 < 1,024` — `64` levels/channel = `4×` smoother numeric gradient resolution at `0` extra memory and `0` carry); updated `docs/API.md` to document `"mean of the first 64 (categorical, 4-bit) / 16 (numeric, 6-bit / 64-level) weighted hits per pixel"`, `AbortError`, and `device.destroy()`.
     - **Writer CLI `--columns` & `--categorical-cols` (`nargs="+"`):** Updated `arrowtiles/__main__.py` (`_flatten_column_args` + `nargs="+"`) so space-separated (`--columns model clusters_14 num_of_tokens`, matching `README.md:89`), comma-separated, and mixed invocations all work; added `test_cli_columns_and_categorical_cols_space_and_comma_syntax` in `tests/test_phase3_priority_and_presets.py`.
  3. **Phase 6 Real-GPU `__gpuStats` & CPU-Buffer Lifecycle Suite (`src/core/gpuStats.ts`, `src/PMTilesClient.ts`, `playwright.config.ts`, `tests/gpu-vram-lifecycle.spec.ts`):**
     - Instrumented `GPUAdapter.prototype.requestDevice`, `GPUDevice.prototype.destroy`, `GPUDevice.prototype.createBuffer`, and `GPUBuffer.prototype.destroy` in `src/core/gpuStats.ts` -> `window.__gpuStats` (`liveDevices`, `totalDevicesCreated`, `totalDevicesDestroyed`, `liveBuffers`, `liveBytes`, `tileLiveBuffers`, `tileLiveBytes`, `totalCreatedBuffers`, `totalDestroyedBuffers`, `totalCreatedBytes`, `totalDestroyedBytes`), plus `PMTilesClient.getCpuMemoryStats()` and live HUD `totalGpuMB`.
     - Configured `playwright.config.ts` (`chrome-webgpu`, `channel: 'chrome'`, `headless: false`, real hardware GPU — removed legacy `--use-angle=swiftshader`, isolated on `127.0.0.1:5179`) and implemented all 5 lifecycle gates in `tests/gpu-vram-lifecycle.spec.ts`.

- **Evidence:**
  - **Writer `pytest` Suite (`51 passed, 1 skipped`):**
    - Command: `.venv\Scripts\python.exe -m pytest -v -rs -p no:cacheprovider`
    - Output: **`51 passed, 1 skipped in 12.43s`**.
  - **Viewer Typecheck, Declaration Check, Bundle Build & `verify_phase5b.mjs`:**
    - `npm run typecheck` (`tsc --noEmit`) & `npx tsc --noEmit --declaration`: **`exit code 0`**.
    - `Select-String -Path 'src\**\*.ts' -Pattern '\bthree\b|\bTHREE\b|\.backend\b'`: **`0` code matches**.
    - `npm run build`: **`exit code 0` in `258 ms`** (`dist/assets/index-*.js` = **`364.78 kB` / `94.09 kB` gzip**).
    - `node scripts/verify_phase5b.mjs`: **`exit code 0`** (`ALL PHASE 5B LIVE WEBGPU CHECKS PASSED`).
  - **Real-GPU Playwright Lifecycle Suite (`npm run test:e2e` — `3 passed in 1.2m` on Intel `xe-lpg` Hardware GPU, `isFallbackAdapter: false`):**
    - **Gate 1 (Render, Controls & Frame-to-Frame Stability):** `69` visible tiles, `15,604,497` active Gaia stars rendered, bit-exact `Float64` wheel zoom-to-cursor (`|Δwx| = 0.0`, `|Δwy| = 0.0`); stationary 2-frame pixel delta: **`0.0040%`** on `gaia_full` Mode 0 (`39 / 978,316` lit px), **`0.0704%`** on `lmsys` Categorical Mode 1 (`meanDelta = 1.71 / 255`), and **`1.1475%`** on `lmsys` `64`-level Numeric Mode 1 (`meanDelta = 6.66 / 255`); `0` WebGPU/console/page errors.
    - **Gate 2 (Deep-Zoom LRU Eviction Plateau, `maxTileCache = 40`):** Visited **`289` unique `Z >= 3` tiles** (`7.2×` cache cap); `activeCacheSize` plateaued at `40` (`tileLiveBuffers = 160` at step 8 & step 17; `tileLiveMB = 144.88 MB -> 104.73 MB`; `1,084` buffers destroyed mid-sweep; `retainedTileCpuBytes = 0` at every stop); post-`destroy()`: `1,248 / 1,248` buffers & `1,094,363,344 / 1,094,363,344 B` destroyed (`liveDevices = 0, liveBytes = 0`).
    - **Gate 3 (Superseded `load()` `AbortError` + `5×` Dataset Swaps):** `load(A); load(B)` rejected `A` with `AbortError` while `B` (`149,942` rows) won; across 5 full `lmsys_sample` <-> `gaia_sample` round-trips, `gaiaTileLiveBytes` returned to **`1,334,628 B` (`67` buffers) on every single round (`0`-byte drift)**.
    - **Gate 4 (`20×` `Deepgraph.create()` + `plot.destroy()` Loop):** `20` `GPUDevice`s created === `20` destroyed (`22 / 22` cumulative), `2,967 / 2,967` buffers (`1,224,723,524 / 1,224,723,524 B`) destroyed, **`liveDevices = 0, liveBuffers = 0, liveBytes = 0, remainingCanvases = 0`**.
    - **Gate 5 (Mandatory Negative Control):** Enabling `debugSkipBufferDestroy = true` on `maxTileCache = 20` produced a **`116,853,136 B` (`111.44 MiB`, `112` buffers) discrepancy** deterministically caught by the `gs.tileLiveBytes === tileStore.getLiveTileGpuBytes()` check (`invariantFailedAsExpected: true`), then flushed cleanly back to `0` live bytes/devices.
    - **Rapid-Pan JS Heap Check (`tests/memory-leak.spec.ts`):** `Initial Heap: 8.12 MB -> Final Heap: 7.54 MB (Delta: -0.58 MB)`.

- **Not done / failed:**
  - **`git push` / `npm publish`:** Not run (holding local commits on `revival/2026-11-wip` per `⛔` guardrails).

- **Questions for owner (Phase 6 Stop Gate before Phase 7):**
  1. **Phase 6 Review:** Ready to proceed to **Phase 7 (Race-Free Per-Slot `1 KB` GPU `PickingLayer` in a dedicated `@compute` pipeline + on-demand `.arrowtiles` `row_id`/attribute decode + plain-WebGPU hover/selection highlight overlay)**?


## 2026-11-21 — Pre-Phase-7 Hygiene Fix & Phase 7 (finish, paused for review before Phase 8): Library-Clean `gpuStats` Isolation, `0.0000%`-Shimmer `1,024`-Level Numeric Mode 1, `powerPreference` Intel-iGPU Guard, Race-Free `1 KB` GPU `PickingLayer`, Standalone `.arrowtiles` `row_id` Decode, and Plain-WebGPU `HighlightOverlay`

- **Done:**
  1. **Pre-Phase-7 Fix — Removed Global WebGPU Prototype Patching from Library Code (`src/demo/gpuStats.ts`, `src/core/Renderer.ts`, `src/lib/RenderLoop.ts`, `src/lib/diagnostics.ts`):**
     - Moved `gpuStats.ts` out of `src/core/` into `src/demo/gpuStats.ts` (`0` global prototype patches and `0` `globalThis.__gpuStats` touches in `src/lib/`, `src/core/`, or `src/index.ts`; verified live in Chrome before harness installation: `winGpuStatsDefined === false`, `createBufferUnpatched === true`).
     - Added `ComputeRasterizer.getLiveGpuBytes()`, `PickingLayer.getLiveGpuBytes()`, and `HighlightOverlay.getLiveGpuBytes()`, computing `TelemetrySnapshot.totalGpuMB` strictly from library-owned `GPUBuffer` byte accounting.
     - Installed `installGpuStatsInstrumentation()` strictly in demo/test harnesses (`src/main.ts`, `scripts/verify_phase5b.mjs`, `tests/gpu-vram-lifecycle.spec.ts`, and `tests/picking-layer.spec.ts`).
  2. **Option B GPU Coexistence (`DeepgraphOptions.powerPreference` + Intel iGPU Pre-Check):**
     - Added `powerPreference?: 'high-performance' | 'low-power'` to `DeepgraphOptions` (`src/lib/types.ts`, `docs/API.md`), forwarded through `ViewerLayer.create()` -> `Renderer.init()` (`navigator.gpu.requestAdapter({ powerPreference })`), plus `?power=low` support in `src/main.ts` and `--force_low_power_gpu` in `playwright.config.ts`.
     - Verified `adapter.info.vendor === 'intel'` (`architecture: 'xe-lpg'`) **before** calling `requestDevice()` in `tests/picking-layer.spec.ts`, testing strictly on `< 5 MiB` `lmsys_sample` and `gaia_sample` (`17.02 MB` total cumulative iGPU allocations freed `100%` to `0`, `0 B` on the RTX 5090).
  3. **Zero-Shimmer `1,024`-Level Scalar Value-Sum for Numeric Mode 1 (`src/core/ComputeRasterizer.ts`, `docs/API.md`):**
     - Kept `64 × 15 = 960 < 1,024` interval-gated RGB accumulation for categorical Mode 1 (`isCat = true`).
     - Upgraded numeric Mode 1 (`isCat = false`) to an order-independent normalized scalar value sum in `word1`: `tU = min(u32(clamp(tNorm, 0.0, 1.0) * 1023.0 + 0.5), 1023u)` gated at `prevW < 1048576u` (`1,048,576 × 1,023 = 1.07B < 2^32`, zero overflow), resolving `eval_ramp(meanT, scaleId)` × `log2(1 + count)` brightness in `fs_main`.
     - Measured stationary 2-frame shimmer on `lmsys_sample` (`num_of_tokens` `viridis`): **`0 / 131,028` lit pixels changed (`0.0000%` shimmer, `maxDelta = 0`)**.
  4. **Phase 7 — Race-Free Per-Slot `1 KB` GPU `PickingLayer`, Standalone `.arrowtiles` `row_id` Decode & Plain-WebGPU `HighlightOverlay` (`05_PLAN` §9):**
     - **Drag vs. Click Gate (`src/core/Renderer.ts`):** Tracks pointer travel from `pointerdown` to `pointerup`, triggering `onCanvasClick` only when left-button pointer travel is `< 4.0 CSS px` (plus `onCanvasHover` and `onCanvasPointerLeave`).
     - **Dedicated `@compute` `PickingLayer` (`src/core/PickingLayer.ts`):** Separate `@compute` pipeline (`1` dynamic uniform + `8` storage buffers `<=` universal WebGPU baseline; `0 B` per-frame pan/zoom overhead) dispatching over a `9 × 9 CSS px` (`dpr`-scaled) cursor window and writing `(dist16th_u12 << 20u) | localRowIdx_u20` via `atomicMin` into a `1,056 B` (`~1 KB`) `slotBestHit` buffer, with automatic multi-chunk passes if an `--allow-oversize-leaves` tile ever exceeds `2^20 - 1` (`1,048,575`) rows. Matches `ComputeRasterizer`'s exact `Float64` `RTC` projection, `pcg_hash` jitter, `maxMag`/`NaN` visibility cutoffs, custom chart axes, and 2-second WGSL axis transitions.
     - **Priority-Aware Tie-Breaking & On-Demand `.arrowtiles` Row Decode (`src/PMTilesClient.ts`, `src/pmtiles.worker.ts`, `src/lib/ViewerLayer.ts`):** Breaks `dist16th` ties across slots by **coarser zoom `z` first** and `rawRowIdx` second, decodes `row_id` (`rowId: number` + lossless `rowIdBigInt?: bigint` when `> 2^53 - 1`), `x_u16`/`y_u16`, and all retained columns (including categorical string labels and `NULL -> null`) directly from `.arrowtiles` on demand (`0 MB` persistent worker RAM), invokes optional `resolveRowAttributes`, exposes `plot.pickAt(cssX, cssY)`, and emits `'click'`, `'select'`, and `45 ms`-throttled `'hover'`.
     - **Plain-WebGPU `HighlightOverlay` (`src/core/HighlightOverlay.ts`, `src/demo/ControlsPanel.ts`):** Renders anti-aliased dual-contrast SDF hover (cyan) and selected (gold) rings via `loadOp: 'load'` in the same `GPUCommandEncoder` as `ComputeRasterizer`, tracking pan, zoom, and 2s axis transitions (`0` draw calls when idle), plus an inspect readout card in `ControlsPanel.ts` and deterministic `GPUBuffer.destroy()` teardown in `plot.destroy()`.

- **Evidence:**
  - **Viewer Typecheck, `.d.ts` Check, Production Build & Library Hygiene Grep (CPU-only):**
    - `npm run typecheck` (`tsc --noEmit`) & `npx tsc --noEmit --declaration`: **`exit code 0`**.
    - `npm run build`: **`exit code 0` in `262 ms`** (`dist/assets/index-*.js` = **`399.12 kB` / `102.46 kB` gzip**).
    - Grep across `src/lib/*.ts`, `src/core/*.ts`, `src/index.ts` for `__gpuStats`, `installGpuStatsInstrumentation`, `prototype.requestDevice`, `prototype.createBuffer`: **`0` matches**.
  - **Intel-iGPU Sample-Only Playwright Verification (`npx playwright test tests/picking-layer.spec.ts` — `1 passed in 13.7s`):**
    - **Intel iGPU Pre-Check:** `vendor === 'intel'` (`xe-lpg`, `isFallbackAdapter: false`) verified before `requestDevice()`.
    - **Library Hygiene Proof:** `winGpuStatsDefined === false`, `createBufferUnpatched === true`.
    - **Numeric Mode 1 Stationary Shimmer:** **`0 / 131,028` lit pixels changed (`0.0000%`, `maxDelta = 0`)**.
    - **Drag vs. Click Gate:** `40 × 25 px` drag emitted **`0` `'click'` events**; stationary click (`0 px` travel) emitted `'click'` + `'select'`.
    - **`ArrowTilesReader` Ground-Truth Parity (`lmsys_sample` & `gaia_sample`):**
      - `lmsys_sample`: `rowId = 40064` (`model: "mixtral"`, `num_of_tokens: 308`, `|ΔdataX| < 1e-12`, `|ΔdataY| < 1e-12`), `rowId = 38479` (`model: "llama-3"`, `num_of_tokens: 95`), `rowId = 45449` (`model: "gpt-4"`, `num_of_tokens: 2`).
      - `gaia_sample` Spatial Sky: `rowId = 0` (`phot_g_mean_mag = 1.9425`, `bp_rp = 1.1435`, `radial_velocity = null`, `teff_gspphot = null`, `|ΔdataX| < 1e-12`, `|ΔdataY| < 1e-12`) + `'hover'` event verified.
      - `gaia_sample` HR Diagram (`x: 'bp_rp'`, `y: 'phot_g_mean_mag'`, `flipY: true`): `rowId = 14301` (`dataX = -0.500831`, `dataY = 6.667600`).
    - **Highlight Overlay, Priority Tie-Break, Oversize Leaf Chunking, `BigInt` `row_id` & Zero-Leak Teardown:**
      - `HighlightOverlay` rendered `140` gold ring pixels around `(480, 300)` and cleared cleanly (`click: null`, `select: { points: [] }`) on empty background click.
      - Coarser `0/0/0` (`z = 0`) beat `1/1/1` (`z = 1`) on exact pixel-center tie; `1,060,000`-row oversize leaf picked `rawRowIdx = 1,055,000` in chunk `#1`; `resolveRowAttributes` enriched `sidecarPrompt: "prompt_for_40064"`; `UInt64` `5900000000000000123n` (`> 2^53 - 1`) round-tripped losslessly via `rowIdBigInt`.
      - Post-`destroy()`: `2 / 2` `GPUDevice`s destroyed, `212 / 212` `GPUBuffer`s destroyed, **`17,021,320 / 17,021,320 B` destroyed (`liveDevices = 0, liveBuffers = 0, liveBytes = 0`)**, `0` WebGPU/console/page errors.

- **Not done / failed:**
  - **`git push` / `npm publish`:** Not run (holding local commits on `revival/2026-11-wip` per `⛔` guardrails).

- **Questions for owner (Phase 7 Stop Gate before Phase 8):**
  1. **Phase 7 Review:** Ready to proceed to **Phase 8 (Vite ES-Module Library Build + `.d.ts` Declarations, Demo App Rebuilt Strictly on Public Entry Point with Zero Deep Imports, Single-HTML Embed Example, `LICENSE` Check, and Stop Gate `⛔ D12` for Package Name / Publishing)**?


## 2026-11-21 — Pre-Phase-8 Hover Hardening & Phase 8 (finish — STOPPED AT `⛔ D12`): Compressed Pick LRU + 1-Tile Worker Cache + Instant GPU Hover Ring, Vite ES-Module Library Packaging (`98.5 kB` gzip), TypeScript 6.0 `.d.ts` Consumer Gate, Public-API Demo, `examples/embed.html`, and Read-Only License Audit

- **Done:**
  1. **Commit 1 (`ecda73d`) — Pre-Phase-8 Hover Network/CPU Hardening, Instant GPU Hover Ring, Spatial Slot Bounds Culling & Async Error Guards:**
     - **Zero Redundant Hover Downloads & Re-Decodes (`src/lib/ViewerLayer.ts`, `src/PMTilesClient.ts`, `src/pmtiles.worker.ts`):**
       - Same-winner `(tileKey, rawRowIdx)` short-circuit in `ViewerLayer.ts` (`0` network requests, `0` worker messages, `0` duplicate `'hover'` events when jittering over the same point).
       - Single in-flight hover with `AbortController` + microtask-coalesced `inFlightPickTileFetches` in `PMTilesClient.ts` so intra-tile hover sweeps share a single `PMTiles.getZxy(z, x, y, signal)` download without abort-restarting it, while cross-tile moves and `pointerleave` abort stale downloads immediately.
       - Byte-capped compressed tile LRU in `PMTilesClient.ts` (`<= 8` tiles / `<= 24 MiB`, opportunistically seeded in `loadTile`, accounted in `getCpuMemoryStats()`, and cleared on `setRequestedColumns` / `destroy()`) + 1-tile parsed Arrow `Table` cache in `pmtiles.worker.ts` (`decode_row`, cleared on `init_schema` / `clear_row_cache`) for `O(1)` (`0` Zstd decompressions, `0` `ArrayBuffer.slice` copies) consecutive intra-tile hovers.
     - **Instant GPU Hover Ring, Spatial Slot Cursor-Window Culling & Opt-In Hover Sidecar (`src/core/TileGpuStore.ts`, `src/core/PickingLayer.ts`, `src/lib/types.ts`, `docs/API.md`):**
       - Added `GPUBufferUsage.COPY_SRC` to tile column buffers and a `32 B` `winnerCoordBuffer` `MAP_READ` readback in `PickingLayer.ts` so `HighlightOverlay.hoverMarker` renders immediately at `60 FPS` from GPU winner coordinates before `decodeTileRow` finishes over slow networks.
       - Added CPU screen-space tile-bounds culling in `PickingLayer.ts` (`!isTransitioning`), skipping non-overlapping spatial slots (`3 / 5` slots culled at `zoom = 2.0` in test).
       - Made `resolveRowAttributes` run on `'click'` and `plot.pickAt(...)` only by default, adding `resolveRowAttributesOnHover?: boolean` (`default: false`) to `DeepgraphOptions`.
     - **Async Error Guards & `pointerleave` Cleanup (`src/lib/ViewerLayer.ts`, `src/pmtiles.worker.ts`, `src/core/Renderer.ts`):**
       - Wrapped `handleCanvasClick` and `pickAt` in `try/catch` (`0` `UnhandledPromiseRejection`s on mid-click `destroy()` / superseded `load()`, routing genuine `resolveRowAttributes` errors to `this.emit('error', ...)`).
       - Included `action: data?.action, id: data?.id` on Zstd WASM init error `postMessage` in `pmtiles.worker.ts` and cleared `hoverMarker` + emitted `hover: null` on `<canvas>` `pointerleave`.
  2. **Commit 2 — Phase 8: Vite ES-Module Library Packaging, TypeScript 6.0 `.d.ts` Gate, Pure Public-API Demo, `examples/embed.html` & Read-Only License Audit (`05_PLAN` §10):**
     - **Vite ES-Module Library Build (`vite.lib.config.ts`, `package.json`, `docs/API.md`):**
       - Configured `"exports"`, `"main"`, `"module"`, `"types"`, `"files": ["dist", "docs/API.md"]`, and `"sideEffects": false` in `package.json` while keeping `"private": true` and placeholder `"name"` until `⛔ D12`.
       - Moved demo-only `"lil-gui"` to `"devDependencies"`, kept `"fflate"` in `"dependencies"` (used directly by `PMTilesClient.ts` for Gzip-compressed PMTiles v3 directories), preserved `copyPublicDir: false` in both `vite.lib.config.ts` (`npm run build` / `npm run build:lib` -> `dist/`) and `vite.config.ts` (`npm run build:demo` -> `dist-demo/`).
       - `dist/index.js` (`429.84 kB` / **`98.47 kB` gzip**, `0 B` of `lil-gui` / `three` / `gpuStats`) spawns its worker relative to `import.meta.url` (`new URL("assets/pmtiles.worker-*.js", import.meta.url)`), and `dist/assets/pmtiles.worker-*.js` inlines `zstd.wasm` as `data:application/wasm;base64,...` so external consumers never hit `/assets/*.wasm` 404s.
     - **TypeScript 6.0 `.d.ts` Packaging & External Consumer Verification (`tsconfig.build.json`, `scripts/emit_dts.mjs`, `scripts/verify_consumer_dts.mjs`, `src/index.ts`, `src/lib/types.ts`):**
       - Made `src/lib/types.ts` 100% self-contained (`0` internal imports) and typed `export const Deepgraph: DeepgraphStatic` in `src/index.ts`, emitting sealed `dist/index.d.ts` (`780 B`) + `dist/lib/types.d.ts` (`11.48 kB`) with `rootDir: "./src"`, `stripInternal: true`, and `.ts -> .js` relative specifier rewriting (`0` `INTERNAL_DIAGNOSTICS`, `ViewerLayer`, `three`, `lil-gui`, or `@webgpu/types` leakage).
       - Verified via `npm run verify:types` (`tsc --noEmit` in an external consumer directory under both `bundler` and `nodenext` with `allowImportingTsExtensions` disabled, `skipLibCheck: false`, and `types: []`).
     - **Pure Public-API Demo & Standalone Single-HTML Embed (`src/main.ts`, `src/demo/ControlsPanel.ts`, `examples/embed.html`, `tests/library-embed.spec.ts`):**
       - Removed `INTERNAL_DIAGNOSTICS` from `src/main.ts` (`0` deep internal imports across `src/main.ts` and `src/demo/*`; `INTERNAL_DIAGNOSTICS` used strictly in `tests/*.spec.ts` and `scripts/verify_phase5b.mjs`) and wired live `'hover'` + pinned `'click'` readout into `ControlsPanel.ts`.
       - Added standalone `examples/embed.html` (`44` lines) importing `../dist/index.js` directly in `<script type="module">` and verified both `examples/embed.html` and the pure-public-API demo end-to-end on Intel `xe-lpg` iGPU in `tests/library-embed.spec.ts`.

- **Evidence:**
  - **Writer Test Suite (CPU-only):** `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` -> **`51 passed, 1 skipped`**.
  - **Viewer Typecheck, Library Build, Demo Build & External Consumer `.d.ts` Gate (CPU-only):**
    - `npm run typecheck` (`tsc --noEmit`): **`exit code 0`**.
    - `npm run build:lib`: **`exit code 0` in `224 ms`** (`dist/index.js` = **`429.84 kB` / `98.47 kB` gzip**; `dist/index.d.ts` + `dist/lib/types.d.ts`).
    - `npm run verify:types`: **`PASS`** under both `"moduleResolution": "bundler"` and `"moduleResolution": "nodenext"` (`allowImportingTsExtensions=false`, `skipLibCheck=false`, `types=[]`).
    - `npm run build:demo`: **`exit code 0` in `260 ms`**.
    - Deep-import grep across `src/main.ts` and `src/demo/*.ts`: **`0` imports from `./lib/*` or `./core/*`**.
  - **Intel-iGPU Sample-Only Playwright Verification (`0 B` on RTX 5090):**
    - `npx playwright test tests/picking-layer.spec.ts`: **`1 passed`** (`reqsDuringLoadedSweep = 0` across 20 hovers; `coldTileRangeReqs = 1` across 20 cold-cache hovers under `50 ms` RTT / `50 Mbps`; instant GPU hover ring `markerPresentImmediately = true` before network resolve; `3 / 5` spatial slots culled; `pointerleave` clear; `0` `UnhandledPromiseRejection`s; `37,917,484 / 37,917,484 B` & `6 / 6` devices freed).
    - `npx playwright test tests/library-embed.spec.ts`: **`1 passed in 9.4s`** (`/examples/embed.html?power=low` loaded `/dist/index.js` + `/dist/assets/pmtiles.worker-*.js` with `failedUrls = []`, `0` `.lil-gui` nodes, `winGpuStatsDefined = false`, clicked `row_id = 40064` `"mixtral"`, and tore down `9,499,388 / 9,499,388 B` & `1 / 1` device cleanly in the public-API demo).

- **Read-Only `LICENSE` & Third-Party Dependency License Audit (Zero Files Created/Modified):**
  - **Repository License Status (Requires Owner Decision at `⛔ D12`):**
    - `duckdb-arrowtiles`: **No `LICENSE` file present on disk**; `pyproject.toml` and `arrowtiles-engine/Cargo.toml` omit `license`; `README.md` §Licensing currently states **CC BY-NC 4.0**.
    - `deepgraph-arrowtiles-sandbox`: **No `LICENSE` file present on disk**; `package.json` omits `license` (`"private": true`); `README.md` §Licensing currently states **CC BY-NC 4.0**.
  - **Viewer (`deepgraph-arrowtiles-sandbox`) Direct Runtime Dependencies (Bundled into `dist/`):**
    - `@bokuweb/zstd-wasm` `0.0.27` — **MIT**
    - `apache-arrow` `21.1.0` — **Apache-2.0**
    - `fflate` `0.8.3` — **MIT**
    - `p-queue` `9.3.1` — **MIT**
    - `pmtiles` `4.4.1` — **BSD-3-Clause**
    - *(Demo-only `devDependency`: `lil-gui` `0.21.0` — **MIT**, excluded from `dist/`)*
  - **Writer (`duckdb-arrowtiles`) Direct Python & Rust Dependencies:**
    - Python (`pyproject.toml`): `duckdb` `1.5.3` (**MIT**), `pmtiles` `3.7.0` (**BSD-3-Clause**), `pyarrow` `24.0.0` (**Apache-2.0**), `tqdm` `4.67.3` (**MPL-2.0 AND MIT**), `maturin` `1.14.1` (**MIT OR Apache-2.0**).
    - Rust (`arrowtiles-engine/Cargo.toml`): `arrow` `58.3.0` (**Apache-2.0**), `parquet` `58.3.0` (**Apache-2.0**), `pyo3` `0.23.5` (**MIT OR Apache-2.0**), `pyo3-log` `0.12.4` (**Apache-2.0 OR MIT**), `pmtiles` `0.23.0` (**MIT OR Apache-2.0**), `rayon` `1.12.0` (**MIT OR Apache-2.0**), `serde_json` `1.0.150` (**MIT OR Apache-2.0**), `base64` `0.22.1` (**MIT OR Apache-2.0**), `anyhow` `1.0.103` (**MIT OR Apache-2.0**), `log` `0.4.32` (**MIT OR Apache-2.0**), `fast_hilbert` `2.1.0` (**MIT**), `zstd` `0.13.3` (**MIT**). Across all `426` transitive crates in `Cargo.lock`, `424` are standard permissive (`MIT`/`Apache-2.0`/`BSD`/`ISC`/`Zlib`/`Unicode-3.0`) plus `attohttpc` `0.30.1` (**MPL-2.0**, unused optional HTTP transitive via `pmtiles`) and `webpki-roots` `1.0.7` (**CDLA-Permissive-2.0**); **zero GPL / AGPL / SSPL / CC BY-NC** third-party dependencies exist in either repo.

- **Not done / failed:**
  - **`LICENSE` creation/edits, `npm publish`, `maturin publish`, and `git push`:** Intentionally NOT performed — stopped cleanly at **`⛔ D12`**.

- **Questions for owner (`⛔ D12` Final Release & Publishing Stop Gate):**
  1. **Package Names (`⛔ D12a`):** Confirm final npm package name for `deepgraph-arrowtiles-sandbox` (e.g. `deepgraph` / `@deepgraph/plot`) and PyPI package name for `duckdb-arrowtiles` (currently `arrowtiles` in `pyproject.toml`).
  2. **Repository `LICENSE` Choice (`⛔ D12b`):** Both repos currently have no `LICENSE` file and carry `CC BY-NC 4.0` text in `README.md`, while all runtime dependencies across JS, Python, and Rust are OSI-compatible (`MIT` / `Apache-2.0` / `BSD-3-Clause` / file-level `MPL-2.0`). Which `LICENSE` should be added to each repo (and `SPEC.md`), and should `README.md` §Licensing be updated to match?
  3. **Remote Push & Registry Publish (`⛔ D12c`):** Ready to push `revival/2026-11-wip` to GitHub / open PRs, and when would you like to flip `"private": false` for `npm publish` / `maturin publish`?


## 2026-11-21 — `D12b` Apache-2.0 Licensing, `SPEC.md` `v0.1` `"tiling": "quadtree-2d"`, Phase 8b Multiscale Zoom-Adaptive Density & Per-Pixel Linear HDR Resolve, and Phase 8c Bundler/Standalone Split + `AbortSignal` (`3` Commits — Held at `⛔ D12a` / `D12c`)

- **Done:**
  1. **Commit 1 (`54e0c2a` in `duckdb-arrowtiles`, `9491f7e` in `deepgraph-arrowtiles-sandbox`) — `D12b` Apache-2.0 Licensing + `SPEC.md` `v0.1` Reserved `"tiling": "quadtree-2d"`:**
     - Added standard unmodified Apache License 2.0 `LICENSE` and `NOTICE` (`Copyright 2026 Robert Erlenbusch`) at the root of both `duckdb-arrowtiles` and `deepgraph-arrowtiles-sandbox` (zero per-file license headers).
     - Set `license = { text = "Apache-2.0" }` in `duckdb-arrowtiles/pyproject.toml`, `license = "Apache-2.0"` in `duckdb-arrowtiles/arrowtiles-engine/Cargo.toml`, and `"license": "Apache-2.0"` + `"files": ["dist", "docs/API.md", "LICENSE", "NOTICE"]` in `deepgraph-arrowtiles-sandbox/package.json` (preserving `"private": true` pending `⛔ D12a`/`D12c`), updated both `README.md` `"## 📄 Licensing"` sections (with ESA/Gaia/DPAC & LMSys-Chat-1M data attribution), and added a one-line Apache-2.0 header to `docs/SPEC.md`.
     - Added reserved `"tiling": "quadtree-2d"` to `docs/SPEC.md` (§1 & §6.4), `arrowtiles/builder.py` (`SPEC_TILING = "quadtree-2d"`, `RESERVED_METADATA_KEYS`), `arrowtiles/reader.py`, `arrowtiles/validator.py`, `tests/test_spec_tiling.py`, and `deepgraph-arrowtiles-sandbox/src/lib/DatasetSession.ts` + `src/lib/types.ts` (defaulting omitted `"tiling"` to `"quadtree-2d"` for backwards compatibility while rejecting unknown present values so future `"octree-3d"` archives fail fast in `v0.1` viewers).
  2. **Commit 2 (`c26f4c6` in `deepgraph-arrowtiles-sandbox`) — Phase 8b Multiscale Zoom-Adaptive Density & Zero-Shimmer Per-Pixel Linear HDR Resolve:**
     - **Zero-Shimmer Linear HDR Mode 0/3 Accumulation (`src/core/ComputeRasterizer.ts`):** Removed per-star `three_aces_filmic` (`-0.000090537` toe) + `linear_to_srgb` and `rand255` stochastic skip from `splat_optical_pixel`. Accumulates deterministic linear radiometric flux (`word0` at scale `1.0 = 65536.0`, saturation-gated `< 0x80000000u`) and exact flux-weighted color scalar sum (`word1 = Σ(fClamped * tU255)` with `tU255 ∈ [0..255]` mapped across active `[u.colorMin, u.colorMax]`, gated on the exact same `fluxU` scale at `prevFlux < 16777215u`, `16,777,215 × 255 = 4,278,190,075 < 2^32`), evaluating the linear Gaia blackbody curve + ACES filmic + sRGB **once per screen pixel** in `fs_main`.
     - **Continuous Unclamped `logZoom` Sizing, Faint-Star Deep-Zoom Reveal, Pan-Stable Auto-Exposure & Mode 1 `refCount` (`Renderer.ts`, `TileGpuStore.ts`, `ComputeRasterizer.ts`, `PickingLayer.ts`):** Exposed unclamped `Renderer.logZoom = max(0, log2(camera.zoom))`, drove splat diameter smoothly via `pointSize * pow(2.0, logZoom * zoomBalance)`, relaxed `maxMagCutoff` up to `22.0` (`bin = 15` clamped in `computeSlotMagBins`), computed viewport-intersected on-screen point density via exact `Float64` `RTC` bounds with stationary-frame bit-exact exposure lock (`0.0%` pan pumping), decayed Mode 1 `refCount` smoothly from `96.0` to `1.15` across `Z=0..12+`, and expanded `PickingLayer` hit windows automatically for enlarged `pointSize`.
     - **Public Multiscale & HDR API + Controls (`src/lib/types.ts`, `src/lib/ViewState.ts`, `src/demo/ControlsPanel.ts`, `docs/API.md`):** Added `pointSize` (`1.0`), `zoomBalance` (`0.22`), `pointOpacity` (`'auto' | number`), and `exposure` (`'auto' | number`) to `DeepgraphEncoding`, `ViewOptionsPatch`, `ViewStateSnapshot`, and `'Multiscale & Tone Mapping'` controls in `ControlsPanel.ts`.
  3. **Commit 3 (Phase 8c) — Bundler (`dist/index.js`) vs. Standalone (`dist/standalone.js`) Build Split, Real Vite Consumer App Gate & `RowAttributeResolver` `AbortSignal`:**
     - **Bundler vs. Standalone Build Split (`vite.lib.config.ts`, `vite.standalone.config.ts`, `package.json`, `scripts/emit_dts.mjs`, `examples/embed.html`, `docs/API.md`):**
       - `dist/index.js` (`exports["."]`, **`188.30 kB` / `47.37 kB` gzip**, `-56.9%` smaller) externalizes main-thread `pmtiles`, `p-queue`, `fflate`, `apache-arrow`, and `@bokuweb/zstd-wasm` so downstream bundlers deduplicate shared packages cleanly.
       - `dist/standalone.js` (`exports["./standalone"]`, **`436.90 kB` / `100.73 kB` gzip**, `0` bare imports) bundles all runtime dependencies for zero-build `<script type="module">` HTML pages (`examples/embed.html`).
       - Both builds keep `dist/assets/pmtiles.worker-*.js` (`514.00 kB`) 100% self-contained (`0` bare imports + inlined `data:application/wasm;base64,...` `zstd.wasm`), asserted in `scripts/emit_dts.mjs`.
     - **Real Vite Consumer Application Verification (`scripts/verify_consumer_dts.mjs`):** Extended `npm run verify:types` to run external `tsc --noEmit` (`bundler` + `nodenext`, importing both `"."` and `"./standalone"`) **plus** a real `vite build` consumer app importing `{ Deepgraph }` alongside `{ vectorFromArray } from 'apache-arrow'`.
     - **Sidecar `AbortSignal` 4th Parameter & Pre-Call Guard (`src/lib/types.ts`, `src/lib/ViewerLayer.ts`, `docs/API.md`):** Added `signal?: AbortSignal` as the 4th parameter of `RowAttributeResolver`, guarded `if (this.destroyed || expectedGen !== this.loadGeneration || signal?.aborted) return null;` immediately before calling `resolveRowAttributes`, and wired `AbortController` cancellation across hover, click, `pickAt`, `load()`, and `destroy()`.

- **Evidence:**
  - **Writer `pytest` Suite (CPU-only):** `.venv\Scripts\python.exe -m pytest -v -rs -p no:cacheprovider` -> **`52 passed, 1 skipped in 17.10s`**.
  - **Phase 8b Before vs. After Acceptance Harness (`Intel xe-lpg iGPU`, `0 B` on RTX 5090):**
    - Mode 0 Stationary Shimmer (`gaia_sample`): **`0 / 171,864` changed pixels (`0.0000%`, `maxDelta = 0`)**.
    - Galactic Core FPS (`gaia_full`): `Z=2` `101.9 -> 104.7 fps` (**`+2.7%`**), `Z=3` `65.8 -> 69.9 fps` (**`+6.2%`**), `0.00%` pure-white clipping.
    - LMC Deep Zoom (`Z=3 -> Z=7 -> Z=8 -> Z=10`, `zoom = 3.2 / 36 / 114 / 358`): mean lit brightness `122.92 -> 65.55 -> 44.69 -> 28.47` (`BEFORE` fade-out) became **`108.83 -> 145.24 -> 163.15 -> 114.86`** (`p99 = 170 / 227 / 226 / 203`, `0.00%` clipping).
    - M31 Andromeda (`zoom = 48`): center ROI `meanLitBrightness = 27.91 -> 75.91`, `p99 = 52 -> 172` (`+230.8%`).
    - Pan LMC → Empty Sky (`zoom = 16`): `74.36 -> 74.36` (**`pumpingRatio = 1.000`**).
    - LMSys 2.84M (`Mode 1`): `Z=2` `88.02 -> 87.98` (`-0.05%`); `zoom = 64` `p99 = 129 -> 181` (`+40.3%`).
  - **Phase 8c Build, Consumer Vite Build & Intel-iGPU Playwright Suite (`0 B` on RTX 5090):**
    - `npm run typecheck`, `npm run build:lib`, `npm run verify:types` (incl. real `vite build` consumer app), `npm run build:demo`: **all `exit code 0`**.
    - `npx playwright test tests/library-embed.spec.ts tests/phase8b-hdr-density.spec.ts tests/picking-layer.spec.ts`: **`3 passed in 55.2s`** (`receivedAbortSignalInstance = true`, `signalAbortedOnDestroy = true`, `callsWhenAbortedBeforeResolver = 0`, `hoverSignalAbortedOnPointerLeave = true`, `liveDevices = 0, liveBuffers = 0, liveBytes = 0`).

- **Remaining Open Owner Gates (`⛔ D12a` / `D12c`):**
  1. **`⛔ D12a` (Final Package Names):** Final npm package name (currently `"deepgraph-arrowtiles-sandbox"`, `"private": true`) and PyPI package name (`"arrowtiles"`).
  2. **`⛔ D12c` (Remote Push & Registry Publish):** Pushing `revival/2026-11-wip` to GitHub and publishing to npm / PyPI remain gated on explicit owner instruction.


## 2026-11-21 — Post-Review Visual Restoration (`9491f7e` `R16 / G16 / B16` Optical RGB + `zoom > 36` Rescue), Pre-Publish `SPEC.md` `0.x` / `required_features` Gates & MuniLM `logs/` Backfill (`Held at ⛔ D12a / D12c`)

- **Done:**
  1. **Restored Exact Pre-8b (`9491f7e`) Mode 0/3 `R16 / G16 / B16` Optical RGB Pipeline + `zoom > 36` Deep-Zoom Rescue (`deepgraph-arrowtiles-sandbox` `a2e4da1`):**
     - Restored `9491f7e`'s verbatim `eval_color` optical RGB ramp stops, `three_aces_filmic`, `linear_to_srgb`, `splat_optical_pixel` (`word0 = R16 | (G16 << 16)`, `word1 = B16`, scale `1024.0`), Mode 3 star trails, and `fs_main` `min(ch, 1024u) / 1024.0` + `clamp(bg + rgb, 0, 1)` resolve in `src/core/ComputeRasterizer.ts` (preserving additive blue OB + golden red-clump mixing and incandescent white-gold bulge blooming while keeping `0.0000%` stationary shimmer).
     - Anchored `zoom <= 36` (`logZoom <= 5.20`, including `Z=2` `zoom=1.8`, `Z=3` `zoom=2.17` at `exposure = 1.0`, and `LMC Z=7` `zoom=36` at `exposure = 0.35`) bit-for-bit to `9491f7e`, and applied smooth continuous star-size growth past `zoom = 64` + gentle deep-zoom exposure/bright-star rescue strictly above `logZoom > 5.20` (`M31` `zoom=48`, `LMC Z=8` `zoom=114`, `M33` `zoom=180`, `LMC Z=10` `zoom=358`).
     - Kept the 4 clean public `ViewOptions` (`pointSize`, `zoomBalance`, `pointOpacity`, `exposure`) across `types.ts`, `ViewState.ts`, `ControlsPanel.ts`, and `docs/API.md` (`dist/index.js` = `187.22 kB` / **`46.62 kB` gzip**; `dist/standalone.js` = `435.82 kB` / **`99.97 kB` gzip**).
  2. **Pre-Publish `SPEC.md` `v0.1` `0.x` Minor-Version & `required_features` Gates (`duckdb-arrowtiles` + `deepgraph-arrowtiles-sandbox`):**
     - Updated `docs/SPEC.md` (§1 & §6.4), `arrowtiles/builder.py` (`RESERVED_METADATA_KEYS`), `arrowtiles/reader.py`, `arrowtiles/validator.py`, `tests/test_spec_tiling.py`, and `src/lib/DatasetSession.ts` + `tests/phase8b-hdr-density.spec.ts` so `0.x` readers/validators reject `minor > 1` (`"0.2"` rejected) and reject malformed or unrecognized `"required_features": string[]` entries while accepting `[]` / omitted.
  3. **MuniLM `logs/` Backfill (`duckdb-arrowtiles/logs/`):**
     - Persisted `2026-11-21_05_WALKTHROUGH_viewer_phase-8b-visual-comparison-and-tuning.md` (with local comparison PNGs copied to `logs/assets/2026-11-21_05_*.png`), `2026-11-21_06_RESEARCH_all_2-5d-and-octree-tiling.md`, and `2026-11-21_07_RESEARCH_all_post-v0-1-format-improvements.md`, and indexed all three in `logs/README.md`.

- **Evidence (`Intel xe-lpg iGPU`, `0 B` on RTX 5090):**
  - **`Z <= 7` Bit-Exact Colour Match vs. `9491f7e` (`gaia_full.arrowtiles`):**
    - `Z=2` (`zoom = 1.8`): `mean |ΔRGB| = 0.0000` (`maxAbsDiff = 0`, `ROI = 115.78`, `Chroma = 73.01`).
    - `Z=3` (`zoom = 2.17`): `mean |ΔRGB| = 0.0000` (`maxAbsDiff = 0`, `ROI = 213.35`, `Chroma = 109.96`, `0 / 962,054` shimmer).
    - `LMC Z=7` (`zoom = 36`): `mean |ΔRGB| = 0.0166` (`maxAbsDiff = 1`, `ROI = 120.18 vs 120.17`, `Contrast = 14.54×`, `Chroma = 67.75 vs 67.74`).
  - **`zoom > 36` Deep-Zoom Rescue (`gaia_full.arrowtiles`):**
    - `LMC Z=8` (`zoom = 114`): `ROI = 60.34 -> 165.70`, `p99 = 104.8 -> 255.0`, `Contrast = 3.43× -> 3.49×`.
    - `LMC Z=10` (`zoom = 358`): `ROI = 24.05 -> 98.50`, `p99 = 49.4 -> 253.0`, `Contrast = 1.89× -> 1.95×`, `0 / 899,827` (`0.0000%`) shimmer.
    - `Andromeda M31` (`zoom = 48`): `ROI = 24.15 -> 34.64`, `p99 = 60.0 -> 109.3` (`+82.2%`).
    - `Triangulum M33` (`Z=9`, `zoom = 180`): `ROI = 17.47 -> 21.63`, `p99 = 45.7 -> 138.6` (`+203.3%`), `Contrast = 0.47× -> 1.63×`, `Dark = 93.04%`.
  - **Automated Suites:**
    - Writer `pytest`: **`53 passed, 1 skipped in 22.70s`**.
    - Viewer `typecheck` + `build:lib` + `verify:types` + `build:demo` + `3` Playwright specs (`library-embed`, `phase8b-hdr-density`, `picking-layer`): **all PASS** (`liveDevices = 0`, `liveBytes = 0`).
