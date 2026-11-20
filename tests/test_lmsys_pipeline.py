"""LMSys embedding pipeline smoke tests (adapted from archive/tests/test_lmsys.py & test_schema.py)."""

from __future__ import annotations

import base64
import compression.zstd as zstd
import json
from pathlib import Path

import duckdb
import pyarrow.ipc as ipc
import pytest
from pmtiles.reader import MmapSource, Reader, all_tiles

from arrowtiles import ArrowTilesBuilder

MOCK_LMSYS = Path(r"D:\exploratory\duckdb-extension\mock_lmsys.parquet")
FULL_LMSYS = Path(r"D:\exploratory\duckdb-extension\duckdb-cosmograph-oss\lmsys.parquet")


@pytest.mark.skipif(
    not FULL_LMSYS.is_file(),
    reason=f"Requires local dataset {FULL_LMSYS}",
)
def test_lmsys_parquet_schema_columns() -> None:
    con = duckdb.connect()
    cols = [
        r[0]
        for r in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{FULL_LMSYS.as_posix()}')"
        ).fetchall()
    ]
    con.close()
    assert {"x_umap", "y_umap", "num_of_tokens", "model"}.issubset(set(cols))


@pytest.mark.skipif(
    not MOCK_LMSYS.is_file(),
    reason=f"Requires local sample dataset {MOCK_LMSYS}",
)
def test_lmsys_smoke_build_on_sample(tmp_path: Path) -> None:
    output_archive = tmp_path / "lmsys_smoke_test.arrowtiles"
    temp_dir = tmp_path / "lmsys_temp"
    sample_limit = 5_000

    con = duckdb.connect()
    bounds = con.execute(
        f"""
        SELECT MIN(x), MAX(x), MIN(y), MAX(y)
        FROM (SELECT * FROM read_parquet('{MOCK_LMSYS.as_posix()}') LIMIT {sample_limit})
        """
    ).fetchone()
    con.close()

    min_x, max_x, min_y, max_y = bounds
    range_x = (max_x - min_x) or 1.0
    range_y = (max_y - min_y) or 1.0

    custom_query = f"""
        SELECT
            model,
            num_of_tokens,
            CAST((x - ({min_x})) / {range_x} AS DOUBLE) AS x_norm,
            CAST((y - ({min_y})) / {range_y} AS DOUBLE) AS y_norm,
            CAST(num_of_tokens AS FLOAT) AS sort_metric
        FROM (SELECT * FROM read_parquet('{MOCK_LMSYS.as_posix()}') LIMIT {sample_limit})
        WHERE x IS NOT NULL AND y IS NOT NULL
    """

    config = {
        "colorField": "sort_metric",
        "sizeField": "sort_metric",
        "mode": "Chart Mode",
        "colorScale": "rdbu",
    }

    builder = ArrowTilesBuilder(memory_limit="2GB", temp_dir=str(temp_dir))
    builder.build(
        input_query=custom_query,
        output_path=str(output_archive),
        sort_col="sort_metric",
        x_col="x_norm",
        y_col="y_norm",
        sort_dir="DESC",
        max_capacity=2_000,
        max_zoom=8,
        custom_metadata=json.dumps(config),
    )

    assert output_archive.is_file()
    with open(output_archive, "rb") as fh:
        source = MmapSource(fh)
        reader = Reader(source)
        schema_bytes = base64.b64decode(reader.metadata()["arrow_schema"])
        total_rows = sum(
            ipc.open_stream(schema_bytes + zstd.decompress(raw)).read_all().num_rows
            for _zxy, raw in all_tiles(source)
        )
    assert total_rows == sample_limit
