"""Phase 1 comprehensive tests: SPEC.md v0.1 contract, edge cases, reader round-trip, and validator."""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.cffi as pc_ffi
import pytest

from arrowtiles import (
    ArrowTilesBuilder,
    ArrowTilesReader,
    _core,
    build_generic,
    validate_file,
)
from arrowtiles.__main__ import main as cli_main


def test_hilbert_shift_invariants_rust() -> None:
    """Verify 2-bit shift derivation from z=20 matches PMTiles TileCoord::new(z, x, y) across 20,000+ cases."""
    _core.verify_hilbert_shift_invariants()


@pytest.mark.parametrize("sampling_mode", ["even_coverage", "proportional"])
@pytest.mark.parametrize("max_zoom", list(range(0, 9)))
def test_all_max_zooms_0_to_8_both_sampling_modes(
    tmp_path: Path, sampling_mode: str, max_zoom: int
) -> None:
    """Regression test: build every max_zoom 0..=8 in both sampling modes with dense cluster spill."""
    src_pq = tmp_path / f"zoom_{sampling_mode}_{max_zoom}.parquet"
    out_at = tmp_path / f"zoom_{sampling_mode}_{max_zoom}.arrowtiles"

    # 2 corner anchors fix bounds to [0, 1]^2 while 78 points cluster inside a single z=8 cell
    # ([0.12500, 0.12508]^2), guaranteeing that even_coverage hits z == max_zoom (<= 6) and spills!
    n_rows = 80
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                CASE
                    WHEN i == 0 THEN 0.0
                    WHEN i == 1 THEN 1.0
                    ELSE 0.12500 + (i % 10) * 0.000008
                END AS x,
                CASE
                    WHEN i == 0 THEN 0.0
                    WHEN i == 1 THEN 1.0
                    ELSE 0.12500 + (i // 10) * 0.000008
                END AS y,
                CAST(i AS DOUBLE) AS score
            FROM range({n_rows}) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    res = build_generic(
        input_parquet=src_pq,
        output_path=out_at,
        x_col="x",
        y_col="y",
        sort_col="score",
        sampling=sampling_mode,
        max_capacity=16,
        max_tile_rows=20,
        max_zoom=max_zoom,
        temp_dir=tmp_path / f"tmp_{sampling_mode}_{max_zoom}",
        show_progress=False,
    )
    assert res["total_rows"] == n_rows
    assert res["observed_max_tile_rows"] <= 20

    val = validate_file(out_at, expected_input_rows=n_rows)
    assert val.ok, f"Failed at sampling={sampling_mode}, max_zoom={max_zoom}: {val.errors}"
    assert val.header_max_zoom == res["actual_max_zoom"]


def test_synthetic_edge_case_sample_and_roundtrip(tmp_path: Path) -> None:
    """Build synthetic edge-case archive (NaN/Inf/NULL coords, NaN aux, colliding x_norm, UInt8 + UInt16 categories)."""
    src_parquet = tmp_path / "edge_cases.parquet"
    out_archive = tmp_path / "edge_cases.arrowtiles"
    temp_dir = tmp_path / "temp_edge"

    total_input = 1_200
    # Rows 0..11: non-finite / NULL coordinates (12 dropped rows)
    # Remaining 1,188 valid rows:
    # - `x_norm`: pre-existing user column that MUST NOT collide with internal normalized coords
    # - `metric_with_nan`: contains NaN and NULL, sorted DESC (NaN and NULL MUST sort last, metadata MUST NOT drop)
    # - `cat_20`: 20 categories (>10) + NULLs -> UInt8
    # - `cat_300`: 300 categories (>256) + NULLs -> UInt16
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                CASE
                    WHEN i < 3 THEN NULL
                    WHEN i < 6 THEN 'NaN'::DOUBLE
                    WHEN i < 9 THEN 'Infinity'::DOUBLE
                    WHEN i = 9 THEN -100.0
                    ELSE -100.0 + ((i * 37) % 1000) * 0.5
                END AS raw_x,
                CASE
                    WHEN i = 9 THEN '-Infinity'::DOUBLE
                    WHEN i IN (10, 11) THEN NULL
                    ELSE 50.0 + ((i * 53) % 500) * 0.25
                END AS raw_y,
                CAST(i * 1.25 AS DOUBLE) AS x_norm,
                CASE
                    WHEN i % 17 == 0 THEN NULL
                    WHEN i % 19 == 0 THEN 'NaN'::DOUBLE
                    ELSE CAST((i * 13) % 500 AS DOUBLE)
                END AS metric_with_nan,
                CASE
                    WHEN i % 11 == 0 THEN NULL
                    ELSE 'cat20_' || lpad(CAST(i % 20 AS VARCHAR), 2, '0')
                END AS cat_20,
                CASE
                    WHEN i % 13 == 0 THEN NULL
                    ELSE 'cat300_' || lpad(CAST(i % 300 AS VARCHAR), 3, '0')
                END AS cat_300
            FROM range({total_input}) AS t(i)
        ) TO '{src_parquet.as_posix()}' (FORMAT PARQUET)
        """
    )
    source_valid_rows = con.execute(
        f"""
        SELECT file_row_number, raw_x, raw_y, x_norm, cat_20, cat_300, metric_with_nan
        FROM read_parquet('{src_parquet.as_posix()}', file_row_number=true)
        WHERE raw_x IS NOT NULL AND raw_y IS NOT NULL
          AND isfinite(raw_x) AND isfinite(raw_y)
        ORDER BY file_row_number ASC
        """
    ).fetchall()
    con.close()

    expected_dropped = 12
    expected_valid = total_input - expected_dropped
    assert len(source_valid_rows) == expected_valid

    summary = build_generic(
        input_parquet=src_parquet,
        output_path=out_archive,
        x_col="raw_x",
        y_col="raw_y",
        sort_col="metric_with_nan",
        sort_dir="DESC",
        max_capacity=256,
        max_zoom=6,
        memory_limit="2GB",
        temp_dir=temp_dir,
        show_progress=False,
    )
    assert summary["total_rows"] == expected_valid
    assert summary["dropped_rows"] == expected_dropped

    val = validate_file(out_archive, expected_input_rows=total_input)
    assert val.ok, f"Validation failed: {val.errors}"
    assert val.total_rows == expected_valid
    assert val.dropped_rows == expected_dropped
    assert val.warnings == []

    # Verify CLI validate exits 0
    assert cli_main(["validate", str(out_archive), "--expected-input-rows", str(total_input)]) == 0

    src_by_rowid = {int(r[0]): r for r in source_valid_rows}

    with ArrowTilesReader(out_archive) as reader:
        meta = reader.metadata()
        schema = reader.schema()

        # User's colliding `x_norm` column survived untouched
        assert "x_norm" in schema.names
        assert "raw_x" not in schema.names
        assert "raw_y" not in schema.names

        # Categorical types follow D4 (UInt8 for <=256, UInt16 for 257..65535, no DictionaryType)
        assert schema.field("cat_20").type == pa.uint8()
        assert schema.field("cat_300").type == pa.uint16()
        assert len(meta["stats"]["cat_20"]["categories"]) == 20
        assert len(meta["stats"]["cat_300"]["categories"]) == 300

        # Numeric stats excluded NaN cleanly without corrupting JSON metadata
        m_stats = meta["stats"]["metric_with_nan"]
        assert math.isfinite(m_stats["min"]) and math.isfinite(m_stats["max"])

        bounds = meta["bounds"]
        span_x = bounds["max_x"] - bounds["min_x"]
        span_y = bounds["max_y"] - bounds["min_y"]

        seen_row_ids: set[int] = set()
        for (z, tx, ty), tbl in reader.iter_tiles(decode_coords=True, decode_categories=True):
            tol_x = span_x / (2.0 * 65535.0 * (1 << z)) + 1e-9
            tol_y = span_y / (2.0 * 65535.0 * (1 << z)) + 1e-9

            rids = tbl["row_id"].to_pylist()
            xs = tbl["x_decoded"].to_pylist()
            ys = tbl["y_decoded"].to_pylist()
            x_norms_col = tbl["x_norm"].to_pylist()
            c20_vals = tbl["cat_20"].to_pylist()
            c300_vals = tbl["cat_300"].to_pylist()
            metrics = tbl["metric_with_nan"].to_pylist()

            # Verify DESC sort puts NULL and NaN strictly AFTER finite values within every tile
            saw_missing_metric = False
            prev_finite: float | None = None
            for m in metrics:
                is_missing = m is None or (isinstance(m, float) and math.isnan(m))
                if is_missing:
                    saw_missing_metric = True
                else:
                    assert not saw_missing_metric, "Finite value appeared after NULL/NaN in DESC sort!"
                    if prev_finite is not None:
                        assert float(m) <= prev_finite + 1e-9
                    prev_finite = float(m)

            for idx, rid in enumerate(rids):
                assert rid not in seen_row_ids
                seen_row_ids.add(rid)
                _, exp_x, exp_y, exp_xnorm, exp_c20, exp_c300, _ = src_by_rowid[rid]
                assert abs(xs[idx] - exp_x) <= tol_x
                assert abs(ys[idx] - exp_y) <= tol_y
                assert abs(x_norms_col[idx] - exp_xnorm) <= 1e-9
                assert c20_vals[idx] == exp_c20  # None preserved as None, never mapped to category 0!
                assert c300_vals[idx] == exp_c300

        assert len(seen_row_ids) == expected_valid


def test_leaf_spillover_updates_header_max_zoom_and_z20_overflow_guard(tmp_path: Path) -> None:
    """Verify dense clusters spill past nominal_max_zoom up to z=20 and update header.max_zoom."""
    spill_pq = tmp_path / "spill.parquet"
    spill_out = tmp_path / "spill.arrowtiles"

    # 100 distinct points tightly clustered inside [0.10, 0.11]^2 with nominal_max_zoom=1, max_tile_rows=16
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                0.10 + (i % 10) * 0.0005 AS x,
                0.10 + (i // 10) * 0.0005 AS y,
                CAST(i AS DOUBLE) AS val
            FROM range(100) AS t(i)
        ) TO '{spill_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    res = build_generic(
        input_parquet=spill_pq,
        output_path=spill_out,
        x_col="x",
        y_col="y",
        sort_col="val",
        sampling="proportional",
        max_capacity=8,
        max_tile_rows=16,
        max_zoom=1,
        temp_dir=tmp_path / "tmp_spill",
        show_progress=False,
    )
    assert res["actual_max_zoom"] > 1
    assert res["observed_max_tile_rows"] <= 16

    val = validate_file(spill_out, expected_input_rows=100)
    assert val.ok, f"Spillover validation failed: {val.errors}"
    assert val.header_max_zoom == res["actual_max_zoom"]
    assert val.observed_max_tile_rows <= 16

    # Exact-duplicate coordinates exceeding max_tile_rows at z=20 MUST fail unless allow_oversize_leaves=True
    # (z=0 claims 2 rows; z=1..20 each accept 5 rows = 102 rows total; 150 rows -> 53 rows land at z=20 > 5)
    dup_pq = tmp_path / "exact_dups.parquet"
    dup_out = tmp_path / "exact_dups.arrowtiles"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT 0.5 AS x, 0.5 AS y, CAST(i AS DOUBLE) AS val
            FROM range(150) AS t(i)
        ) TO '{dup_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    with pytest.raises(RuntimeError, match="exceeded max_tile_rows"):
        build_generic(
            input_parquet=dup_pq,
            output_path=dup_out,
            x_col="x",
            y_col="y",
            sampling="proportional",
            max_capacity=2,
            max_tile_rows=5,
            max_zoom=1,
            allow_oversize_leaves=False,
            temp_dir=tmp_path / "tmp_dup_fail",
            show_progress=False,
        )

    res_ok = build_generic(
        input_parquet=dup_pq,
        output_path=dup_out,
        x_col="x",
        y_col="y",
        sampling="proportional",
        max_capacity=2,
        max_tile_rows=5,
        max_zoom=1,
        allow_oversize_leaves=True,
        temp_dir=tmp_path / "tmp_dup_ok",
        show_progress=False,
    )
    assert res_ok["actual_max_zoom"] == 20
    val_dup = validate_file(dup_out, expected_input_rows=150)
    assert val_dup.ok, f"allow_oversize_leaves validation failed: {val_dup.errors}"
    assert val_dup.declared_max_tile_rows == val_dup.observed_max_tile_rows


def test_reserved_columns_and_custom_metadata_rejected(tmp_path: Path) -> None:
    """Verify reserved columns (`z`, `__at_*`) and invalid/reserved custom_metadata fail cleanly."""
    bad_pq = tmp_path / "bad_col.parquet"
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT 0.1 AS x, 0.2 AS y, 1 AS z FROM range(10)) TO '{bad_pq.as_posix()}' (FORMAT PARQUET)"
    )
    con.close()

    with pytest.raises(ValueError, match="reserved ArrowTiles column"):
        build_generic(
            input_parquet=bad_pq,
            output_path=tmp_path / "out.arrowtiles",
            x_col="x",
            y_col="y",
            temp_dir=tmp_path / "t1",
            show_progress=False,
        )

    good_pq = tmp_path / "good.parquet"
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT 0.1 + i*0.01 AS x, 0.2 + i*0.01 AS y, i AS val FROM range(10) t(i)) TO '{good_pq.as_posix()}' (FORMAT PARQUET)"
    )
    con.close()

    # Corrupt JSON in custom_config
    with pytest.raises(ValueError, match="Invalid custom_config"):
        build_generic(
            input_parquet=good_pq,
            output_path=tmp_path / "out2.arrowtiles",
            x_col="x",
            y_col="y",
            custom_config="{not valid json",
            temp_dir=tmp_path / "t2",
            show_progress=False,
        )

    # NaN in custom_config
    with pytest.raises(ValueError, match="NaN"):
        build_generic(
            input_parquet=good_pq,
            output_path=tmp_path / "out3.arrowtiles",
            x_col="x",
            y_col="y",
            custom_config='{"extra": NaN}',
            temp_dir=tmp_path / "t3",
            show_progress=False,
        )

    # Reserved key in custom_config
    with pytest.raises(ValueError, match="reserved ArrowTiles key"):
        build_generic(
            input_parquet=good_pq,
            output_path=tmp_path / "out4.arrowtiles",
            x_col="x",
            y_col="y",
            custom_config='{"bounds": {"min_x": 0}}',
            temp_dir=tmp_path / "t4",
            show_progress=False,
        )

    # Direct Rust ArrowTilesPacker check on unparseable custom_metadata & DictionaryType
    schema_ok = pa.schema(
        [
            pa.field("row_id", pa.uint64(), nullable=False),
            pa.field("x_u16", pa.uint16(), nullable=False),
            pa.field("y_u16", pa.uint16(), nullable=False),
            pa.field("z", pa.uint8(), nullable=False),
        ]
    )
    empty_reader = pa.RecordBatchReader.from_batches(schema_ok, [])
    c_stream = pc_ffi.ffi.new("struct ArrowArrayStream*")
    ptr = int(pc_ffi.ffi.cast("uintptr_t", c_stream))
    empty_reader._export_to_c(ptr)

    with pytest.raises(ValueError, match="Invalid custom_metadata JSON"):
        _core.ArrowTilesPacker(
            str(tmp_path / "rust_bad_meta.arrowtiles"),
            ptr,
            10_000,
            4,
            1000,
            '{"format":"arrowtiles","version":"0.1"}',
            "{corrupt_json",
        )


def test_multifile_dense_row_id_and_resume(tmp_path: Path) -> None:
    """Verify multi-file Parquet glob assigns dense 0..N-1 row_ids and --resume produces valid output."""
    pq_dir = tmp_path / "parts"
    pq_dir.mkdir()
    con = duckdb.connect()
    for idx, count in enumerate([17, 23, 19]):
        p = pq_dir / f"part_{idx:02d}.parquet"
        con.execute(
            f"""
            COPY (
                SELECT
                    CAST((i + {idx * 100}) % 50 AS DOUBLE) / 50.0 AS x,
                    CAST((i * 3 + {idx}) % 50 AS DOUBLE) / 50.0 AS y,
                    CAST({idx * 1000} + i AS BIGINT) AS marker
                FROM range({count}) t(i)
            ) TO '{p.as_posix()}' (FORMAT PARQUET)
            """
        )
    con.close()

    out1 = tmp_path / "multi1.arrowtiles"
    temp_dir = tmp_path / "resume_temp"
    build_generic(
        input_parquet=f"{pq_dir.as_posix()}/part_*.parquet",
        output_path=out1,
        x_col="x",
        y_col="y",
        temp_dir=temp_dir,
        show_progress=False,
    )

    val = validate_file(out1, expected_input_rows=17 + 23 + 19)
    assert val.ok, val.errors

    with ArrowTilesReader(out1) as reader:
        all_rids: list[int] = []
        rid_to_marker: dict[int, int] = {}
        for _zxy, tbl in reader.iter_tiles():
            for rid, mrk in zip(tbl["row_id"].to_pylist(), tbl["marker"].to_pylist(), strict=True):
                all_rids.append(rid)
                rid_to_marker[rid] = mrk
        assert sorted(all_rids) == list(range(17 + 23 + 19))
        # File 0 -> row_id 0..16 (marker 0..16), File 1 -> row_id 17..39 (marker 1000..1022), File 2 -> 40..58
        assert rid_to_marker[0] == 0
        assert rid_to_marker[17] == 1000
        assert rid_to_marker[40] == 2000

    # Require explicit id_col when calling ArrowTilesBuilder.build() directly
    with ArrowTilesBuilder(memory_limit="1GB", temp_dir=tmp_path / "direct_err", show_progress=False) as b:
        with pytest.raises(ValueError, match="id_col"):
            b.build(
                input_query="SELECT 0.5 AS x_norm, 0.5 AS y_norm, 1.0 AS abs_m",
                output_path=tmp_path / "fail.arrowtiles",
            )


def test_legacy_v00_compatibility_and_unknown_major_rejection(
    lmsys_arrowtiles_path: Path, tmp_path: Path
) -> None:
    """Verify legacy v0.0 archive passes validator with warning only, and unknown major version is rejected."""
    res = validate_file(lmsys_arrowtiles_path, max_tiles_to_scan=25)
    assert res.ok, f"Legacy v0.0 archive should pass with warning, got errors: {res.errors}"
    assert res.is_legacy is True
    assert any("Legacy v0.0" in w for w in res.warnings)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with ArrowTilesReader(lmsys_arrowtiles_path) as r:
            assert r.is_legacy is True
            t0 = r.read_tile(0, 0, 0)
            assert t0 is not None and t0.num_rows > 0
        assert any("v0.0 compatibility mode" in str(w.message) for w in caught)

    # Check check_spec_version rejects unknown major version (e.g. "1.0")
    from arrowtiles.reader import check_spec_version

    with pytest.raises(ValueError, match="major version"):
        check_spec_version({"format": "arrowtiles", "version": "1.0"}, "future.arrowtiles")
