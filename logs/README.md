# ArrowTiles & DeepGraph — Engineering, Research & Audit Logs (`logs/`)

All deep research memos, read-only forensic audits, implementation plans, architectural decision records (ADRs), and post-execution walkthroughs are persisted here so institutional context lives permanently in Git rather than disappearing inside ephemeral IDE/agent session folders.

> Note: `.gitignore` uses `logs/*`, `!logs/README.md`, and `!logs/20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9]_*.md` so structured MuniLM-convention logs are tracked in Git while historic multi-megabyte raw session transcripts in `logs/` remain untracked on disk.

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
| `2026-11-19_05` | `PLAN` | `all` | [`2026-11-19_05_PLAN_all_merged-consensus-revival-plan.md`](2026-11-19_05_PLAN_all_merged-consensus-revival-plan.md) | Approved merged consensus revival plan (Phases 0–7) uniting `IMPLEMENTATION_PLAN_2026-11-19_revised.md` with all 5 verified Gemini + Claude review patches. |
| `2026-11-19_06` | `WALKTHROUGH` | `all` | [`2026-11-19_06_WALKTHROUGH_all_phase-1-spec-package-and-viewer.md`](2026-11-19_06_WALKTHROUGH_all_phase-1-spec-package-and-viewer.md) | Phase 1 completion walkthrough: `SPEC.md` v0.1, `arrowtiles/` PyO3 package, validator/reader, `<20 MiB` sample builder (`13 passed`), and Phase 1b WebGPU viewer compatibility (`0` console/page errors). |
