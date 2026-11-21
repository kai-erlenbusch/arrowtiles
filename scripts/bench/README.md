# Phase 4 Container Benchmark Harness (`.arrowtiles` vs. Sorted HTTP-Range Parquet)

Reproducible Chrome Web Worker benchmark harness backing [`docs/BENCHMARK_parquet_vs_arrowtiles.md`](../../docs/BENCHMARK_parquet_vs_arrowtiles.md).

## Prerequisites

1. Build sample/benchmark datasets into `samples/_tmp_phase4_parquet_bench/`:
   ```bash
   # Full suite (gaia_sample, lmsys_sample, lmsys_full, gaia_100m):
   .venv/Scripts/python scripts/bench/build_phase4_datasets.py

   # Or only lmsys_full (2.84M rows):
   .venv/Scripts/python scripts/bench/build_phase4_datasets.py --only lmsys_full
   ```
2. Install browser worker dependencies locally in `scripts/bench/` (`node_modules/` is gitignored):
   ```bash
   cd scripts/bench
   npm install
   ```

## Running the Benchmark

```bash
# Unthrottled loopback HTTP Range (5 runs each, Median + P95):
node scripts/bench/run_phase4_browser_bench.mjs

# Throttled WAN simulation (50 ms RTT, 50 Mbps download/upload via Chrome CDP) on lmsys_full:
node scripts/bench/run_phase4_browser_bench.mjs --only lmsys_full --throttle-50mbps
```

Clean up temporary Parquet files in `samples/_tmp_phase4_parquet_bench/` after runs.
