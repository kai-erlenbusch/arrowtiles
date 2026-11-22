"""Tests for pre-v0.1.0 writer polish: `__index_level_<N>__` auto-drop & guarded Float64 -> Float32 downcast."""

from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path

import duckdb
import pyarrow as pa
import pytest

from arrowtiles import ArrowTilesBuilder, ArrowTilesReader, build_generic, validate_file
from arrowtiles.__main__ import main as cli_main


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _f32(val: float) -> float:
    out = struct.unpack("<f", struct.pack("<f", val))[0]
    return 0.0 if out == 0.0 else out


def test_pandas_index_level_auto_drop_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Default generic build drops __index_level_0/1__, records them in dropped_columns, and keeps 'index'."""
    src_pq = tmp_path / "multi_index.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                (i % 25) / 25.0 AS x,
                (i // 25) / 10.0 AS y,
                CAST(i * 0.5 AS DOUBLE) AS score,
                CAST(i * 10 AS BIGINT) AS "index",
                CAST(i AS BIGINT) AS __index_level_0__,
                'lvl_' || CAST(i % 3 AS VARCHAR) AS __index_level_1__
            FROM range(250) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    out_at = tmp_path / "multi_index.arrowtiles"
    res = build_generic(
        input_parquet=src_pq,
        output_path=out_at,
        x_col="x",
        y_col="y",
        temp_dir=tmp_path / "tmp_drop",
        show_progress=False,
    )
    captured = capsys.readouterr().out
    assert "Dropping pandas index column '__index_level_0__'" in captured
    assert "Dropping pandas index column '__index_level_1__'" in captured
    assert res["dropped_columns"] == ["__index_level_0__", "__index_level_1__"]

    val = validate_file(out_at, expected_input_rows=250)
    assert val.ok, val.errors

    with ArrowTilesReader(out_at) as reader:
        names = set(reader.schema().names)
        assert "__index_level_0__" not in names
        assert "__index_level_1__" not in names
        assert "index" in names
        assert "score" in names
        assert reader.metadata()["dropped_columns"] == ["__index_level_0__", "__index_level_1__"]
        assert "__index_level_0__" not in reader.metadata()["stats"]

    # Deterministic mmap teardown allows immediate unlink on Windows while `reader` is still in scope
    out_at.unlink()


def test_pandas_index_level_explicit_retention_overrides(tmp_path: Path) -> None:
    """Explicit columns=, sort_col=, or id_col= retains the requested __index_level_<N>__ column."""
    src_pq = tmp_path / "explicit_idx.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                (i % 20) / 20.0 AS x,
                (i // 20) / 10.0 AS y,
                CAST(i AS DOUBLE) AS score,
                CAST(i AS UBIGINT) AS __index_level_0__,
                CAST(1000 - i AS BIGINT) AS __index_level_1__
            FROM range(100) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    # 1. Explicit columns=[...]
    out_cols = tmp_path / "keep_cols.arrowtiles"
    res_cols = build_generic(
        input_parquet=src_pq,
        output_path=out_cols,
        x_col="x",
        y_col="y",
        columns=["__index_level_0__", "score"],
        temp_dir=tmp_path / "t_cols",
        show_progress=False,
    )
    assert res_cols["dropped_columns"] == []
    assert validate_file(out_cols, expected_input_rows=100).ok
    with ArrowTilesReader(out_cols) as r:
        assert "__index_level_0__" in r.schema().names

    # 2. Explicit sort_col="__index_level_0__"
    out_sort = tmp_path / "keep_sort.arrowtiles"
    res_sort = build_generic(
        input_parquet=src_pq,
        output_path=out_sort,
        x_col="x",
        y_col="y",
        sort_col="__index_level_0__",
        temp_dir=tmp_path / "t_sort",
        show_progress=False,
    )
    assert res_sort["dropped_columns"] == ["__index_level_1__"]
    assert validate_file(out_sort, expected_input_rows=100).ok
    with ArrowTilesReader(out_sort) as r:
        assert "__index_level_0__" in r.schema().names
        assert "__index_level_1__" not in r.schema().names

    # 3. Explicit id_col="__index_level_0__"
    out_id = tmp_path / "keep_id.arrowtiles"
    res_id = build_generic(
        input_parquet=src_pq,
        output_path=out_id,
        x_col="x",
        y_col="y",
        id_col="__index_level_0__",
        temp_dir=tmp_path / "t_id",
        show_progress=False,
    )
    assert res_id["dropped_columns"] == ["__index_level_1__"]
    assert validate_file(out_id, expected_input_rows=100).ok


def test_float64_to_float32_downcast_savings_nan_inf_negative_zero_and_determinism(
    tmp_path: Path,
) -> None:
    """DOUBLE payload columns downcast to Float32 cleanly (+Inf/-Inf/NaN/NULL/-0.0 safe, smaller, deterministic)."""
    src_pq = tmp_path / "floats.parquet"
    n_rows = 4_000
    min_mod_a = 0.12345678901234568
    max_mod_a = 0.9876543210987654
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                ((i * 7919) % 1000) / 1000.0 AS x,
                ((i * 6971) % 1000) / 1000.0 AS y,
                CASE
                    WHEN i == 0 THEN {min_mod_a!r}::DOUBLE
                    WHEN i == 1 THEN {max_mod_a!r}::DOUBLE
                    WHEN i == 2 THEN NULL
                    WHEN i == 3 THEN 'NaN'::DOUBLE
                    WHEN i == 4 THEN 'Infinity'::DOUBLE
                    WHEN i == 5 THEN '-Infinity'::DOUBLE
                    ELSE {min_mod_a!r}::DOUBLE + ((i * 31) % 800) * 0.001000123456789
                END AS mod_a,
                CASE
                    WHEN i == 0 THEN -1e-46::DOUBLE
                    ELSE ((i * 17) % 997) / 997.0
                END AS mod_subnormal_neg,
                sin(CAST(i AS DOUBLE) * 0.137) AS mod_b,
                cos(CAST(i AS DOUBLE) * 0.271) AS mod_c,
                CAST(i * 3 + 7 AS BIGINT) AS tok_count
            FROM range({n_rows}) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    out_f32_1 = tmp_path / "f32_1.arrowtiles"
    out_f32_2 = tmp_path / "f32_2.arrowtiles"
    out_f64 = tmp_path / "f64.arrowtiles"

    build_generic(
        input_parquet=src_pq,
        output_path=out_f32_1,
        x_col="x",
        y_col="y",
        max_capacity=500,
        max_zoom=5,
        temp_dir=tmp_path / "t_f32_1",
        show_progress=False,
    )
    build_generic(
        input_parquet=src_pq,
        output_path=out_f32_2,
        x_col="x",
        y_col="y",
        max_capacity=500,
        max_zoom=5,
        temp_dir=tmp_path / "t_f32_2",
        show_progress=False,
    )
    build_generic(
        input_parquet=src_pq,
        output_path=out_f64,
        x_col="x",
        y_col="y",
        keep_float64=True,
        max_capacity=500,
        max_zoom=5,
        temp_dir=tmp_path / "t_f64",
        show_progress=False,
    )

    assert validate_file(out_f32_1, expected_input_rows=n_rows).ok
    assert validate_file(out_f64, expected_input_rows=n_rows).ok
    assert _sha256(out_f32_1) == _sha256(out_f32_2)
    assert out_f32_1.stat().st_size < out_f64.stat().st_size

    with ArrowTilesReader(out_f32_1) as r32:
        sch = r32.schema()
        assert sch.field("mod_a").type == pa.float32()
        assert sch.field("mod_subnormal_neg").type == pa.float32()
        assert sch.field("mod_b").type == pa.float32()
        assert sch.field("mod_c").type == pa.float32()
        assert sch.field("tok_count").type == pa.int64()

        st_a = r32.metadata()["stats"]["mod_a"]
        assert st_a["min"] == _f32(min_mod_a)
        assert st_a["max"] == _f32(max_mod_a)
        assert st_a["null_count"] == 1
        sub_min = r32.metadata()["stats"]["mod_subnormal_neg"]["min"]
        assert sub_min == 0.0 and math.copysign(1.0, sub_min) == 1.0

        saw_nan = saw_pos_inf = saw_neg_inf = saw_null = False
        for _zxy, tbl in r32.iter_tiles(decode_coords=False):
            for v in tbl["mod_a"].to_pylist():
                if v is None:
                    saw_null = True
                elif math.isnan(v):
                    saw_nan = True
                elif math.isinf(v) and v > 0:
                    saw_pos_inf = True
                elif math.isinf(v) and v < 0:
                    saw_neg_inf = True
        assert saw_null and saw_nan and saw_pos_inf and saw_neg_inf


def test_keep_float64_cli_and_resume_invalidation(tmp_path: Path) -> None:
    """--keep-float64 CLI retains Float64, and toggling keep_float64 invalidates --resume Pass 1 partitions."""
    src_pq = tmp_path / "cli_f64.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                (i % 20) / 20.0 AS x,
                (i // 20) / 10.0 AS y,
                CAST(i * 0.1 AS DOUBLE) AS metric
            FROM range(200) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    cli_out = tmp_path / "cli_keep_f64.arrowtiles"
    rc = cli_main(
        [
            "build",
            "--input",
            str(src_pq),
            "--output",
            str(cli_out),
            "--x-col",
            "x",
            "--y-col",
            "y",
            "--keep-float64",
            "--temp-dir",
            str(tmp_path / "tmp_cli"),
        ]
    )
    assert rc == 0
    with ArrowTilesReader(cli_out) as r_cli:
        assert r_cli.schema().field("metric").type == pa.float64()

    # Populate Pass 1 partitions with default keep_float64=False (Float32)
    shared_tmp = tmp_path / "shared_resume_tmp"
    p1 = build_generic(
        input_parquet=src_pq,
        output_path=tmp_path / "unused.arrowtiles",
        x_col="x",
        y_col="y",
        keep_float64=False,
        temp_dir=shared_tmp,
        show_progress=False,
        _pass1_only=True,
    )
    assert p1["pass1_only"] is True

    # Resuming with keep_float64=True MUST invalidate stale Float32 partitions and match fresh Float64 build
    fresh_f64 = tmp_path / "fresh_f64.arrowtiles"
    build_generic(
        input_parquet=src_pq,
        output_path=fresh_f64,
        x_col="x",
        y_col="y",
        keep_float64=True,
        temp_dir=tmp_path / "tmp_fresh_f64",
        show_progress=False,
    )

    toggled_f64 = tmp_path / "toggled_f64.arrowtiles"
    res_toggled = build_generic(
        input_parquet=src_pq,
        output_path=toggled_f64,
        x_col="x",
        y_col="y",
        keep_float64=True,
        resume=True,
        temp_dir=shared_tmp,
        show_progress=False,
    )
    assert res_toggled["resumed_pass1"] is False
    assert _sha256(toggled_f64) == _sha256(fresh_f64)
    with ArrowTilesReader(toggled_f64) as r_tog:
        assert r_tog.schema().field("metric").type == pa.float64()


def test_out_of_range_float64_and_keep_source_xy_and_direct_build_guards(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Out-of-range DOUBLE (1e100) and keep_source_xy=True stay Float64 cleanly alongside Float32 siblings."""
    src_pq = tmp_path / "extreme.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                (i % 10) / 10.0 AS x,
                (i // 10) / 10.0 AS y,
                CASE WHEN i == 0 THEN 1e100::DOUBLE ELSE CAST(i AS DOUBLE) END AS huge_val,
                CAST(i * 0.25 AS DOUBLE) AS small_val
            FROM range(100) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    out_at = tmp_path / "extreme.arrowtiles"
    build_generic(
        input_parquet=src_pq,
        output_path=out_at,
        x_col="x",
        y_col="y",
        keep_source_xy=True,
        temp_dir=tmp_path / "t_ext",
        show_progress=False,
    )
    captured = capsys.readouterr().out
    assert "Retaining Float64 for column 'huge_val'" in captured
    assert validate_file(out_at, expected_input_rows=100).ok

    with ArrowTilesReader(out_at) as r:
        sch = r.schema()
        assert sch.field("huge_val").type == pa.float64()
        assert sch.field("small_val").type == pa.float32()
        assert sch.field("x").type == pa.float64()
        assert sch.field("y").type == pa.float64()

    # Direct ArrowTilesBuilder.build() caller passing downcast_float32_cols without pre-computed stats
    direct_out = tmp_path / "direct_guard.arrowtiles"
    with ArrowTilesBuilder(
        memory_limit="1GB", temp_dir=tmp_path / "t_direct", show_progress=False
    ) as builder:
        builder.build(
            input_query="""
                SELECT
                    CAST(i AS UBIGINT) AS row_id,
                    (i % 10) / 10.0 AS x_norm,
                    (i // 10) / 10.0 AS y_norm,
                    CASE WHEN i == 0 THEN 1e100::DOUBLE ELSE 1.0::DOUBLE END AS huge_val,
                    0.12345678901234568::DOUBLE AS small_val
                FROM range(50) AS t(i)
            """,
            output_path=direct_out,
            id_col="row_id",
            downcast_float32_cols={"huge_val", "small_val"},
        )
    assert validate_file(direct_out, expected_input_rows=50).ok
    with ArrowTilesReader(direct_out) as rd:
        assert rd.schema().field("huge_val").type == pa.float64()
        assert rd.schema().field("small_val").type == pa.float32()
        assert rd.metadata()["stats"]["small_val"]["min"] == _f32(0.12345678901234568)


def test_float64_sort_col_priority_ordering_preserved_before_float32_cast(tmp_path: Path) -> None:
    """Sub-Float32 priority differences (1.00000000 vs 1.00000001) sort in Float64 before Float32 tile cast."""
    src_pq = tmp_path / "sub_ulp_prio.parquet"
    con = duckdb.connect()
    # row 0 has slightly WORSE ASC priority (1.00000001) than row 1 (1.00000000); both round to 1.0f32!
    con.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                (0.5::DOUBLE, 0.5::DOUBLE, 1.00000001::DOUBLE),
                (0.5::DOUBLE, 0.5::DOUBLE, 1.00000000::DOUBLE),
                (0.0::DOUBLE, 0.0::DOUBLE, 10.0::DOUBLE),
                (1.0::DOUBLE, 1.0::DOUBLE, 20.0::DOUBLE)
            ) AS v(x, y, prio)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    out_at = tmp_path / "sub_ulp_prio.arrowtiles"
    build_generic(
        input_parquet=src_pq,
        output_path=out_at,
        x_col="x",
        y_col="y",
        sort_col="prio",
        sort_dir="ASC",
        sampling="proportional",
        max_capacity=1,
        max_tile_rows=4,
        max_zoom=3,
        temp_dir=tmp_path / "t_prio",
        show_progress=False,
    )
    assert validate_file(out_at, expected_input_rows=4).ok

    with ArrowTilesReader(out_at) as r:
        assert r.schema().field("prio").type == pa.float32()
        root = r.read_tile(0, 0, 0, decode_coords=False)
        assert root is not None
        assert root.num_rows == 1
        assert root["row_id"].to_pylist() == [1]
        assert root["prio"].to_pylist() == [1.0]
