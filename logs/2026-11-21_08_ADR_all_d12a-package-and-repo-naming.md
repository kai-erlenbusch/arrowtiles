---
log_id: 2026-11-21_08
date: 2026-11-21
type: ADR
status: approved
scope: [all]
source_artifact: null
conversation_id: e91adbce-084e-445b-98b1-a434c428c86d
---

# ADR (`D12a`): Final Package & Repository Naming (`arrowtiles` + `deepgraph` / `pydeepgraph`)

## 1. Context & Registry Audit (`2026-11-21`)

Gate `⛔ D12a` required locking the permanent public package and repository names for both sibling repositories prior to `v0.1.0` publication, accounting for planned future node-link / graph edge rendering in the WebGPU engine and live registry availability across PyPI, npm, and crates.io:

| Name | PyPI | npm | crates.io | Role |
| :--- | :---: | :---: | :---: | :--- |
| **`arrowtiles`** | **Available** | **Available** (`0` hits) | **Available** | `.arrowtiles` format builder, reader, validator, and CLI |
| **`deepgraph`** | Taken (`v1.2.0`, 2025-07-01) | **Available** | — | Pure-WebGPU billion-point & graph visualization engine |
| **`pydeepgraph`** | **Available** | **Available** | **Available** | Future Python / Jupyter `anywidget` wrapper (`pydeck` / `pyvis` pattern) |

## 2. Decision (Owner Approved — Path 1)

1. **Format & Builder Repository (`arrowtiles`):**
   - **PyPI package:** `"arrowtiles"` (`pip install arrowtiles`, CLI `arrowtiles`)
   - **Target GitHub repository:** `https://github.com/kai-erlenbusch/arrowtiles` *(to be renamed on GitHub from `duckdb-arrowtiles` during `D12c`)*
2. **WebGPU Point & Graph Engine Repository (`deepgraph`):**
   - **npm package:** `"deepgraph"` (`npm install deepgraph`, plus `./standalone` subpath `deepgraph/standalone`)
   - **Target GitHub repository:** `https://github.com/kai-erlenbusch/deepgraph` *(dropping `-arrowtiles-sandbox` during `D12c`)*
   - **Future Python / Jupyter widget package:** `"pydeepgraph"` (`pip install pydeepgraph`)
3. **Local Folder Compatibility & Pre-Publish Safety:**
   - Sibling path lookups in `vite.config.ts`, `tests/conftest.py`, `tests/phase8b-hdr-density.spec.ts`, and `scripts/` prefer `arrowtiles` / `deepgraph` first and automatically fall back to `duckdb-arrowtiles` / `deepgraph-arrowtiles-sandbox` so tests and benchmarks work both before and after local directory renaming.
   - `"private": true` remains set in `package.json` until owner gate `⛔ D12c` (explicit push & publish).
