"""Phase 3 test suite: SplitMix64 cross-language equivalence, default random priority, and Gaia preset."""

from __future__ import annotations

import hashlib
import random
import subprocess
import sys
from pathlib import Path

import duckdb
import pyarrow as pa
import pytest

from arrowtiles import (
    ArrowTilesBuilder,
    ArrowTilesReader,
    _core,
    build_gaia,
    build_generic,
    splitmix64_py,
    validate_file,
)
from arrowtiles.builder import MASK_U64, _duckdb_splitmix64_sql


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_splitmix64_rust_python_duckdb_bit_exact_equivalence() -> None:
    """Verify Rust, Python, and DuckDB UHUGEINT SplitMix64 match bit-for-bit with zero overflow."""
    assert hasattr(_core, "splitmix64_hash")

    # Independent 64-bit literal reference vectors (NOT computed via splitmix64_py) pinned to SPEC.md §6.1
    golden_vectors = [
        (0, 0, 0xE220A8397B1DCDAF),                      # 16294208416658607535
        (0, 42, 0xBDD732262FEB6E95),                     # 13679457532755275413
        (1, 42, 0xBA69EC90EB4FEF88),                     # 13432527470776545160
        (0xFFFFFFFFFFFFFFFF, -1, 0xF3203E9039F4A821),    # 17519071339639777313
        (123456789, -987654321, 0xF1C1278DBFA2126B),     # 17420248323404730987
    ]
    for r_id, seed, expected in golden_vectors:
        assert splitmix64_py(r_id, seed) == expected
        assert _core.splitmix64_hash(r_id, seed) == expected

    edge_row_ids = [0, 1, 42, (1 << 32) - 1, 1 << 53, (1 << 63) - 1, 1 << 63, MASK_U64]
    edge_seeds = [0, 1, 42, -1, -(1 << 63), (1 << 63) - 1, MASK_U64, 1234567890123456789]

    con = duckdb.connect()
    try:
        for seed in edge_seeds:
            for r_id in edge_row_ids:
                py_val = splitmix64_py(r_id, seed)
                rs_val = _core.splitmix64_hash(r_id, seed)
                sql_expr = _duckdb_splitmix64_sql(f"CAST({r_id} AS UBIGINT)", seed)
                duck_val = con.execute(f"SELECT {sql_expr}").fetchone()[0]
                assert py_val == rs_val == duck_val, (
                    f"SplitMix64 mismatch for row_id={r_id}, seed={seed}: "
                    f"py={py_val}, rust={rs_val}, duckdb={duck_val}"
                )

        # Bulk test on 1,000 random 64-bit unsigned row_ids across negative & large seeds
        rng = random.Random(20261120)
        rand_ids = [rng.getrandbits(64) for _ in range(1_000)]
        tbl = pa.table({"row_id": pa.array(rand_ids, type=pa.uint64())})
        con.register("rand_ids_tbl", tbl)

        for seed in (42, -999999999999, -(1 << 63), (1 << 63) - 1):
            sql_col = _duckdb_splitmix64_sql("row_id", seed)
            duck_out = [
                r[0]
                for r in con.execute(
                    f"SELECT {sql_col} FROM rand_ids_tbl"
                ).fetchall()
            ]
            for r_id, d_val in zip(rand_ids, duck_out):
                p_val = splitmix64_py(r_id, seed)
                r_val = _core.splitmix64_hash(r_id, seed)
                assert d_val == p_val == r_val
    finally:
        con.close()


