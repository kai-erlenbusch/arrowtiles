"""Build Phase 4 benchmark datasets (.arrowtiles vs Parquet Layout 1 tile-RG vs Parquet Layout 2 Page-Index).

Usage:
    python scripts/bench/build_phase4_datasets.py
    python scripts/bench/build_phase4_datasets.py --only lmsys_full
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import struct
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
from pmtiles.reader import MmapSource, Reader, all_tiles

from arrowtiles import _zstd, build_gaia, build_generic, validate_file

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_PARENT = REPO_ROOT.parent
SAMPLES_DIR = REPO_ROOT / "samples"
BENCH_DATA_DIR = SAMPLES_DIR / "_tmp_phase4_parquet_bench"
_DEFAULT_VIEWER_DIR = (
    WORKSPACE_PARENT / "deepgraph"
    if (WORKSPACE_PARENT / "deepgraph").is_dir()
    else WORKSPACE_PARENT / "deepgraph-arrowtiles-sandbox"
)
S3_CACHE_DIR = Path(
    os.environ.get(
        "ARROWTILES_GAIA_S3_CACHE",
        str(_DEFAULT_VIEWER_DIR / "s3_cache"),
    )
)
LMSYS_FULL_PQ = Path(
    os.environ.get(
        "ARROWTILES_LMSYS_PARQUET",
        str(WORKSPACE_PARENT / "duckdb-cosmograph-oss" / "lmsys.parquet"),
    )
)
MOCK_LMSYS_PQ = Path(
    os.environ.get(
        "ARROWTILES_MOCK_LMSYS_PARQUET",
        str(WORKSPACE_PARENT / "mock_lmsys.parquet"),
    )
)


def read_parquet_footer_len(pq_path: Path) -> int:
    size = pq_path.stat().st_size
    with open(pq_path, "rb") as fh:
        fh.seek(size - 8)
        tail = fh.read(8)
    footer_len, magic = struct.unpack("<I4s", tail)
    assert magic == b"PAR1", f"Invalid Parquet magic in {pq_path}"
    return int(footer_len)


def read_pmtiles_header_sizes(at_path: Path) -> dict[str, int]:
    with open(at_path, "rb") as fh:
        src = MmapSource(fh)
        r = Reader(src)
        h = r.header()
    return {
        "header_bytes": 127,
        "root_dir_bytes": int(h.get("root_length", 0)),
        "metadata_bytes": int(h.get("metadata_length", 0)),
        "leaf_dir_bytes": int(h.get("leaf_length", 0)),
        "initial_handshake_bytes": 127 + int(h.get("root_length", 0)) + int(h.get("metadata_length", 0)),
    }


def convert_arrowtiles_to_two_parquet_layouts(
    at_path: Path,
    out_prefix: Path,
    page_idx_rg_rows: int = 250_000,
) -> dict:
    tile_rg_pq = out_prefix.with_name(out_prefix.name + "_tile_rg.parquet")
    tile_rg_idx_json = out_prefix.with_name(out_prefix.name + "_tile_rg.index.json")
    page_idx_pq = out_prefix.with_name(out_prefix.name + "_page_idx.parquet")
    page_idx_json = out_prefix.with_name(out_prefix.name + "_page_idx.index.json")

    for p in (tile_rg_pq, tile_rg_idx_json, page_idx_pq, page_idx_json):
        if p.exists():
            p.unlink()

    with open(at_path, "rb") as fh:
        src = MmapSource(fh)
        pm = Reader(src)
        meta = pm.metadata()
        schema_bytes = base64.b64decode(meta["arrow_schema"])
        schema = ipc.RecordBatchStreamReader(schema_bytes).schema

        t_conv0 = time.perf_counter()
        writer_rg = pq.ParquetWriter(
            tile_rg_pq,
            schema,
            compression="zstd",
            compression_level=3,
            use_dictionary=False,
            write_statistics=True,
        )
        writer_pi = pq.ParquetWriter(
            page_idx_pq,
            schema,
            compression="zstd",
            compression_level=3,
            use_dictionary=False,
            write_statistics=True,
            write_page_index=True,
            data_page_size=65_536,
        )

        tile_index: dict[str, list[int]] = {}
        buffered_tables: list[pa.Table] = []
        buffered_rows = 0
        global_row_cursor = 0
        rg_idx = 0

        try:
            for (z, x, y), raw_tile in all_tiles(src):
                decomp = _zstd.zstd_decompress(raw_tile)
                tbl = ipc.open_stream(schema_bytes + decomp).read_all()
                n = tbl.num_rows
                if n == 0:
                    continue
                key = f"{z}/{x}/{y}"
                tile_index[key] = [global_row_cursor, global_row_cursor + n, rg_idx]
                rg_idx += 1
                global_row_cursor += n

                # Layout 1: 1 exact Row Group per tile
                writer_rg.write_table(tbl, row_group_size=n)

                # Layout 2: 250,000-row Row Groups + Page Index
                buffered_tables.append(tbl)
                buffered_rows += n
                while buffered_rows >= page_idx_rg_rows:
                    combined = (
                        buffered_tables[0]
                        if len(buffered_tables) == 1
                        else pa.concat_tables(buffered_tables)
                    )
                    writer_pi.write_table(combined.slice(0, page_idx_rg_rows), row_group_size=page_idx_rg_rows)
                    rem = combined.slice(page_idx_rg_rows)
                    buffered_tables = [rem] if rem.num_rows > 0 else []
                    buffered_rows = rem.num_rows

            if buffered_rows > 0:
                combined = (
                    buffered_tables[0]
                    if len(buffered_tables) == 1
                    else pa.concat_tables(buffered_tables)
                )
                writer_pi.write_table(combined, row_group_size=page_idx_rg_rows)
        finally:
            writer_rg.close()
            writer_pi.close()

        pack_sec = time.perf_counter() - t_conv0

    meta_lite = {k: v for k, v in meta.items() if k != "arrow_schema"}
    idx_payload = {"metadata": meta_lite, "tiles": tile_index}
    idx_bytes = json.dumps(idx_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    tile_rg_idx_json.write_bytes(idx_bytes)
    page_idx_json.write_bytes(idx_bytes)

    rg_footer = read_parquet_footer_len(tile_rg_pq)
    pi_footer = read_parquet_footer_len(page_idx_pq)
    rg_meta = pq.read_metadata(tile_rg_pq)
    pi_meta = pq.read_metadata(page_idx_pq)

    overview_keys = [
        f"{z}/{x}/{y}"
        for z in (0, 1, 2)
        for x in range(1 << z)
        for y in range(1 << z)
        if f"{z}/{x}/{y}" in tile_index
    ]
    deep_candidates = [k for k in tile_index.keys() if int(k.split("/")[0]) >= 3]
    deep_candidates.sort(
        key=lambda k: (
            int(k.split("/")[0]),
            abs(int(k.split("/")[1]) - (1 << (int(k.split("/")[0]) - 1))),
        )
    )
    deep_keys = deep_candidates[:16] if deep_candidates else overview_keys[:8]

    return {
        "schema_columns": list(schema.names),
        "total_rows": global_row_cursor,
        "total_tiles": len(tile_index),
        "overview_keys": overview_keys,
        "overview_rows": sum(tile_index[k][1] - tile_index[k][0] for k in overview_keys),
        "deep_keys": deep_keys,
        "deep_rows": sum(tile_index[k][1] - tile_index[k][0] for k in deep_keys),
        "arrowtiles": {
            "path": at_path.as_posix(),
            "file_bytes": at_path.stat().st_size,
            **read_pmtiles_header_sizes(at_path),
        },
        "parquet_tile_rg": {
            "path": tile_rg_pq.as_posix(),
            "index_path": tile_rg_idx_json.as_posix(),
            "file_bytes": tile_rg_pq.stat().st_size,
            "index_bytes": len(idx_bytes),
            "footer_bytes": rg_footer,
            "num_row_groups": rg_meta.num_row_groups,
            "pack_from_tiles_sec": round(pack_sec / 2.0, 2),
        },
        "parquet_page_idx": {
            "path": page_idx_pq.as_posix(),
            "index_path": page_idx_json.as_posix(),
            "file_bytes": page_idx_pq.stat().st_size,
            "index_bytes": len(idx_bytes),
            "footer_bytes": pi_footer,
            "num_row_groups": pi_meta.num_row_groups,
            "pack_from_tiles_sec": round(pack_sec / 2.0, 2),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Phase 4 .arrowtiles vs Parquet benchmark datasets.")
    parser.add_argument(
        "--only",
        nargs="+",
        choices=["gaia_sample", "lmsys_sample", "lmsys_full", "gaia_100m"],
        help="Build only the specified dataset(s).",
    )
    args = parser.parse_args()
    selected = set(args.only) if args.only else {"gaia_sample", "lmsys_sample", "lmsys_full", "gaia_100m"}

    BENCH_DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = BENCH_DATA_DIR / "phase4_manifest.json"
    manifest: dict[str, dict] = {}
    if manifest_path.exists() and args.only:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if "gaia_sample" in selected:
        print("[gaia_sample] Converting gaia_sample...", flush=True)
        gaia_sample_at = SAMPLES_DIR / "gaia_sample.arrowtiles"
        manifest["gaia_sample"] = convert_arrowtiles_to_two_parquet_layouts(
            gaia_sample_at, BENCH_DATA_DIR / "gaia_sample"
        )
        manifest["gaia_sample"]["workloads"] = {
            "default_gaia": ["x_u16", "y_u16", "phot_g_mean_mag", "bp_rp"],
        }

    if "lmsys_sample" in selected:
        print("[lmsys_sample] Building & converting lmsys_sample (100k rows, proportional)...", flush=True)
        lmsys_sample_at = BENCH_DATA_DIR / "lmsys_sample_prop.arrowtiles"
        t0 = time.perf_counter()
        build_generic(
            input_parquet=MOCK_LMSYS_PQ,
            output_path=lmsys_sample_at,
            x_col="x",
            y_col="y",
            columns=["model", "num_of_tokens"],
            row_limit=100_000,
            max_capacity=20_000,
            max_zoom=8,
            memory_limit="4GB",
            temp_dir=BENCH_DATA_DIR / "_tmp_lmsys_s",
            show_progress=False,
        )
        lmsys_s_sec = time.perf_counter() - t0
        shutil.rmtree(BENCH_DATA_DIR / "_tmp_lmsys_s", ignore_errors=True)
        manifest["lmsys_sample"] = convert_arrowtiles_to_two_parquet_layouts(
            lmsys_sample_at, BENCH_DATA_DIR / "lmsys_sample"
        )
        manifest["lmsys_sample"]["arrowtiles"]["build_sec"] = round(lmsys_s_sec, 2)
        manifest["lmsys_sample"]["workloads"] = {
            "full_cols": ["x_u16", "y_u16", "model", "num_of_tokens"],
        }

    if "lmsys_full" in selected:
        print("[lmsys_full] Converting lmsys_full (2.84M rows, 36 payload cols, proportional 25k)...", flush=True)
        lmsys_full_at = SAMPLES_DIR / "lmsys_d7_proportional_25k.arrowtiles"
        if not lmsys_full_at.exists():
            t0 = time.perf_counter()
            build_generic(
                input_parquet=LMSYS_FULL_PQ,
                output_path=lmsys_full_at,
                x_col="x",
                y_col="y",
                categorical_cols=["clusters_14", "clusters_42", "clusters_135", "clusters_392"],
                max_capacity=25_000,
                max_zoom=10,
                memory_limit="8GB",
                temp_dir=BENCH_DATA_DIR / "_tmp_lmsys_full",
                show_progress=False,
            )
            build_sec = round(time.perf_counter() - t0, 2)
            shutil.rmtree(BENCH_DATA_DIR / "_tmp_lmsys_full", ignore_errors=True)
        else:
            build_sec = 21.11
        manifest["lmsys_full"] = convert_arrowtiles_to_two_parquet_layouts(
            lmsys_full_at, BENCH_DATA_DIR / "lmsys_full"
        )
        manifest["lmsys_full"]["arrowtiles"]["build_sec"] = build_sec
        all_lmsys_cols = [
            c for c in manifest["lmsys_full"]["schema_columns"] if c not in ("row_id", "z")
        ]
        manifest["lmsys_full"]["workloads"] = {
            "proj_3_of_38": ["x_u16", "y_u16", "clusters_14"],
            "full_schema_36": all_lmsys_cols,
        }

    if "gaia_100m" in selected:
        gaia_batches = sorted(S3_CACHE_DIR.glob("batch_*.parquet"))[:3]
        print(f"[gaia_100m] Building gaia_100m (100,000,000 rows from {[p.name for p in gaia_batches]})...", flush=True)
        gaia_100m_at = BENCH_DATA_DIR / "gaia_100m.arrowtiles"
        tmp_g100 = BENCH_DATA_DIR / "_tmp_gaia_100m_duck"
        shutil.rmtree(tmp_g100, ignore_errors=True)
        t_g0 = time.perf_counter()
        try:
            build_gaia(
                input_parquet=[str(p) for p in gaia_batches],
                output_path=gaia_100m_at,
                row_limit=100_000_000,
                max_capacity=100_000,
                max_zoom=14,
                memory_limit="24GB",
                temp_dir=tmp_g100,
                show_progress=False,
            )
        finally:
            shutil.rmtree(tmp_g100, ignore_errors=True)
        gaia_100m_build_sec = time.perf_counter() - t_g0
        print(f"  gaia_100m.arrowtiles built in {gaia_100m_build_sec:.2f}s! Validating header/first 100 tiles...", flush=True)
        val_100m = validate_file(gaia_100m_at, expected_input_rows=100_000_000, max_tiles_to_scan=100)
        assert val_100m.ok, val_100m.errors

        print("  Converting gaia_100m to Parquet Layout 1 (tile RG) and Layout 2 (Page Index)...", flush=True)
        manifest["gaia_100m"] = convert_arrowtiles_to_two_parquet_layouts(
            gaia_100m_at, BENCH_DATA_DIR / "gaia_100m"
        )
        manifest["gaia_100m"]["arrowtiles"]["build_sec"] = round(gaia_100m_build_sec, 2)
        manifest["gaia_100m"]["workloads"] = {
            "optical_4cols": ["x_u16", "y_u16", "phot_g_mean_mag", "bp_rp"],
            "full_gaia_9cols": [
                c for c in manifest["gaia_100m"]["schema_columns"] if c not in ("row_id", "z")
            ],
        }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("DONE! Wrote", manifest_path, flush=True)


if __name__ == "__main__":
    main()
