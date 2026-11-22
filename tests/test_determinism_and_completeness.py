"""Phase 2 test suite: byte-identical determinism, completeness, priority contracts, --resume, and D7a."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import duckdb
import pyarrow as pa
import pytest

from arrowtiles import ArrowTilesReader, build_generic, validate_file


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("sampling_mode", ["even_coverage", "proportional"])
def test_byte_identical_sha256_unique_and_tied_priorities(
    tmp_path: Path, sampling_mode: str
) -> None:
    """Verify two independent builds produce byte-for-byte identical SHA-256 archives (unique & all-tied)."""
    unique_pq = tmp_path / f"unique_{sampling_mode}.parquet"
    tied_pq = tmp_path / f"tied_{sampling_mode}.parquet"

    n_rows = 8_000
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                ((i * 7919) % 1000) / 1000.0 AS x,
                ((i * 6971) % 1000) / 1000.0 AS y,
                CAST(i * 0.125 AS DOUBLE) AS priority_val,
                CASE (i % 5)
                    WHEN 0 THEN NULL
                    WHEN 1 THEN 'g1'
                    WHEN 2 THEN 'g2'
                    WHEN 3 THEN 'g3'
                    ELSE 'g4'
                END AS grp,
                CASE WHEN i % 7 = 0 THEN NULL ELSE CAST(i * 1.5 AS DOUBLE) END AS opt_num,
                CASE WHEN i % 3 = 0 THEN NULL WHEN i % 2 = 0 THEN TRUE ELSE FALSE END AS opt_flag,
                CASE WHEN i % 6 = 0 THEN NULL ELSE 'note_' || CAST(i % 25 AS VARCHAR) END AS opt_note
            FROM range({n_rows}) AS t(i)
        ) TO '{unique_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.execute(
        f"""
        COPY (
            SELECT
                ((i * 7919) % 1000) / 1000.0 AS x,
                ((i * 6971) % 1000) / 1000.0 AS y,
                42.0::DOUBLE AS priority_val,
                'same_cat' AS grp
            FROM range({n_rows}) AS t(i)
        ) TO '{tied_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    for label, src_pq, sort_col, extra_cols, max_cats in [
        ("unique", unique_pq, "priority_val", ["priority_val", "grp", "opt_num", "opt_flag", "opt_note"], 10),
        ("all_tied", tied_pq, "priority_val", None, 4096),
        ("random_seed", unique_pq, None, ["priority_val", "grp", "opt_num", "opt_flag", "opt_note"], 10),
    ]:
        out1 = tmp_path / f"{label}_{sampling_mode}_1.arrowtiles"
        out2 = tmp_path / f"{label}_{sampling_mode}_2.arrowtiles"

        build_generic(
            input_parquet=src_pq,
            output_path=out1,
            x_col="x",
            y_col="y",
            sort_col=sort_col,
            columns=extra_cols,
            max_categories=max_cats,
            seed=12345,
            sampling=sampling_mode,
            max_capacity=300,
            max_tile_rows=600,
            max_zoom=5,
            temp_dir=tmp_path / f"tmp_{label}_{sampling_mode}_1",
            show_progress=False,
        )
        build_generic(
            input_parquet=src_pq,
            output_path=out2,
            x_col="x",
            y_col="y",
            sort_col=sort_col,
            columns=extra_cols,
            max_categories=max_cats,
            seed=12345,
            sampling=sampling_mode,
            max_capacity=300,
            max_tile_rows=600,
            max_zoom=5,
            temp_dir=tmp_path / f"tmp_{label}_{sampling_mode}_2",
            show_progress=False,
        )

        val1 = validate_file(out1, expected_input_rows=n_rows)
        assert val1.ok, val1.errors
        assert _sha256(out1) == _sha256(out2), (
            f"Non-deterministic archive bytes for case={label}, sampling={sampling_mode}"
        )


