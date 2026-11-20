"""Synthetic end-to-end pipeline smoke tests (adapted from archive/tests/create_dummy.py & read_meta_pmtiles.py)."""

from __future__ import annotations

import base64
import compression.zstd as zstd
from pathlib import Path

import duckdb
import pyarrow.ipc as ipc
from pmtiles.reader import MmapSource, Reader, all_tiles

from arrowtiles import build_generic


def test_build_generic_synthetic_roundtrip(tmp_path: Path) -> None:
    """Build a synthetic Parquet dataset with numeric + categorical columns and verify PMTiles + Arrow IPC output."""
    input_parquet = tmp_path / "dummy.parquet"
    output_arrowtiles = tmp_path / "dummy_out.arrowtiles"
    temp_dir = tmp_path / "duckdb_temp"

    num_rows = 5_000
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT
                (i % 100) / 100.0 AS x,
                ((i // 100) % 50) / 50.0 AS y,
                CAST(i % 250 AS DOUBLE) AS score,
                CASE (i % 4)
                    WHEN 0 THEN 'alpha'
                    WHEN 1 THEN 'beta'
                    WHEN 2 THEN 'gamma'
                    ELSE 'delta'
                END AS group_label
            FROM range({num_rows}) AS t(i)
        ) TO '{input_parquet.as_posix()}' (FORMAT PARQUET)
        """
    )
    con.close()

    build_generic(
        input_parquet=input_parquet.as_posix(),
        output_path=str(output_arrowtiles),
        x_col="x",
        y_col="y",
        sort_col="score",
        memory_limit="2GB",
        temp_dir=str(temp_dir),
    )

    assert output_arrowtiles.is_file()
    assert output_arrowtiles.stat().st_size > 127

    with open(output_arrowtiles, "rb") as fh:
        source = MmapSource(fh)
        reader = Reader(source)
        metadata = reader.metadata()
        assert "arrow_schema" in metadata

        schema_bytes = base64.b64decode(metadata["arrow_schema"])
        schema = ipc.RecordBatchStreamReader(schema_bytes).schema
        field_names = set(schema.names)
        assert {"x_u16", "y_u16", "z", "score", "group_label"}.issubset(field_names)

        total_rows = 0
        tile_count = 0
        for _zxy, raw_tile in all_tiles(source):
            tile_count += 1
            decompressed = zstd.decompress(raw_tile)
            table = ipc.open_stream(schema_bytes + decompressed).read_all()
            total_rows += table.num_rows

    assert tile_count > 0
    assert total_rows == num_rows
