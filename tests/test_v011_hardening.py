"""Regression tests for ArrowTiles v0.1.1 hardening fixes."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.cffi as pc_ffi
import pytest
from pmtiles.reader import MmapSource, Reader
from pmtiles.tile import Compression, TileType
from pmtiles.writer import Writer as PmWriter

from arrowtiles import (
    ArrowTilesBuilder,
    ArrowTilesReader,
    _core,
    build_generic,
    validate_file,
)


def _rewrite_pmtiles_metadata(src_path: Path, dst_path: Path, mutate_fn: Any) -> None:
    """Copy a PMTiles archive while mutating its JSON metadata for negative validator tests."""
    with open(src_path, "rb") as f_in:
        src_source = MmapSource(f_in)
        r = Reader(src_source)
        header = dict(r.header())
        meta = json.loads(json.dumps(r.metadata()))
        mutate_fn(meta)

        with open(dst_path, "wb") as f_out:
            w = PmWriter(f_out)
            from pmtiles.reader import all_tiles, zxy_to_tileid

            for (z, x, y), raw in all_tiles(src_source):
                w.write_tile(zxy_to_tileid(z, x, y), raw)
            w.finalize(
                {
                    "tile_type": TileType.UNKNOWN,
                    "tile_compression": Compression.ZSTD,
                    "min_zoom": header["min_zoom"],
                    "max_zoom": header["max_zoom"],
                    "min_lon_e7": 0,
                    "min_lat_e7": 0,
                    "max_lon_e7": 0,
                    "max_lat_e7": 0,
                    "center_zoom": 0,
                    "center_lon_e7": 0,
                    "center_lat_e7": 0,
                },
                meta,
            )


def test_boolean_categorical_roundtrip_and_validator_null_count_check(tmp_path: Path) -> None:
    """Verify BOOLEAN categorical_cols do not wipe values to NULL, and validator catches null_count drift."""
    pq_path = tmp_path / "bool_cat.parquet"
    out_path = tmp_path / "bool_cat.arrowtiles"

    tbl = pa.table(
        {
            "x": [0.1, 0.2, 0.3, 0.4],
            "y": [0.1, 0.2, 0.3, 0.4],
            "is_bot": pa.array([True, False, None, True], type=pa.bool_()),
            "int_cat": pa.array([10, 20, 10, None], type=pa.int32()),
        }
    )
    import pyarrow.parquet as pq

    pq.write_table(tbl, pq_path)

    build_generic(
        input_parquet=pq_path,
        output_path=out_path,
        x_col="x",
        y_col="y",
        categorical_cols=["is_bot", "int_cat"],
        temp_dir=tmp_path / "t_bool",
        show_progress=False,
    )

    val = validate_file(out_path, expected_input_rows=4)
    assert val.ok, val.errors

    with ArrowTilesReader(out_path) as reader:
        t0 = reader.read_tile(0, 0, 0, decode_categories=True)
        assert t0 is not None
        rids = t0["row_id"].to_pylist()
        bots = t0["is_bot"].to_pylist()
        ints = t0["int_cat"].to_pylist()
        by_rid = {rids[i]: (bots[i], ints[i]) for i in range(len(rids))}
        assert by_rid == {
            0: ("true", "10"),
            1: ("false", "20"),
            2: (None, "10"),
            3: ("true", None),
        }

    # Mutate declared stats null_count and confirm validator catches silent NULL corruption
    corrupted = tmp_path / "bool_cat_bad_nulls.arrowtiles"
    _rewrite_pmtiles_metadata(
        out_path,
        corrupted,
        lambda m: m["stats"]["is_bot"].update({"null_count": 0}),
    )
    bad_val = validate_file(corrupted)
    assert not bad_val.ok
    assert any("null_count" in err and "is_bot" in err for err in bad_val.errors)


def test_direct_build_duplicate_id_col_rejected_and_u64_extremes_preserved(
    tmp_path: Path,
) -> None:
    """Verify ArrowTilesBuilder.build() rejects duplicate id_col and preserves > i32::MAX and > 2^53 - 1."""
    with ArrowTilesBuilder(
        memory_limit="512MB", temp_dir=tmp_path / "dup_id", show_progress=False
    ) as b:
        with pytest.raises(ValueError, match="not unique"):
            b.build(
                input_query="""
                    SELECT * FROM (VALUES
                        (100::UBIGINT, 0.1::DOUBLE, 0.2::DOUBLE, 1.0::FLOAT),
                        (100::UBIGINT, 0.3::DOUBLE, 0.4::DOUBLE, 2.0::FLOAT)
                    ) AS t(id, x_norm, y_norm, metric)
                """,
                output_path=tmp_path / "dup.arrowtiles",
                x_col="x_norm",
                y_col="y_norm",
                id_col="id",
            )

    # Test UInt64 row_id > i32::MAX (2_147_483_648) and > 2^53 - 1 (Gaia 64-bit source_id)
    extreme_ids = [
        0,
        2_147_483_647,
        2_147_483_648,
        5_000_000_000,
        9_007_199_254_740_992,
        6_917_528_997_577_384_320,
    ]
    pq_u64 = tmp_path / "u64_extremes.parquet"
    import pyarrow.parquet as pq

    pq.write_table(
        pa.table(
            {
                "source_id": pa.array(extreme_ids, type=pa.uint64()),
                "x": [0.1 * i for i in range(len(extreme_ids))],
                "y": [0.15 * i for i in range(len(extreme_ids))],
                "val": [float(i) for i in range(len(extreme_ids))],
            }
        ),
        pq_u64,
    )
    out_u64 = tmp_path / "u64_extremes.arrowtiles"
    build_generic(
        input_parquet=pq_u64,
        output_path=out_u64,
        x_col="x",
        y_col="y",
        id_col="source_id",
        temp_dir=tmp_path / "t_u64",
        show_progress=False,
    )
    val = validate_file(out_u64, expected_input_rows=len(extreme_ids))
    assert val.ok, val.errors
    with ArrowTilesReader(out_u64) as r:
        t0 = r.read_tile(0, 0, 0)
        assert t0 is not None
        assert sorted(t0["row_id"].to_pylist()) == extreme_ids


def test_sort_col_non_leakage_in_build_generic(tmp_path: Path) -> None:
    """Verify unrequested sort_col does not leak into exported tiles while preserving priority order."""
    pq_path = tmp_path / "sort_leak.parquet"
    import pyarrow.parquet as pq

    pq.write_table(
        pa.table(
            {
                "x": [0.1, 0.12, 0.14, 0.16, 0.18, 0.20],
                "y": [0.1, 0.12, 0.14, 0.16, 0.18, 0.20],
                "keep_me": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
                "sort_only": [600.0, 100.0, 500.0, 200.0, 400.0, 300.0],
            }
        ),
        pq_path,
    )

    out1 = tmp_path / "no_leak_cols.arrowtiles"
    build_generic(
        input_parquet=pq_path,
        output_path=out1,
        x_col="x",
        y_col="y",
        columns=["keep_me"],
        sort_col="sort_only",
        sort_dir="ASC",
        max_capacity=2,
        max_zoom=4,
        temp_dir=tmp_path / "t1",
        show_progress=False,
    )
    assert validate_file(out1, expected_input_rows=6).ok
    with ArrowTilesReader(out1) as r:
        assert "keep_me" in r.schema().names
        assert "sort_only" not in r.schema().names
        assert r.metadata()["priority"] == {
            "kind": "column",
            "column": "sort_only",
            "order": "asc",
        }
        t0 = r.read_tile(0, 0, 0)
        assert t0 is not None
        # Highest priority under sort_only ASC are row_id 1 (100.0) and row_id 3 (200.0)
        assert t0["row_id"].to_pylist() == [1, 3]

    # Second leak site: keep_source_xy=False when sort_col == x_col
    out2 = tmp_path / "no_leak_xy.arrowtiles"
    build_generic(
        input_parquet=pq_path,
        output_path=out2,
        x_col="x",
        y_col="y",
        keep_source_xy=False,
        sort_col="x",
        sort_dir="DESC",
        temp_dir=tmp_path / "t2",
        show_progress=False,
    )
    assert validate_file(out2, expected_input_rows=6).ok
    with ArrowTilesReader(out2) as r:
        assert "x" not in r.schema().names
        assert "y" not in r.schema().names
        assert r.metadata()["priority"] == {"kind": "column", "column": "x", "order": "desc"}


def test_narrow_span_float64_retention_and_utc_temporal_stats(tmp_path: Path) -> None:
    """Verify narrow-span Unix epochs stay Float64 and TIMESTAMP/DATE emit exact UTC epoch-ms stats."""
    pq_path = tmp_path / "temporal_epoch.parquet"
    con = duckdb.connect()
    con.execute("SET TimeZone = 'America/Chicago';")
    con.execute(
        f"""
        COPY (
            SELECT
                CAST((i % 32) / 32.0 AS DOUBLE) AS x,
                CAST((i // 32) / 32.0 AS DOUBLE) AS y,
                CAST(1767312000.0 + i AS DOUBLE) AS ts_sec_f64,
                CAST(i * 0.5 AS DOUBLE) AS wide_f64,
                TIMESTAMP '2026-01-02 00:00:00' + to_seconds(i) AS created_ts,
                DATE '2026-01-02' + CAST(i % 5 AS INTEGER) AS created_date
            FROM range(200) t(i)
        ) TO '{pq_path.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    out_path = tmp_path / "temporal_epoch.arrowtiles"
    build_generic(
        input_parquet=pq_path,
        output_path=out_path,
        x_col="x",
        y_col="y",
        keep_float64=False,
        temp_dir=tmp_path / "t_temp",
        show_progress=False,
    )

    val = validate_file(out_path, expected_input_rows=200)
    assert val.ok, val.errors

    with ArrowTilesReader(out_path) as r:
        # Narrow-span epoch DOUBLE retained as Float64, wide DOUBLE downcast to Float32
        assert r.schema().field("ts_sec_f64").type == pa.float64()
        assert r.schema().field("wide_f64").type == pa.float32()

        # Naive TIMESTAMP '2026-01-02 00:00:00' must equal exact UTC 1767312000000.0 ms (zero +6h TZ shift!)
        ts_stats = r.metadata()["stats"]["created_ts"]
        assert ts_stats["type"] == "numeric"
        assert ts_stats["min"] == 1_767_312_000_000.0
        assert ts_stats["max"] == 1_767_312_199_000.0
        assert ts_stats["null_count"] == 0

        date_stats = r.metadata()["stats"]["created_date"]
        assert date_stats["type"] == "numeric"
        assert date_stats["min"] == 1_767_312_000_000.0
        assert date_stats["max"] == 1_767_312_000_000.0 + 4 * 86_400_000.0


def test_resume_deleted_intermediate_partition_and_concurrent_default_temp_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify deleting z_0.parquet invalidates --resume cleanly and temp_dir=None is concurrency-safe."""
    monkeypatch.chdir(tmp_path)
    pq_path = tmp_path / "pts.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                CAST(((i * 97) % 500) / 500.0 AS DOUBLE) AS x,
                CAST(((i * 53) % 500) / 500.0 AS DOUBLE) AS y,
                CAST(i AS FLOAT) AS metric
            FROM range(300) t(i)
        ) TO '{pq_path.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    # --resume without explicit temp_dir must raise ValueError
    with pytest.raises(ValueError, match="explicit temp_dir"):
        build_generic(
            input_parquet=pq_path,
            output_path=tmp_path / "fail_resume.arrowtiles",
            x_col="x",
            y_col="y",
            resume=True,
            temp_dir=None,
            show_progress=False,
        )

    baseline = tmp_path / "baseline.arrowtiles"
    build_generic(
        input_parquet=pq_path,
        output_path=baseline,
        x_col="x",
        y_col="y",
        max_capacity=20,
        max_zoom=4,
        temp_dir=tmp_path / "t_base",
        show_progress=False,
    )
    baseline_sha = hashlib.sha256(baseline.read_bytes()).hexdigest()

    resume_temp = tmp_path / "t_resume"
    build_generic(
        input_parquet=pq_path,
        output_path=tmp_path / "unused.arrowtiles",
        x_col="x",
        y_col="y",
        max_capacity=20,
        max_zoom=4,
        temp_dir=resume_temp,
        show_progress=False,
        _pass1_only=True,
    )
    # Delete intermediate z_0.parquet while keeping deepest partition & manifest
    z0_file = resume_temp / "partitions" / "z_0.parquet"
    assert z0_file.is_file()
    z0_file.unlink()

    resumed_out = tmp_path / "resumed.arrowtiles"
    res_info = build_generic(
        input_parquet=pq_path,
        output_path=resumed_out,
        x_col="x",
        y_col="y",
        max_capacity=20,
        max_zoom=4,
        resume=True,
        temp_dir=resume_temp,
        show_progress=False,
    )
    assert res_info["resumed_pass1"] is False
    assert hashlib.sha256(resumed_out.read_bytes()).hexdigest() == baseline_sha

    # Concurrent temp_dir=None builds in the same CWD must not clobber each other or leave ./duckdb_temp
    def _worker(idx: int) -> Path:
        out = tmp_path / f"conc_{idx}.arrowtiles"
        build_generic(
            input_parquet=pq_path,
            output_path=out,
            x_col="x",
            y_col="y",
            max_capacity=25,
            max_zoom=4,
            temp_dir=None,
            threads=2,
            show_progress=False,
        )
        return out

    with ThreadPoolExecutor(max_workers=2) as pool:
        outs = list(pool.map(_worker, [0, 1]))

    for out_f in outs:
        assert validate_file(out_f, expected_input_rows=300).ok
        assert hashlib.sha256(out_f.read_bytes()).hexdigest() == baseline_sha or validate_file(out_f).ok
    assert not (tmp_path / "duckdb_temp").exists()


def test_validator_strict_int_bool_rejection_and_windows_mmap_unlink(tmp_path: Path) -> None:
    """Verify validator rejects bool/string integer metadata and releases mmap on corrupt directories."""
    pq_path = tmp_path / "v.parquet"
    import pyarrow.parquet as pq

    pq.write_table(pa.table({"x": [0.1, 0.9], "y": [0.2, 0.8], "m": [1.0, 2.0]}), pq_path)
    good = tmp_path / "good.arrowtiles"
    build_generic(
        input_parquet=pq_path,
        output_path=good,
        x_col="x",
        y_col="y",
        temp_dir=tmp_path / "tv",
        show_progress=False,
    )

    bad_types = tmp_path / "bad_types.arrowtiles"
    _rewrite_pmtiles_metadata(
        good,
        bad_types,
        lambda m: m.update(
            {
                "total_rows": "2",
                "max_tile_rows": True,
                "grid_size": False,
                "bounds": {"min_x": True, "max_x": 1.0, "min_y": 0.0, "max_y": 1.0},
            }
        ),
    )
    res_bad = validate_file(bad_types)
    assert not res_bad.ok
    assert any("metadata.total_rows must be an integer" in e for e in res_bad.errors)
    assert any("metadata.max_tile_rows must be an integer" in e for e in res_bad.errors)
    assert any("metadata.grid_size must be an integer" in e for e in res_bad.errors)
    assert any("bounds.min_x must be a finite number" in e for e in res_bad.errors)

    # Corrupt directory / truncated archive must return ok=False and immediately unlink on Windows
    raw_bytes = bytearray(good.read_bytes())
    # Corrupt root directory bytes right after 127-byte PMTiles header
    for i in range(127, min(len(raw_bytes), 180)):
        raw_bytes[i] = 0xFF
    corrupt_dir = tmp_path / "corrupt_dir.arrowtiles"
    corrupt_dir.write_bytes(bytes(raw_bytes))

    res_corrupt = validate_file(corrupt_dir)
    assert not res_corrupt.ok
    corrupt_dir.unlink()
    assert not corrupt_dir.exists()


def test_rust_core_reserved_keys_utf8view_cast_64mib_cap_ffi_release_and_scoped_pool(
    tmp_path: Path,
) -> None:
    """Verify Rust _core reserved keys, Utf8View->Utf8 cast, >64MiB tile rejection, FFI release, and scoped pool."""
    schema_view = pa.schema(
        [
            pa.field("row_id", pa.uint64(), nullable=False),
            pa.field("x_u16", pa.uint16(), nullable=False),
            pa.field("y_u16", pa.uint16(), nullable=False),
            pa.field("z", pa.uint8(), nullable=False),
            pa.field("label_view", pa.string_view(), nullable=True),
            pa.field("bin_view", pa.binary_view(), nullable=True),
            pa.field("dec_neg", pa.decimal128(10, -2), nullable=True),
            pa.field("final_tile_id", pa.uint64(), nullable=False),
        ]
    )

    def _export_schema(s: pa.Schema) -> tuple[Any, int]:
        rdr = pa.RecordBatchReader.from_batches(s, [])
        cs = pc_ffi.ffi.new("struct ArrowArrayStream*")
        p = int(pc_ffi.ffi.cast("uintptr_t", cs))
        rdr._export_to_c(p)
        return cs, p

    # 1. Reject custom_metadata 'tiling' and 'required_features'
    for reserved_key in ("tiling", "required_features"):
        _cs, ptr = _export_schema(schema_view)
        with pytest.raises(ValueError, match="reserved"):
            _core.ArrowTilesPacker(
                str(tmp_path / f"res_{reserved_key}.arrowtiles"),
                ptr,
                10_000,
                0,
                1000,
                '{"format":"arrowtiles","version":"0.1"}',
                json.dumps({reserved_key: "bad"}),
            )

    # 2. Scoped Rayon thread pool respects per-instance rayon_threads & casts Utf8View -> Utf8
    _cs2, ptr2 = _export_schema(schema_view)
    spec_meta = {
        "format": "arrowtiles",
        "version": "0.1",
        "tiling": "quadtree-2d",
        "bounds": {"min_x": 0.0, "max_x": 1.0, "min_y": 0.0, "max_y": 1.0},
        "priority": {"kind": "random", "seed": 42},
        "sampling": "proportional",
        "grid_size": 16,
        "nominal_max_zoom": 0,
        "tile_capacity": 100,
        "max_tile_rows": 100,
        "total_rows": 3,
        "dropped_rows": 0,
        "dropped_columns": [],
        "stats": {},
    }
    out_view = tmp_path / "utf8view_cast.arrowtiles"
    packer2 = _core.ArrowTilesPacker(
        str(out_view),
        ptr2,
        10_000,
        0,
        100,
        json.dumps(spec_meta),
        None,
        2,
    )
    assert packer2.rayon_threads == 2

    _cs6, ptr6 = _export_schema(schema_view)
    packer6 = _core.ArrowTilesPacker(
        str(tmp_path / "pool6.arrowtiles"),
        ptr6,
        10_000,
        0,
        100,
        json.dumps(spec_meta),
        None,
        5,
    )
    assert packer6.rayon_threads == 5
    del packer6

    import decimal

    batch_view = pa.RecordBatch.from_arrays(
        [
            pa.array([0, 1, 2], type=pa.uint64()),
            pa.array([10, 20, 30], type=pa.uint16()),
            pa.array([40, 50, 60], type=pa.uint16()),
            pa.array([0, 0, 0], type=pa.uint8()),
            pa.array(["short", None, "a_longer_inlined_or_out_of_line_utf8view_string"], type=pa.string_view()),
            pa.array([b"\x01\x02", None, b"0123456789abcdef_binary_view"], type=pa.binary_view()),
            pa.array(
                [decimal.Decimal("1200"), None, decimal.Decimal("-3400")],
                type=pa.decimal128(10, -2),
            ),
            pa.array([0, 0, 0], type=pa.uint64()),
        ],
        schema=schema_view,
    )
    rdr_data = pa.RecordBatchReader.from_batches(schema_view, [batch_view])
    cs_data = pc_ffi.ffi.new("struct ArrowArrayStream*")
    ptr_data = int(pc_ffi.ffi.cast("uintptr_t", cs_data))
    rdr_data._export_to_c(ptr_data)
    packer2.process_batch(ptr_data)
    packer2.finalize()

    assert validate_file(out_view, expected_input_rows=3).ok
    with ArrowTilesReader(out_view) as r:
        assert r.schema().field("label_view").type == pa.string()
        assert r.schema().field("bin_view").type == pa.binary()
        assert r.schema().field("dec_neg").type == pa.float64()
        t0 = r.read_tile(0, 0, 0)
        assert t0 is not None
        assert t0["label_view"].to_pylist() == [
            "short",
            None,
            "a_longer_inlined_or_out_of_line_utf8view_string",
        ]
        assert t0["dec_neg"].to_pylist() == [1200.0, None, -3400.0]

    # 3. Calling process_batch AFTER finalize() must consume & release the FFI stream before raising RuntimeError
    rdr_after = pa.RecordBatchReader.from_batches(schema_view, [batch_view])
    cs_after = pc_ffi.ffi.new("struct ArrowArrayStream*")
    ptr_after = int(pc_ffi.ffi.cast("uintptr_t", cs_after))
    rdr_after._export_to_c(ptr_after)
    assert cs_after.release != pc_ffi.ffi.NULL
    with pytest.raises(RuntimeError, match="already finalized"):
        packer2.process_batch(ptr_after)
    assert cs_after.release == pc_ffi.ffi.NULL

    # 4. > 64 MiB compressed tile must be rejected by flush_chunk_buffer
    schema_big = pa.schema(
        [
            pa.field("row_id", pa.uint64(), nullable=False),
            pa.field("x_u16", pa.uint16(), nullable=False),
            pa.field("y_u16", pa.uint16(), nullable=False),
            pa.field("z", pa.uint8(), nullable=False),
            pa.field("payload", pa.binary(), nullable=False),
            pa.field("final_tile_id", pa.uint64(), nullable=False),
        ]
    )
    _cs_big, ptr_big_s = _export_schema(schema_big)
    packer_big = _core.ArrowTilesPacker(
        str(tmp_path / "too_big.arrowtiles"),
        ptr_big_s,
        10_000,
        0,
        10,
        json.dumps(spec_meta),
        None,
        2,
    )
    # 68 MiB of incompressible CSPRNG bytes across 2 rows in tile 0
    blob_34m_a = os.urandom(34 * 1024 * 1024)
    blob_34m_b = os.urandom(34 * 1024 * 1024)
    batch_big = pa.RecordBatch.from_arrays(
        [
            pa.array([0, 1], type=pa.uint64()),
            pa.array([0, 1], type=pa.uint16()),
            pa.array([0, 1], type=pa.uint16()),
            pa.array([0, 0], type=pa.uint8()),
            pa.array([blob_34m_a, blob_34m_b], type=pa.binary()),
            pa.array([0, 0], type=pa.uint64()),
        ],
        schema=schema_big,
    )
    rdr_big = pa.RecordBatchReader.from_batches(schema_big, [batch_big])
    cs_big_d = pc_ffi.ffi.new("struct ArrowArrayStream*")
    ptr_big_d = int(pc_ffi.ffi.cast("uintptr_t", cs_big_d))
    rdr_big._export_to_c(ptr_big_d)
    packer_big.process_batch(ptr_big_d)
    with pytest.raises(RuntimeError, match="exceeds 64 MiB"):
        packer_big.finalize()
    assert not (tmp_path / "too_big.arrowtiles").exists()
    assert not (tmp_path / "too_big.arrowtiles.tmp").exists()

    # 5. _load_core_module must raise ImportError (not return None) when arrowtiles._core is None
    import sys as _sys
    import arrowtiles as _at_pkg
    from arrowtiles.builder import _load_core_module

    orig_core_attr = getattr(_at_pkg, "_core", None)
    orig_sys_mod = _sys.modules.get("arrowtiles_core")
    try:
        _at_pkg._core = None  # type: ignore[attr-defined]
        _sys.modules["arrowtiles_core"] = None  # type: ignore[assignment]
        with pytest.raises(ImportError, match="Native engine 'arrowtiles._core' not found"):
            _load_core_module()
    finally:
        _at_pkg._core = orig_core_attr  # type: ignore[attr-defined]
        if orig_sys_mod is not None:
            _sys.modules["arrowtiles_core"] = orig_sys_mod
        else:
            _sys.modules.pop("arrowtiles_core", None)


def test_constant_large_double_precision_retention_above_2_pow_24(tmp_path: Path) -> None:
    """Verify min_f == max_f DOUBLE > 2^24 that loses Float32 precision stays Float64."""
    from arrowtiles.builder import _should_downcast_double

    # Inexact > 2^24 constant (e.g. single-row or constant Unix timestamp in seconds)
    ok_inexact, reason = _should_downcast_double(1_767_312_001.0, 1_767_312_001.0)
    assert ok_inexact is False
    assert "2^24" in reason

    # Exact power-of-two > 2^24 (2^25 = 33,554,432.0) is losslessly representable in Float32
    ok_exact, _ = _should_downcast_double(33_554_432.0, 33_554_432.0)
    assert ok_exact is True

    # Small constant (|val| <= 2^24) continues to downcast to Float32
    ok_small, _ = _should_downcast_double(0.12345678901234568, 0.12345678901234568)
    assert ok_small is True

    pq_path = tmp_path / "const_epoch.parquet"
    import pyarrow.parquet as pq

    pq.write_table(
        pa.table(
            {
                "x": [0.25, 0.75],
                "y": [0.25, 0.75],
                "const_epoch_f64": pa.array([1_767_312_001.0, 1_767_312_001.0], type=pa.float64()),
                "const_pow2_f64": pa.array([33_554_432.0, 33_554_432.0], type=pa.float64()),
            }
        ),
        pq_path,
    )

    out_path = tmp_path / "const_epoch.arrowtiles"
    build_generic(
        input_parquet=pq_path,
        output_path=out_path,
        x_col="x",
        y_col="y",
        keep_float64=False,
        temp_dir=tmp_path / "t_const",
        show_progress=False,
    )
    val = validate_file(out_path, expected_input_rows=2)
    assert val.ok, val.errors

    with ArrowTilesReader(out_path) as r:
        assert r.schema().field("const_epoch_f64").type == pa.float64()
        assert r.schema().field("const_pow2_f64").type == pa.float32()
        t0 = r.read_tile(0, 0, 0)
        assert t0 is not None
        assert t0["const_epoch_f64"].to_pylist() == [1_767_312_001.0, 1_767_312_001.0]
        assert t0["const_pow2_f64"].to_pylist() == [33_554_432.0, 33_554_432.0]
        assert r.metadata()["stats"]["const_epoch_f64"]["min"] == 1_767_312_001.0
        assert r.metadata()["stats"]["const_epoch_f64"]["max"] == 1_767_312_001.0