@pytest.mark.parametrize("sampling_mode", ["even_coverage", "proportional"])
@pytest.mark.parametrize("nominal_max_zoom", [4, 8])
@pytest.mark.parametrize("sort_dir", ["ASC", "DESC"])
def test_priority_monotonicity_and_completeness_contract(
    tmp_path: Path, sampling_mode: str, nominal_max_zoom: int, sort_dir: str
) -> None:
    """Verify SPEC.md §5.2 per-cell (z<=6 & z<nom_z even_coverage) and per-tile priority invariants."""
    src_pq = tmp_path / f"prio_{sampling_mode}_{nominal_max_zoom}_{sort_dir}.parquet"
    out_at = tmp_path / f"prio_{sampling_mode}_{nominal_max_zoom}_{sort_dir}.arrowtiles"

    # Include non-finite rows (dropped), priority ties, NULLs, NaNs, and dense clusters that spill across levels
    n_total = 3_500
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                CASE
                    WHEN i < 5 THEN 'NaN'::DOUBLE
                    WHEN i == 5 THEN 0.0
                    WHEN i == 6 THEN 1.0
                    WHEN i < 800 THEN 0.25 + ((i * 17) % 20) * 0.0002
                    ELSE ((i * 313) % 1000) / 1000.0
                END AS x,
                CASE
                    WHEN i == 4 THEN NULL
                    WHEN i == 5 THEN 0.0
                    WHEN i == 6 THEN 1.0
                    WHEN i < 800 THEN 0.25 + ((i * 29) % 20) * 0.0002
                    ELSE ((i * 577) % 1000) / 1000.0
                END AS y,
                CASE
                    WHEN i % 41 == 0 THEN NULL
                    WHEN i % 43 == 0 THEN 'NaN'::DOUBLE
                    ELSE CAST((i * 7) % 120 AS DOUBLE)
                END AS prio
            FROM range({n_total}) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    src_rows = con.execute(
        f"""
        SELECT file_row_number, x, y, prio
        FROM read_parquet('{src_pq.as_posix()}', file_row_number=true)
        WHERE x IS NOT NULL AND y IS NOT NULL AND isfinite(x) AND isfinite(y)
        """
    ).fetchall()
    con.close()

    tile_cap = 256  # grid_size = isqrt(256) = 16
    leaf_cap = 300
    build_generic(
        input_parquet=src_pq,
        output_path=out_at,
        x_col="x",
        y_col="y",
        sort_col="prio",
        sort_dir=sort_dir,
        sampling=sampling_mode,
        max_capacity=tile_cap,
        max_tile_rows=leaf_cap,
        max_zoom=nominal_max_zoom,
        temp_dir=tmp_path / "tmp_prio",
        show_progress=False,
    )

    val = validate_file(out_at, expected_input_rows=n_total)
    assert val.ok, val.errors
    assert val.total_rows == len(src_rows)
    assert val.dropped_rows == n_total - len(src_rows)

    def _rank_key(prio_val: float | None, row_id: int) -> tuple[int, float, int]:
        if prio_val is None or math.isnan(prio_val):
            return (1, 0.0, row_id)
        signed = float(prio_val) if sort_dir == "ASC" else -float(prio_val)
        return (0, signed, row_id)

    # Map row_id -> exact normalized (x_norm, y_norm) and rank_key
    src_info: dict[int, tuple[float, float, tuple[int, float, int]]] = {}
    for rid_raw, rx, ry, rprio in src_rows:
        rid = int(rid_raw)
        # Bounds are fixed to [0, 1]^2 by anchors i=5 (0,0) and i=6 (1,1); top-down y_norm = 1.0 - y
        x_norm = max(0.0, min(1.0, float(rx)))
        y_norm = max(0.0, min(1.0, 1.0 - float(ry)))
        src_info[rid] = (x_norm, y_norm, _rank_key(rprio, rid))

    def _cell_at_z(x_norm: float, y_norm: float, z: int, grid_size: int) -> tuple[int, int, int, int]:
        n20 = float(1 << 20)
        max_idx_20 = (1 << 20) - 1
        ix_20 = int(min(x_norm * n20, float(max_idx_20)))
        iy_20 = int(min(y_norm * n20, float(max_idx_20)))
        shift = 20 - z
        tx = ix_20 >> shift
        ty = iy_20 >> shift
        n = float(1 << z)
        lx = max(0.0, min(1.0, x_norm * n - float(tx)))
        ly = max(0.0, min(1.0, y_norm * n - float(ty)))
        gx = min(int(lx * float(grid_size)), grid_size - 1)
        gy = min(int(ly * float(grid_size)), grid_size - 1)
        return tx, ty, gx, gy

    tiles_data: dict[tuple[int, int, int], list[int]] = {}
    with ArrowTilesReader(out_at) as reader:
        meta = reader.metadata()
        grid_size = int(meta["grid_size"])
        for (z, tx, ty), tbl in reader.iter_tiles():
            rids = [int(r) for r in tbl["row_id"].to_pylist()]
            # Verify strict intra-tile priority order
            ranks = [src_info[r][2] for r in rids]
            assert ranks == sorted(ranks), f"Intra-tile priority order violated in {z}/{tx}/{ty}"
            tiles_data[(z, tx, ty)] = rids

    # Check cross-level priority invariants
    for (z, tx, ty), rids in tiles_data.items():
        if z >= nominal_max_zoom:
            continue

        uses_even_grid = sampling_mode == "even_coverage" and z <= 6 and z < nominal_max_zoom
        if uses_even_grid:
            # Build cell -> rank map for this coarse tile
            cell_winner: dict[tuple[int, int], tuple[int, float, int]] = {}
            for rid in rids:
                xn, yn, rnk = src_info[rid]
                ctx, cty, gx, gy = _cell_at_z(xn, yn, z, grid_size)
                assert (ctx, cty) == (tx, ty)
                assert (gx, gy) not in cell_winner, (
                    f"Multiple rows assigned to cell ({gx},{gy}) at z={z}/{tx}/{ty}"
                )
                cell_winner[(gx, gy)] = rnk

            # Check every descendant tile T' (z' > z) under (z, tx, ty)
            for (zp, txp, typ), desc_rids in tiles_data.items():
                if zp <= z:
                    continue
                if (txp >> (zp - z)) == tx and (typ >> (zp - z)) == ty:
                    for drid in desc_rids:
                        xn, yn, drnk = src_info[drid]
                        ctx, cty, gx, gy = _cell_at_z(xn, yn, z, grid_size)
                        assert (ctx, cty) == (tx, ty)
                        assert (gx, gy) in cell_winner, (
                            f"Row {drid} spilled to z={zp} while parent cell ({gx},{gy}) at z={z} was empty!"
                        )
                        assert cell_winner[(gx, gy)] < drnk, (
                            f"Priority inversion in cell ({gx},{gy}): parent z={z} {cell_winner[(gx, gy)]} >= child z={zp} {drnk}"
                        )
        else:
            # Per-tile contract: if tile is full (len == tile_cap), every descendant has worse priority
            # and if tile is NOT full, NO descendant tiles may exist!
            worst_parent = max(src_info[r][2] for r in rids)
            is_full = len(rids) == tile_cap
            for (zp, txp, typ), desc_rids in tiles_data.items():
                if zp <= z:
                    continue
                if (txp >> (zp - z)) == tx and (typ >> (zp - z)) == ty:
                    assert is_full, (
                        f"Descendant tile {zp}/{txp}/{typ} exists under non-full parent {z}/{tx}/{ty} ({len(rids)} < {tile_cap})"
                    )
                    best_child = min(src_info[r][2] for r in desc_rids)
                    assert worst_parent < best_child, (
                        f"Per-tile priority inversion: parent {z}/{tx}/{ty} worst {worst_parent} >= child {zp}/{txp}/{typ} best {best_child}"
                    )


