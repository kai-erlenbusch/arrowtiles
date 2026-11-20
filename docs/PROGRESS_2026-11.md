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
