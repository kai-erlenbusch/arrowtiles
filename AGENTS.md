# AGENTS.md — ArrowTiles (`arrowtiles`)

Engineering context, wire-format invariants, and verification commands for AI coding agents working in **ArrowTiles**.

---

## 1. Repository Scope & Sibling Boundary

- **This repository (`arrowtiles`):** DuckDB + Rust (`PyO3`) `.arrowtiles` `v0.1` spatial pyramid builder, reference Python reader, validator, CLI (`arrowtiles`), and canonical wire-format specification ([`docs/SPEC.md`](docs/SPEC.md)).
  - Target GitHub repository: `https://github.com/kai-erlenbusch/arrowtiles`
- **Sibling repository (`deepgraph`):** Pure-WebGPU billion-point and graph visualization engine (`npm install deepgraph`) that streams `.arrowtiles` archives over HTTP Range requests.
  - Located locally at `../deepgraph` (or `../deepgraph-arrowtiles-sandbox` prior to local folder rename).
  - Target GitHub repository: `https://github.com/kai-erlenbusch/deepgraph`
- Any change to `.arrowtiles` metadata keys, version gates, coordinate quantization, or tile compression **must** be updated in [`docs/SPEC.md`](docs/SPEC.md), enforced in both `arrowtiles/{reader,validator}.py` and `deepgraph/src/lib/DatasetSession.ts`, and covered by tests in both repositories.

---

## 2. Clean-Room Licensing Rule (`Apache-2.0`)

- ArrowTiles is licensed under **Apache License 2.0** (`LICENSE`, `NOTICE`).
- **NEVER** read, inspect, port, or copy code from `CC BY-NC-SA 4.0` repositories (`Quadfeather`, `deepscatter`, `deepscatter-source`, `gaia-deepscatter-study`). All bucketing, Hilbert ordering, and Arrow IPC packing logic must remain clean-room Apache-2.0 / MIT / BSD-compatible implementations.
- Do **not** add per-file license headers unless explicitly requested; root `LICENSE` and `NOTICE` are sufficient.

---

## 3. Source Layout

```text
arrowtiles/
├── __init__.py              # Public Python API exports (`build_generic`, `build_gaia`, `ArrowTilesReader`, `validate_file`, ...)
├── __main__.py              # CLI entry point (`arrowtiles build | validate | inspect`)
├── builder.py               # Single-pass DuckDB SQL preflight, Pass 1/2 orchestration & SHA-256 `--resume` manifest
├── reader.py                # Reference `.arrowtiles` v0.1 reader (`header`, `metadata`, `schema`, `list_tiles`, `read_tile`, `iter_tiles`)
├── validator.py             # Full SPEC v0.1 archive validator (`validate_file` -> `ValidationResult`)
└── _zstd.py                 # Zstandard decompression helper (Rust `_core` fast path + fallback)
arrowtiles-engine/
├── Cargo.toml               # `arrowtiles_core` PyO3 cdylib (`arrow`, `parquet`, `pmtiles`, `fast_hilbert`, `rayon`, `zstd`)
└── src/lib.rs               # Deterministic zero-atomic 2-stage `run_bucketer` + parallel Rayon Zstd PMTiles packer
docs/
├── SPEC.md                  # Canonical `.arrowtiles` v0.1 wire-format specification
├── BENCHMARK_parquet_vs_arrowtiles.md  # HTTP Range & browser decode benchmarks vs. GeoParquet/Parquet
└── PROGRESS_2026-11.md      # Chronological engineering ledger
scripts/
├── build_samples.py         # Builds `< 5 MiB` `samples/{gaia_sample,lmsys_sample}.arrowtiles` fixtures
└── bench/                   # Reproducible Parquet vs. ArrowTiles browser & Range benchmark suite
tests/                       # Pytest unit, determinism, completeness & spec-gate suites
```

---

## 4. Wire-Format, Determinism & Security Invariants (`docs/SPEC.md`)

1. **Forward/Backward Version & Feature Gates (`SPEC.md` §1 & §6.4):**
   - While `major == 0`, readers and validators **must** reject `minor > 1` (`"0.1"` accepted; `"0.2"` rejected).
   - `"tiling"` defaults to `"quadtree-2d"` when omitted; unknown tiling identifiers **must** be rejected.
   - `"required_features"` (`string[]`, `[]` or omitted in `v0.1`) **must** reject non-array values or any unrecognized feature string.
   - Archives lacking both `"format"` and `"version"` open in `v0.0` legacy compatibility mode with a clear warning.
2. **Bit-Identical SHA-256 Reproducibility:**
   - `run_bucketer` (`arrowtiles-engine/src/lib.rs`) uses a zero-atomic 2-stage pipeline: **Stage A** computes stateless `(ix_20, iy_20, h_20)` in parallel via Rayon; **Stage B** claims tile/sub-grid slots sequentially in strict `(priority_key, row_id ASC)` order.
   - JSON metadata is serialized with `sort_keys=True`. Re-running a build (with or without `--resume` against a matching `arrowtiles-partitions-v2` SHA-256 manifest) **must** produce a byte-identical `.arrowtiles` output.
3. **Out-of-Core, Column Pruning & SQL Safety Discipline:**
   - Never materialize multi-GB datasets into Python lists or NumPy/Pandas copies; stream Arrow `RecordBatchReader` batches between DuckDB and Rust (`arrow::ffi_stream`).
   - Generic builds omit unrequested `__index_level_<N>__` columns (`^__index_level_\d+__$`) and high-cardinality strings (`> max_categories`, recorded in `metadata.dropped_columns`), and downcast in-range `DOUBLE` (`Float64`) payload attributes (`|min|, |max| <= 3.4028234e38`) to `Float32` after `Float64` coordinate normalization and `Float64` `sort_col` ordering unless `--keep-float64` (`keep_float64=True`) is requested.
   - Always quote SQL identifiers via `ArrowTilesBuilder._quote_ident` and escape file paths via `_sql_path_expr`. Never enable DuckDB `allow_unsigned_extensions`.
   - Always close DuckDB connections deterministically (`with ArrowTilesBuilder(...)` / `with ArrowTilesReader(...)`) so temporary files can be unlinked cleanly on Windows.

---

## 5. Build & Verification Commands

```powershell
# Recompile the Rust PyO3 extension (`arrowtiles._core`) in release mode after editing `arrowtiles-engine/`:
$env:VIRTUAL_ENV = (Resolve-Path .\.venv).Path
maturin develop --release

# Install editable Python package + dev dependencies (`pytest`):
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" --no-build-isolation

# Run full pytest suite (53 tests, CPU-only):
.\.venv\Scripts\python.exe -m pytest -v -rs -p no:cacheprovider

# CLI smoke checks:
.\.venv\Scripts\python.exe -m arrowtiles validate samples\lmsys_sample.arrowtiles
.\.venv\Scripts\python.exe -m arrowtiles inspect samples\lmsys_sample.arrowtiles
```

- **Release Gate:** Do **not** run `git push` or `maturin publish` / `twine upload` unless explicitly instructed by the repository owner.

---

## 6. Engineering, Research & Audit Logs (`logs/`)

Persist substantive `RESEARCH`, read-only `AUDIT`, approved `PLAN`, locked `ADR`, and post-execution `WALKTHROUGH` documents in `logs/` following [`logs/README.md`](logs/README.md) (`YYYY-MM-DD_<seq>_<TYPE>_<scope>_<topic-slug>.md` with YAML frontmatter, indexed chronologically in `logs/README.md`). Never commit credentials, `.env` values, or binary artifacts (`logs/assets/` and `logs/old/` remain gitignored).
