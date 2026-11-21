"""Tests for SPEC.md v0.1 reserved `tiling` metadata contract (`quadtree-2d` default & unknown-tiling rejection)."""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pmtiles.reader import MmapSource, Reader, all_tiles
from pmtiles.tile import Compression, TileType
from pmtiles.writer import Writer

from arrowtiles import (
    SPEC_TILING,
    ArrowTilesReader,
    build_generic,
    validate_file,
)


def _make_tiny_parquet(path: Path) -> None:
    tbl = pa.table(
        {
            "x": [0.0, 10.0, 20.0, 30.0],
            "y": [0.0, 10.0, 20.0, 30.0],
            "val": [1.0, 2.0, 3.0, 4.0],
        }
    )
    pq.write_table(tbl, path)


def _rewrite_metadata(src_path: Path, dst_path: Path, mutate_fn) -> None:
    with open(src_path, "rb") as fh:
        source = MmapSource(fh)
        reader = Reader(source)
        header = dict(reader.header())
        meta = dict(reader.metadata())
        tiles = [(zxy, bytes(raw)) for zxy, raw in all_tiles(source)]

    mutate_fn(meta)

    with open(dst_path, "wb") as out_fh:
        writer = Writer(out_fh)
        from pmtiles.tile import zxy_to_tileid

        for (z, x, y), raw in sorted(tiles, key=lambda item: zxy_to_tileid(*item[0])):
            writer.write_tile(zxy_to_tileid(z, x, y), raw)

        meta_bytes = json.dumps(meta, sort_keys=True).encode("utf-8")
        meta_comp = header.get("internal_compression", Compression.GZIP)
        if meta_comp == Compression.GZIP:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
                gz.write(meta_bytes)
            encoded_meta = buf.getvalue()
        else:
            encoded_meta = meta_bytes

        writer.finalize(
            {
                "tile_type": TileType.UNKNOWN,
                "tile_compression": Compression.ZSTD,
                "min_zoom": header.get("min_zoom", 0),
                "max_zoom": header.get("max_zoom", 0),
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
        _ = encoded_meta


def test_spec_tiling_quadtree_2d_emitted_reserved_and_enforced(tmp_path: Path) -> None:
    pq_path = tmp_path / "pts.parquet"
    out_path = tmp_path / "pts.arrowtiles"
    _make_tiny_parquet(pq_path)

    # 1. Reserved key collision on `tiling` in custom_config must fail fast
    with pytest.raises(ValueError, match="tiling"):
        build_generic(
            input_parquet=pq_path,
            output_path=out_path,
            x_col="x",
            y_col="y",
            custom_config='{"tiling": "octree-3d"}',
            show_progress=False,
        )

    # 2. Standard build emits `tiling == "quadtree-2d"` and validates cleanly
    build_generic(
        input_parquet=pq_path,
        output_path=out_path,
        x_col="x",
        y_col="y",
        show_progress=False,
    )
    res = validate_file(out_path)
    assert res.ok, res.errors

    with ArrowTilesReader(out_path) as rdr:
        assert rdr.metadata().get("tiling") == SPEC_TILING == "quadtree-2d"

    # 3. Omitted `tiling` (existing v0.1 files) stays backward-compatible
    omitted_path = tmp_path / "pts_omitted_tiling.arrowtiles"
    _rewrite_metadata(out_path, omitted_path, lambda m: m.pop("tiling", None))
    res_omitted = validate_file(omitted_path)
    assert res_omitted.ok, res_omitted.errors
    with ArrowTilesReader(omitted_path) as rdr_omitted:
        assert rdr_omitted.metadata().get("tiling") is None

    # 4. Unknown `tiling` (e.g. future `"octree-3d"`) is rejected by both validator and reader
    octree_path = tmp_path / "pts_octree.arrowtiles"
    _rewrite_metadata(out_path, octree_path, lambda m: m.__setitem__("tiling", "octree-3d"))
    res_octree = validate_file(octree_path)
    assert not res_octree.ok
    assert any("tiling" in e and "octree-3d" in e for e in res_octree.errors)

    with pytest.raises(ValueError, match="octree-3d"):
        ArrowTilesReader(octree_path)
