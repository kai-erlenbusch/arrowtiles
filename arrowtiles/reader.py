"""ArrowTiles v0.1 reference Python reader (with v0.0 legacy compatibility warning)."""

from __future__ import annotations

import base64
import os
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
from pmtiles.reader import MmapSource, Reader, all_tiles

from arrowtiles._zstd import zstd_decompress


def check_spec_version(metadata: dict[str, Any], path_label: str = "<archive>") -> tuple[bool, str | None]:
    """Validate format/version metadata per SPEC.md §1.

    Returns `(is_legacy, version_str)`. Raises `ValueError` on unknown format or major version.
    """
    fmt = metadata.get("format")
    ver = metadata.get("version")

    if fmt is None and ver is None:
        warnings.warn(
            f"Archive '{path_label}' lacks 'format'/'version' metadata; opening in v0.0 compatibility mode.",
            UserWarning,
            stacklevel=2,
        )
        return True, None

    if fmt != "arrowtiles":
        raise ValueError(
            f"Unsupported archive format {fmt!r} in '{path_label}' (expected 'arrowtiles')"
        )

    if not isinstance(ver, str) or "." not in ver:
        raise ValueError(f"Invalid ArrowTiles version {ver!r} in '{path_label}'")

    major_str = ver.split(".", 1)[0]
    try:
        major = int(major_str)
    except ValueError as exc:
        raise ValueError(f"Invalid ArrowTiles major version in {ver!r}") from exc

    if major != 0:
        raise ValueError(
            f"Unsupported ArrowTiles major version {ver!r} in '{path_label}' (reader supports 0.x)"
        )

    tiling = metadata.get("tiling")
    if tiling is not None and tiling != "quadtree-2d":
        raise ValueError(
            f"Unsupported ArrowTiles tiling {tiling!r} in '{path_label}' (reader supports 'quadtree-2d')"
        )

    return False, ver


class ArrowTilesReader:
    """Reference reader for `.arrowtiles` PMTiles v3 + Zstd Arrow IPC archives."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"Archive not found: {self.path}")

        self._fh = open(self.path, "rb")  # noqa: SIM115
        try:
            self._source = MmapSource(self._fh)
            self._reader = Reader(self._source)
            self._header = dict(self._reader.header())
            raw_meta = self._reader.metadata()
            if not isinstance(raw_meta, dict):
                raise ValueError(f"Expected JSON object metadata in '{self.path}'")
            self._metadata: dict[str, Any] = raw_meta
            self.is_legacy, self.version = check_spec_version(self._metadata, str(self.path))

            b64_schema = self._metadata.get("arrow_schema")
            if not b64_schema or not isinstance(b64_schema, str):
                raise ValueError(f"Missing 'arrow_schema' in metadata of '{self.path}'")
            self._schema_bytes = base64.b64decode(b64_schema)
            self._schema = ipc.RecordBatchStreamReader(self._schema_bytes).schema
        except Exception:
            self._fh.close()
            raise

    def close(self) -> None:
        if getattr(self, "_fh", None) is not None and not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> ArrowTilesReader:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def header(self) -> dict[str, Any]:
        return dict(self._header)

    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    def schema(self) -> pa.Schema:
        return self._schema

    def list_tiles(self) -> list[tuple[int, int, int]]:
        return [tuple(zxy) for zxy, _raw in all_tiles(self._source)]  # type: ignore[misc]

    def _decode_table_payload(
        self,
        raw_tile: bytes,
        z: int,
        x: int,
        y: int,
        *,
        decode_coords: bool = True,
        decode_categories: bool = False,
    ) -> pa.Table:
        decompressed = zstd_decompress(raw_tile)
        table = ipc.open_stream(self._schema_bytes + decompressed).read_all()

        if decode_categories:
            stats = self._metadata.get("stats")
            if isinstance(stats, dict):
                for col_name, col_meta in stats.items():
                    if (
                        isinstance(col_meta, dict)
                        and col_meta.get("type") == "categorical"
                        and isinstance(col_meta.get("categories"), list)
                        and col_name in table.schema.names
                    ):
                        col_idx = table.schema.get_field_index(col_name)
                        col_chunked = table.column(col_idx)
                        if pa.types.is_unsigned_integer(col_chunked.type) or pa.types.is_integer(
                            col_chunked.type
                        ):
                            labels = pa.array(
                                [str(v) for v in col_meta["categories"]],
                                type=pa.string(),
                            )
                            decoded_col = pc.take(labels, col_chunked)
                            table = table.set_column(col_idx, col_name, decoded_col)

        if decode_coords and "x_u16" in table.schema.names and "y_u16" in table.schema.names:
            bounds = self._metadata.get("bounds")
            if isinstance(bounds, dict):
                min_x = float(bounds.get("min_x", 0.0))
                max_x = float(bounds.get("max_x", 1.0))
                min_y = float(bounds.get("min_y", 0.0))
                max_y = float(bounds.get("max_y", 1.0))
            else:
                min_x, max_x, min_y, max_y = 0.0, 1.0, 0.0, 1.0

            span_x = max_x - min_x
            span_y = max_y - min_y
            inv_n = 1.0 / float(1 << int(z))

            x_frac = pc.divide(pc.cast(table["x_u16"], pa.float64()), 65535.0)
            y_frac = pc.divide(pc.cast(table["y_u16"], pa.float64()), 65535.0)
            x_norm = pc.multiply(pc.add(x_frac, float(x)), inv_n)
            y_norm = pc.multiply(pc.add(y_frac, float(y)), inv_n)

            x_dec = pc.add(min_x, pc.multiply(x_norm, span_x))
            if self.is_legacy and not isinstance(bounds, dict):
                # Legacy v0.0 archives without bounds return normalized coordinates
                y_dec = y_norm
            else:
                # ArrowTiles v0.1 top-down Y: y_hat = max_y - y_norm * span_y
                y_dec = pc.subtract(max_y, pc.multiply(y_norm, span_y))

            table = table.append_column("x_decoded", x_dec)
            table = table.append_column("y_decoded", y_dec)

        return table

    def read_tile(
        self,
        z: int,
        x: int,
        y: int,
        *,
        decode_coords: bool = True,
        decode_categories: bool = False,
    ) -> pa.Table | None:
        """Read and decode a single `(z, x, y)` tile, or return `None` if empty."""
        raw_tile = self._reader.get(int(z), int(x), int(y))
        if raw_tile is None:
            return None
        return self._decode_table_payload(
            raw_tile,
            int(z),
            int(x),
            int(y),
            decode_coords=decode_coords,
            decode_categories=decode_categories,
        )

    def iter_tiles(
        self,
        *,
        decode_coords: bool = False,
        decode_categories: bool = False,
    ) -> Iterator[tuple[tuple[int, int, int], pa.Table]]:
        """Stream all non-empty tiles in PMTiles Hilbert order."""
        for (z, x, y), raw_tile in all_tiles(self._source):
            yield (
                (int(z), int(x), int(y)),
                self._decode_table_payload(
                    raw_tile,
                    int(z),
                    int(x),
                    int(y),
                    decode_coords=decode_coords,
                    decode_categories=decode_categories,
                ),
            )