def test_resume_true_byte_identical_and_invalidates_stale_manifest(tmp_path: Path) -> None:
    """Verify resume=True skips Pass 1 with byte-identical output and invalidates stale partitions on setting/file change."""
    src_pq = tmp_path / "resume_src.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                ((i * 101) % 500) / 500.0 AS x,
                ((i * 211) % 500) / 500.0 AS y,
                CAST(i % 100 AS DOUBLE) AS score
            FROM range(2000) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    baseline_out = tmp_path / "baseline.arrowtiles"
    build_generic(
        input_parquet=src_pq,
        output_path=baseline_out,
        x_col="x",
        y_col="y",
        sort_col="score",
        sort_dir="ASC",
        max_capacity=256,
        max_zoom=5,
        temp_dir=tmp_path / "tmp_baseline",
        show_progress=False,
    )

    # 1. Run Pass 1 only, confirm manifest + partitions exist, then finish with resume=True
    resume_tmp = tmp_path / "tmp_resume"
    res_p1 = build_generic(
        input_parquet=src_pq,
        output_path=tmp_path / "unused.arrowtiles",
        x_col="x",
        y_col="y",
        sort_col="score",
        sort_dir="ASC",
        max_capacity=256,
        max_zoom=5,
        temp_dir=resume_tmp,
        show_progress=False,
        _pass1_only=True,
    )
    assert res_p1["pass1_only"] is True
    assert (resume_tmp / "partitions" / "manifest.json").is_file()

    resumed_out = tmp_path / "resumed.arrowtiles"
    res_p2 = build_generic(
        input_parquet=src_pq,
        output_path=resumed_out,
        x_col="x",
        y_col="y",
        sort_col="score",
        sort_dir="ASC",
        max_capacity=256,
        max_zoom=5,
        resume=True,
        temp_dir=resume_tmp,
        show_progress=False,
    )
    assert res_p2["resumed_pass1"] is True
    assert _sha256(resumed_out) == _sha256(baseline_out)

    # 2. Stale setting change (sort_dir DESC vs ASC) MUST NOT reuse ASC partitions!
    stale_tmp = tmp_path / "tmp_stale"
    build_generic(
        input_parquet=src_pq,
        output_path=tmp_path / "unused2.arrowtiles",
        x_col="x",
        y_col="y",
        sort_col="score",
        sort_dir="ASC",
        max_capacity=256,
        max_zoom=5,
        temp_dir=stale_tmp,
        show_progress=False,
        _pass1_only=True,
    )

    desc_fresh_out = tmp_path / "desc_fresh.arrowtiles"
    build_generic(
        input_parquet=src_pq,
        output_path=desc_fresh_out,
        x_col="x",
        y_col="y",
        sort_col="score",
        sort_dir="DESC",
        max_capacity=256,
        max_zoom=5,
        temp_dir=tmp_path / "tmp_desc_fresh",
        show_progress=False,
    )

    desc_from_stale_out = tmp_path / "desc_from_stale.arrowtiles"
    res_stale = build_generic(
        input_parquet=src_pq,
        output_path=desc_from_stale_out,
        x_col="x",
        y_col="y",
        sort_col="score",
        sort_dir="DESC",
        max_capacity=256,
        max_zoom=5,
        resume=True,
        temp_dir=stale_tmp,
        show_progress=False,
    )
    assert res_stale["resumed_pass1"] is False
    assert _sha256(desc_from_stale_out) == _sha256(desc_fresh_out)