def test_default_seeded_random_priority_and_splitmix64_ranking(tmp_path: Path) -> None:
    """Verify omitting sort_col defaults to SplitMix64 random priority (never abs_m) and selects exact top-k."""
    # 1. Direct ArrowTilesBuilder.build() without sort_col (no abs_m column present!)
    direct_out = tmp_path / "direct_random.arrowtiles"
    with ArrowTilesBuilder(
        memory_limit="1GB", temp_dir=str(tmp_path / "direct_tmp"), show_progress=False
    ) as builder:
        builder.build(
            input_query="""
                SELECT
                    CAST(i AS UBIGINT) AS row_id,
                    (i % 20) / 20.0 AS x_norm,
                    (i // 20) / 20.0 AS y_norm,
                    CAST(i * 1.5 AS DOUBLE) AS metric
                FROM range(200) AS t(i)
            """,
            output_path=direct_out,
            id_col="row_id",
            max_capacity=25,
            max_zoom=3,
            sampling="proportional",
            seed=42,
        )

    val_direct = validate_file(direct_out, expected_input_rows=200)
    assert val_direct.ok, val_direct.errors

    with ArrowTilesReader(direct_out) as reader:
        meta = reader.metadata()
        assert meta["priority"] == {"kind": "random", "seed": 42}
        root_tbl = reader.read_tile(0, 0, 0)
        assert root_tbl is not None
        assert root_tbl.num_rows == 25
        observed_root_ids = set(root_tbl["row_id"].to_pylist())

    # Exact top-25 row_ids ranked by (splitmix64_py(row_id, 42), row_id)
    expected_top25 = {
        r_id
        for r_id in sorted(range(200), key=lambda rid: (splitmix64_py(rid, 42), rid))[:25]
    }
    assert observed_root_ids == expected_top25

    # 2. build_generic() without sort_col: byte-identical with same seed, distinct root selection with different seed
    src_pq = tmp_path / "pts.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                (i % 25) / 25.0 AS x,
                (i // 25) / 25.0 AS y,
                CAST(i AS DOUBLE) AS val,
                CAST(i % 5 AS INTEGER) AS cluster_id
            FROM range(500) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    # Verify D7 defaults when sampling and max_capacity are omitted, plus explicit categorical_cols on INTEGER
    out_defaults = tmp_path / "gen_defaults.arrowtiles"
    build_generic(
        input_parquet=src_pq,
        output_path=out_defaults,
        x_col="x",
        y_col="y",
        categorical_cols=["cluster_id"],
        temp_dir=tmp_path / "tmp_defaults",
        show_progress=False,
    )
    val_def = validate_file(out_defaults, expected_input_rows=500)
    assert val_def.ok, val_def.errors
    with ArrowTilesReader(out_defaults) as rdef:
        mdef = rdef.metadata()
        assert mdef["sampling"] == "proportional"
        assert mdef["tile_capacity"] == 25_000
        assert mdef["stats"]["cluster_id"] == {
            "type": "categorical",
            "categories": ["0", "1", "2", "3", "4"],
            "null_count": 0,
        }
        assert rdef.schema().field("cluster_id").type == pa.uint8()

    out_a = tmp_path / "gen_seed42_a.arrowtiles"
    out_b = tmp_path / "gen_seed42_b.arrowtiles"
    out_c = tmp_path / "gen_seed99.arrowtiles"

    for idx, (target, s) in enumerate([(out_a, 42), (out_b, 42), (out_c, 99)]):
        build_generic(
            input_parquet=src_pq,
            output_path=target,
            x_col="x",
            y_col="y",
            max_capacity=40,
            max_zoom=4,
            seed=s,
            temp_dir=tmp_path / f"tmp_gen_{idx}",
            show_progress=False,
        )

    assert _sha256(out_a) == _sha256(out_b)
    with ArrowTilesReader(out_a) as ra, ArrowTilesReader(out_c) as rc:
        assert ra.metadata()["priority"] == {"kind": "random", "seed": 42}
        assert ra.metadata()["sampling"] == "proportional"
        assert rc.metadata()["priority"] == {"kind": "random", "seed": 99}
        ids_42 = set(ra.read_tile(0, 0, 0)["row_id"].to_pylist())
        ids_99 = set(rc.read_tile(0, 0, 0)["row_id"].to_pylist())
        assert ids_42 != ids_99


def test_gaia_preset_both_esa_dr3_and_legacy_schemas_plus_cli_forwarding(
    tmp_path: Path,
) -> None:
    """Verify --preset gaia accepts both (phot_g_mean_mag, bp_rp) and (magnitude, bv) and forwards CLI flags."""
    esa_pq = tmp_path / "gaia_esa_dr3.parquet"
    s3_pq = tmp_path / "gaia_s3_cache.parquet"

    con = duckdb.connect()
    # Schema A: raw ESA Gaia DR3 names (phot_g_mean_mag, bp_rp) without optional kinematics columns
    con.execute(
        f"""
        COPY (
            SELECT
                CAST((i * 37) % 360 AS DOUBLE) AS ra,
                CAST(((i * 13) % 170) - 85 AS DOUBLE) AS dec,
                CAST(4.0 + (i % 150) * 0.1 AS FLOAT) AS phot_g_mean_mag,
                CAST(-0.3 + (i % 40) * 0.1 AS FLOAT) AS bp_rp
            FROM range(300) AS t(i)
        ) TO '{esa_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    # Schema B: s3_cache names (magnitude, bv) + full kinematics
    con.execute(
        f"""
        COPY (
            SELECT
                CAST((i * 37) % 360 AS DOUBLE) AS ra,
                CAST(((i * 13) % 170) - 85 AS DOUBLE) AS dec,
                CAST(4.0 + (i % 150) * 0.1 AS FLOAT) AS magnitude,
                CAST(-0.3 + (i % 40) * 0.1 AS FLOAT) AS bv,
                CAST(1.0 + (i % 20) AS FLOAT) AS parallax,
                CAST((i % 10) - 5.0 AS FLOAT) AS pmra,
                CAST((i % 10) - 5.0 AS FLOAT) AS pmdec,
                CAST((i % 30) - 15.0 AS FLOAT) AS radial_velocity,
                CAST(4000.0 + (i % 50) * 100.0 AS FLOAT) AS teff_gspphot
            FROM range(300) AS t(i)
        ) TO '{s3_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    out_esa = tmp_path / "gaia_esa.arrowtiles"
    build_gaia(
        input_parquet=esa_pq,
        output_path=out_esa,
        max_capacity=64,
        max_zoom=4,
        temp_dir=tmp_path / "tmp_esa",
        show_progress=False,
    )
    val_esa = validate_file(out_esa, expected_input_rows=300)
    assert val_esa.ok, val_esa.errors

    with ArrowTilesReader(out_esa) as reader:
        meta_esa = reader.metadata()
        schema_names = set(reader.schema().names)
        assert "phot_g_mean_mag" in schema_names
        assert "abs_m" not in schema_names
        assert meta_esa["priority"] == {
            "kind": "column",
            "column": "phot_g_mean_mag",
            "order": "asc",
        }
        assert meta_esa["sampling"] == "even_coverage"
        assert meta_esa["view"]["sizeField"] == "phot_g_mean_mag"
        assert meta_esa["stats"]["parallax"]["null_count"] == 300

    # CLI forwarding check on Schema B with --preset gaia --sampling proportional --grid-size 32
    out_cli = tmp_path / "gaia_cli_prop.arrowtiles"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "arrowtiles",
            "build",
            "--preset",
            "gaia",
            "--input",
            str(s3_pq),
            "--output",
            str(out_cli),
            "--tile-capacity",
            "50",
            "--max-zoom",
            "4",
            "--sampling",
            "proportional",
            "--grid-size",
            "32",
            "--memory-limit",
            "1GB",
            "--temp-dir",
            str(tmp_path / "tmp_cli"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"CLI failed: {proc.stderr}\n{proc.stdout}"
    val_cli = validate_file(out_cli, expected_input_rows=300)
    assert val_cli.ok, val_cli.errors

    with ArrowTilesReader(out_cli) as reader:
        meta_cli = reader.metadata()
        assert "phot_g_mean_mag" in set(reader.schema().names)
        assert "abs_m" not in set(reader.schema().names)
        assert meta_cli["sampling"] == "proportional"
        assert meta_cli["grid_size"] == 32
        assert meta_cli["tile_capacity"] == 50
        assert meta_cli["priority"] == {
            "kind": "column",
            "column": "phot_g_mean_mag",
            "order": "asc",
        }
        root_rows = reader.read_tile(0, 0, 0)
        assert root_rows is not None
        assert root_rows.num_rows == 50
        # Brightest 50 stars out of 300 (2 per 0.1-mag step starting at 4.0 -> 25 steps: 4.0..6.4)
        mags = root_rows["phot_g_mean_mag"].to_pylist()
        assert max(mags) <= 6.45


def test_tile_capacity_and_sampling_explicit_passthrough(tmp_path: Path) -> None:
    """Verify exact tile_capacity and sampling mode passthrough on densely clustered input."""
    src_pq = tmp_path / "clustered.parquet"
    con = duckdb.connect()
    # Anchor [0, 1]^2 domain with i=0 at (0,0) and i=1 at (1,1), plus 298 points tightly inside [0.001, 0.011]^2
    con.execute(
        f"""
        COPY (
            SELECT
                CASE
                    WHEN i == 0 THEN 0.0
                    WHEN i == 1 THEN 1.0
                    ELSE 0.001 + (i % 20) * 0.0005
                END AS x,
                CASE
                    WHEN i == 0 THEN 0.0
                    WHEN i == 1 THEN 1.0
                    ELSE 0.001 + (i // 20) * 0.0005
                END AS y,
                CAST(i AS DOUBLE) AS rank_val
            FROM range(300) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    out_even = tmp_path / "clustered_even.arrowtiles"
    out_prop = tmp_path / "clustered_prop.arrowtiles"

    build_generic(
        input_parquet=src_pq,
        output_path=out_even,
        x_col="x",
        y_col="y",
        sort_col="rank_val",
        sort_dir="ASC",
        max_capacity=37,
        grid_size=16,
        max_zoom=5,
        sampling="even_coverage",
        temp_dir=tmp_path / "tmp_even",
        show_progress=False,
    )
    build_generic(
        input_parquet=src_pq,
        output_path=out_prop,
        x_col="x",
        y_col="y",
        sort_col="rank_val",
        sort_dir="ASC",
        max_capacity=37,
        grid_size=16,
        max_zoom=5,
        sampling="proportional",
        temp_dir=tmp_path / "tmp_prop",
        show_progress=False,
    )

    with ArrowTilesReader(out_even) as r_even, ArrowTilesReader(out_prop) as r_prop:
        # In proportional mode, root tile claims exact tile_capacity = 37 rows!
        assert r_prop.read_tile(0, 0, 0).num_rows == 37
        # In even_coverage (16x16 grid over [0,1]^2), (0,0) + 298 cluster points share 1 corner cell
        # and (1,1) occupies the opposite corner cell -> root tile claims exact 2 rows!
        assert r_even.read_tile(0, 0, 0).num_rows == 2


def test_sparse_utinyint_usmallint_categorical_cols(tmp_path: Path) -> None:
    """Regression test: sparse/1-based UTINYINT and USMALLINT columns in categorical_cols remap to dense 0..K-1."""
    src_pq = tmp_path / "sparse_unsigned_cats.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                CAST(i AS DOUBLE) * 0.01 AS x,
                CAST(99 - i AS DOUBLE) * 0.01 AS y,
                CASE
                    WHEN i % 4 == 0 THEN NULL
                    WHEN i % 4 == 1 THEN CAST(10 AS UTINYINT)
                    WHEN i % 4 == 2 THEN CAST(20 AS UTINYINT)
                    ELSE CAST(30 AS UTINYINT)
                END AS sparse_u8,
                CASE
                    WHEN i % 3 == 0 THEN CAST(100 AS USMALLINT)
                    WHEN i % 3 == 1 THEN CAST(250 AS USMALLINT)
                    ELSE CAST(1000 AS USMALLINT)
                END AS sparse_u16
            FROM range(100) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    out_at = tmp_path / "sparse_unsigned_cats.arrowtiles"
    build_generic(
        input_parquet=src_pq,
        output_path=out_at,
        x_col="x",
        y_col="y",
        categorical_cols=["sparse_u8", "sparse_u16"],
        max_capacity=50,
        max_zoom=4,
        temp_dir=tmp_path / "tmp_sparse",
        show_progress=False,
    )

    val = validate_file(out_at, expected_input_rows=100)
    assert val.ok, val.errors

    with ArrowTilesReader(out_at) as reader:
        meta = reader.metadata()
        assert meta["stats"]["sparse_u8"] == {
            "type": "categorical",
            "categories": ["10", "20", "30"],
            "null_count": 25,
        }
        assert meta["stats"]["sparse_u16"] == {
            "type": "categorical",
            "categories": ["100", "250", "1000"],
            "null_count": 0,
        }
        root_raw = reader.read_tile(0, 0, 0, decode_categories=False)
        assert root_raw is not None
        u8_codes = [v for v in root_raw["sparse_u8"].to_pylist() if v is not None]
        assert set(u8_codes) == {0, 1, 2}
        u16_codes = root_raw["sparse_u16"].to_pylist()
        assert set(u16_codes) == {0, 1, 2}

        root_dec = reader.read_tile(0, 0, 0, decode_categories=True)
        assert root_dec is not None
        u8_labels = [v for v in root_dec["sparse_u8"].to_pylist() if v is not None]
        assert set(u8_labels) == {"10", "20", "30"}
        u16_labels = root_dec["sparse_u16"].to_pylist()
        assert set(u16_labels) == {"100", "250", "1000"}


def test_overview_bytes_warning_and_uint64_large_id_col(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify Z=0..2 overview byte reporting/warning and lossless UInt64 --id-col > 2^53 - 1."""
    import arrowtiles.builder as bmod

    src_pq = tmp_path / "large_ids.parquet"
    base_id = 5_900_000_000_000_000_000  # Gaia DR3 source_id scale (> 2^53 - 1)
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                CAST({base_id} AS UBIGINT) + CAST(i AS UBIGINT) AS source_id,
                CAST(i % 25 AS DOUBLE) * 0.04 AS x,
                CAST(i // 25 AS DOUBLE) * 0.1 AS y,
                CAST(i AS FLOAT) AS metric
            FROM range(200) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    # Lower overview warning threshold via monkeypatch to verify the warning fires deterministically
    monkeypatch.setattr(bmod, "OVERVIEW_Z0_2_WARN_BYTES", 100)

    out_at = tmp_path / "large_ids.arrowtiles"
    res = build_generic(
        input_parquet=src_pq,
        output_path=out_at,
        x_col="x",
        y_col="y",
        id_col="source_id",
        max_capacity=40,
        max_zoom=4,
        temp_dir=tmp_path / "tmp_large_id",
        show_progress=False,
    )

    captured = capsys.readouterr().out
    assert "values > 2^53 - 1" in captured
    assert "Z=0..2 overview tiles total" in captured
    assert "--columns" in captured
    assert res["overview_z0_2_bytes"] > 100

    val = validate_file(out_at, expected_input_rows=200)
    assert val.ok, val.errors

    with ArrowTilesReader(out_at) as reader:
        root = reader.read_tile(0, 0, 0)
        assert root is not None
        ids = root["row_id"].to_pylist()
        assert all(base_id <= v < base_id + 200 for v in ids)


def test_cli_columns_and_categorical_cols_space_and_comma_syntax(tmp_path: Path) -> None:
    """Verify --columns and --categorical-cols accept space-separated, comma-separated, and mixed tokens."""
    from arrowtiles.__main__ import _flatten_column_args, build_parser, main as cli_main

    parser = build_parser()
    parsed_space = parser.parse_args(
        [
            "build",
            "--input",
            "in.parquet",
            "--output",
            "out.arrowtiles",
            "--x-col",
            "x",
            "--y-col",
            "y",
            "--columns",
            "model",
            "clusters_14",
            "num_of_tokens",
            "--categorical-cols",
            "clusters_14",
            "model",
        ]
    )
    assert _flatten_column_args(parsed_space.columns) == ["model", "clusters_14", "num_of_tokens"]
    assert _flatten_column_args(parsed_space.categorical_cols) == ["clusters_14", "model"]

    parsed_mixed = parser.parse_args(
        [
            "build",
            "--input",
            "in.parquet",
            "--output",
            "out.arrowtiles",
            "--x-col",
            "x",
            "--y-col",
            "y",
            "--columns",
            "model,clusters_14",
            "num_of_tokens",
            "--categorical-cols",
            "clusters_14,model",
        ]
    )
    assert _flatten_column_args(parsed_mixed.columns) == ["model", "clusters_14", "num_of_tokens"]
    assert _flatten_column_args(parsed_mixed.categorical_cols) == ["clusters_14", "model"]

    # End-to-end CLI build with space-separated --columns and --categorical-cols (matching README.md)
    src_pq = tmp_path / "cli_cols.parquet"
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                CAST(i % 20 AS DOUBLE) * 0.05 AS x,
                CAST(i // 20 AS DOUBLE) * 0.1 AS y,
                CASE WHEN i % 2 = 0 THEN 'gpt-4' ELSE 'claude-3' END AS model,
                CAST(i % 5 AS INTEGER) AS clusters_14,
                CAST(i * 3 + 1 AS INTEGER) AS num_of_tokens,
                CAST(i AS DOUBLE) AS unused_col
            FROM range(120) AS t(i)
        ) TO '{src_pq.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    out_at = tmp_path / "cli_cols.arrowtiles"
    rc = cli_main(
        [
            "build",
            "--input",
            str(src_pq),
            "--output",
            str(out_at),
            "--x-col",
            "x",
            "--y-col",
            "y",
            "--columns",
            "model",
            "clusters_14",
            "num_of_tokens",
            "--categorical-cols",
            "clusters_14",
            "--temp-dir",
            str(tmp_path / "tmp_cli_cols"),
        ]
    )
    assert rc == 0
    val = validate_file(out_at, expected_input_rows=120)
    assert val.ok, val.errors

    with ArrowTilesReader(out_at) as reader:
        names = set(reader.schema().names)
        assert {"model", "clusters_14", "num_of_tokens"}.issubset(names)
        assert "unused_col" not in names
        assert reader.metadata()["stats"]["clusters_14"]["type"] == "categorical"
