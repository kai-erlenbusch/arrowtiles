"""Gaia Hammer-projection pipeline smoke tests (portable fixtures & Zstd helper).

Writes exclusively to pytest `tmp_path`; never touches `gaia_full.arrowtiles` or `s3_cache/`.
"""

from __future__ import annotations

import base64
from pathlib import Path

import duckdb
import pyarrow.ipc as ipc
from pmtiles.reader import MmapSource, Reader, all_tiles

from arrowtiles import ArrowTilesBuilder
from conftest import zstd_decompress


def test_gaia_batch_schema_and_hammer_smoke_build(
    gaia_batch0_parquet_path: Path, tmp_path: Path
) -> None:
    con = duckdb.connect()
    cols = [
        r[0]
        for r in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{gaia_batch0_parquet_path.as_posix()}')"
        ).fetchall()
    ]
    con.close()
    assert {
        "ra",
        "dec",
        "magnitude",
        "bv",
        "parallax",
        "pmra",
        "pmdec",
        "radial_velocity",
        "teff_gspphot",
    }.issubset(set(cols))

    sample_limit = 5_000
    output_arrowtiles = tmp_path / "gaia_smoke_test.arrowtiles"
    temp_dir = tmp_path / "gaia_temp"

    custom_query = f"""
        WITH raw_data AS (
            SELECT
                ra, dec, magnitude, bv, parallax, pmra, pmdec, radial_velocity, teff_gspphot,
                RADIANS(ra) AS ra_rad,
                RADIANS(dec) AS dec_rad,
                RADIANS(192.85948) AS a_g,
                RADIANS(27.12825) AS d_g,
                RADIANS(122.93192) AS l_ncp
            FROM read_parquet('{gaia_batch0_parquet_path.as_posix()}')
            WHERE ra IS NOT NULL AND dec IS NOT NULL
            LIMIT {sample_limit}
        ),
        galactic AS (
            SELECT
                *,
                ASIN(SIN(d_g)*SIN(dec_rad) + COS(d_g)*COS(dec_rad)*COS(ra_rad - a_g)) AS b_rad,
                l_ncp - ATAN2(
                    COS(dec_rad)*SIN(ra_rad - a_g),
                    COS(d_g)*SIN(dec_rad) - SIN(d_g)*COS(dec_rad)*COS(ra_rad - a_g)
                ) AS l_rad_raw
            FROM raw_data
        ),
        wrapped AS (
            SELECT *, ((l_rad_raw + 5*PI()) % (2*PI())) - PI() AS l_rad FROM galactic
        )
        SELECT
            CAST(( ( -2 * sqrt(2) * cos(b_rad) * sin(l_rad / 2) ) / sqrt(1 + cos(b_rad) * cos(l_rad / 2)) + 2.8284271247461903 ) / 5.6568542494923806 AS DOUBLE) AS x_norm,
            1.0 - CAST(( ((sqrt(2) * sin(b_rad)) / sqrt(1 + cos(b_rad) * cos(l_rad / 2))) + 1.4142135623730951 ) / 2.8284271247461903 AS DOUBLE) AS y_norm,
            CAST(magnitude AS FLOAT) AS abs_m,
            CAST(bv AS FLOAT) AS bp_rp,
            CAST(radial_velocity AS FLOAT) AS radial_velocity,
            CAST(teff_gspphot AS FLOAT) AS teff_gspphot,
            CAST(parallax AS FLOAT) AS parallax,
            CAST(pmra AS FLOAT) AS pmra,
            CAST(pmdec AS FLOAT) AS pmdec
        FROM wrapped
    """

    builder = ArrowTilesBuilder(memory_limit="2GB", temp_dir=str(temp_dir))
    builder.build(
        input_query=custom_query,
        output_path=str(output_arrowtiles),
        sort_col="abs_m",
        x_col="x_norm",
        y_col="y_norm",
        max_capacity=2_000,
        max_zoom=10,
        resume=False,
    )

    assert output_arrowtiles.is_file()
    with open(output_arrowtiles, "rb") as fh:
        source = MmapSource(fh)
        reader = Reader(source)
        schema_bytes = base64.b64decode(reader.metadata()["arrow_schema"])
        total_rows = sum(
            ipc.open_stream(schema_bytes + zstd_decompress(raw)).read_all().num_rows
            for _zxy, raw in all_tiles(source)
        )
    assert total_rows == sample_limit