def test_d7a_drops_free_text_by_default_and_honors_columns_opt_in(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify high-cardinality string columns (> max_categories) are dropped + recorded unless named in columns=."""
    src_pq = tmp_path / "d7a.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                (i % 50) / 50.0 AS x,
                (i // 50) / 10.0 AS y,
                CAST(i AS DOUBLE) AS score,
                'cat_' || CAST(i % 4 AS VARCHAR) AS cat_col,
                'unique_prompt_text_' || CAST(i AS VARCHAR) AS raw_prompt
            FROM range(300) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    default_out = tmp_path / "d7a_default.arrowtiles"
    res_def = build_generic(
        input_parquet=src_pq,
        output_path=default_out,
        x_col="x",
        y_col="y",
        sort_col="score",
        max_categories=20,
        temp_dir=tmp_path / "t_def",
        show_progress=False,
    )
    captured = capsys.readouterr()
    assert "Dropping high-cardinality string column 'raw_prompt'" in captured.out
    assert res_def["dropped_columns"] == ["raw_prompt"]

    val_def = validate_file(default_out, expected_input_rows=300)
    assert val_def.ok, val_def.errors

    with ArrowTilesReader(default_out) as r:
        assert "raw_prompt" not in r.schema().names
        assert "cat_col" in r.schema().names
        assert r.metadata()["dropped_columns"] == ["raw_prompt"]

    # Explicit opt-in via columns= retains raw_prompt
    optin_out = tmp_path / "d7a_optin.arrowtiles"
    res_opt = build_generic(
        input_parquet=src_pq,
        output_path=optin_out,
        x_col="x",
        y_col="y",
        sort_col="score",
        columns=["score", "cat_col", "raw_prompt"],
        max_categories=20,
        temp_dir=tmp_path / "t_opt",
        show_progress=False,
    )
    assert res_opt["dropped_columns"] == []
    val_opt = validate_file(optin_out, expected_input_rows=300)
    assert val_opt.ok, val_opt.errors
    with ArrowTilesReader(optin_out) as r:
        assert "raw_prompt" in r.schema().names
        assert r.metadata()["dropped_columns"] == []


def test_validator_rejects_out_of_range_category_codes(tmp_path: Path) -> None:
    """Verify validator fails if a categorical column contains an integer code >= len(categories)."""
    import pyarrow.cffi as pc_ffi

    from arrowtiles import _core

    schema = pa.schema(
        [
            pa.field("row_id", pa.uint64(), nullable=False),
            pa.field("cat", pa.uint8(), nullable=True),
            pa.field("x_u16", pa.uint16(), nullable=False),
            pa.field("y_u16", pa.uint16(), nullable=False),
            pa.field("z", pa.uint8(), nullable=False),
            pa.field("final_tile_id", pa.uint64(), nullable=False),
        ]
    )
    empty_reader = pa.RecordBatchReader.from_batches(schema, [])
    c_schema = pc_ffi.ffi.new("struct ArrowArrayStream*")
    ptr_schema = int(pc_ffi.ffi.cast("uintptr_t", c_schema))
    empty_reader._export_to_c(ptr_schema)

    spec_meta = {
        "format": "arrowtiles",
        "version": "0.1",
        "bounds": {"min_x": 0.0, "max_x": 1.0, "min_y": 0.0, "max_y": 1.0},
        "priority": {"kind": "random", "seed": 42},
        "sampling": "proportional",
        "grid_size": 16,
        "nominal_max_zoom": 1,
        "tile_capacity": 10,
        "max_tile_rows": 10,
        "total_rows": 2,
        "dropped_rows": 0,
        "dropped_columns": [],
        "stats": {
            "cat": {"type": "categorical", "categories": ["a", "b", "c"], "null_count": 0}
        },
    }
    bad_path = tmp_path / "bad_cat_code.arrowtiles"
    packer = _core.ArrowTilesPacker(
        str(bad_path),
        ptr_schema,
        10_000,
        0,
        10,
        json.dumps(spec_meta),
        None,
    )

    # Code 5 is >= len(["a", "b", "c"]) == 3!
    batch = pa.RecordBatch.from_arrays(
        [
            pa.array([0, 1], type=pa.uint64()),
            pa.array([0, 5], type=pa.uint8()),
            pa.array([100, 200], type=pa.uint16()),
            pa.array([100, 200], type=pa.uint16()),
            pa.array([0, 0], type=pa.uint8()),
            pa.array([0, 0], type=pa.uint64()),
        ],
        schema=schema,
    )
    data_reader = pa.RecordBatchReader.from_batches(schema, [batch])
    c_data = pc_ffi.ffi.new("struct ArrowArrayStream*")
    ptr_data = int(pc_ffi.ffi.cast("uintptr_t", c_data))
    data_reader._export_to_c(ptr_data)
    packer.process_batch(ptr_data)
    packer.finalize()

    val = validate_file(bad_path)
    assert not val.ok
    assert any("out-of-range code" in err for err in val.errors), val.errors
