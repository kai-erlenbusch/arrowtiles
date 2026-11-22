"""ArrowTiles v0.1 archive validator (with v0.0 legacy compatibility mode)."""

from __future__ import annotations

import base64
import math
import mmap
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
from pmtiles.reader import Reader, all_tiles, zxy_to_tileid
from pmtiles.tile import Compression, TileType

from arrowtiles._zstd import zstd_decompress

RANGE_WARN_BYTES = 16 * 1024 * 1024  # 16 MiB advisory warning (SPEC.md §2.5 SHOULD)
EXPLICIT_RANGE_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB hard ceiling (SPEC.md §2.5 MUST NOT exceed)

REQUIRED_V01_METADATA_KEYS = (
    "format",
    "version",
    "arrow_schema",
    "bounds",
    "priority",
    "sampling",
    "grid_size",
    "nominal_max_zoom",
    "tile_capacity",
    "max_tile_rows",
    "total_rows",
    "dropped_rows",
    "stats",
)


@dataclass
class ValidationResult:
    path: str
    ok: bool
    is_legacy: bool
    spec_version: str | None
    tile_count: int
    total_rows: int
    declared_total_rows: int | None
    dropped_rows: int | None
    actual_max_zoom: int
    header_max_zoom: int
    observed_max_tile_rows: int
    declared_max_tile_rows: int | None
    max_compressed_tile_bytes: int
    max_compressed_tile_coord: tuple[int, int, int] | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "ok": self.ok,
            "is_legacy": self.is_legacy,
            "spec_version": self.spec_version,
            "tile_count": self.tile_count,
            "total_rows": self.total_rows,
            "declared_total_rows": self.declared_total_rows,
            "dropped_rows": self.dropped_rows,
            "actual_max_zoom": self.actual_max_zoom,
            "header_max_zoom": self.header_max_zoom,
            "observed_max_tile_rows": self.observed_max_tile_rows,
            "declared_max_tile_rows": self.declared_max_tile_rows,
            "max_compressed_tile_bytes": self.max_compressed_tile_bytes,
            "max_compressed_tile_coord": (
                list(self.max_compressed_tile_coord)
                if self.max_compressed_tile_coord is not None
                else None
            ),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def validate_file(
    path: str | os.PathLike[str],
    *,
    expected_input_rows: int | None = None,
    max_exact_rowid_check: int = 20_000_000,
    max_tiles_to_scan: int | None = None,
) -> ValidationResult:
    """Validate an `.arrowtiles` file against SPEC.md v0.1 (or v0.0 compatibility rules)."""
    archive_path = Path(path)
    errors: list[str] = []
    warnings_list: list[str] = []

    if not archive_path.is_file():
        return ValidationResult(
            path=str(archive_path),
            ok=False,
            is_legacy=False,
            spec_version=None,
            tile_count=0,
            total_rows=0,
            declared_total_rows=None,
            dropped_rows=None,
            actual_max_zoom=0,
            header_max_zoom=0,
            observed_max_tile_rows=0,
            declared_max_tile_rows=None,
            max_compressed_tile_bytes=0,
            max_compressed_tile_coord=None,
            warnings=[],
            errors=[f"File does not exist: {archive_path}"],
        )

    with open(archive_path, "rb") as fh:
        magic = fh.read(7)
        if magic != b"PMTiles":
            return ValidationResult(
                path=str(archive_path),
                ok=False,
                is_legacy=False,
                spec_version=None,
                tile_count=0,
                total_rows=0,
                declared_total_rows=None,
                dropped_rows=None,
                actual_max_zoom=0,
                header_max_zoom=0,
                observed_max_tile_rows=0,
                declared_max_tile_rows=None,
                max_compressed_tile_bytes=0,
                max_compressed_tile_coord=None,
                warnings=[],
                errors=["Invalid magic bytes: not a PMTiles archive"],
            )

        try:
            archive_mmap = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        except Exception as exc:
            return ValidationResult(
                path=str(archive_path),
                ok=False,
                is_legacy=False,
                spec_version=None,
                tile_count=0,
                total_rows=0,
                declared_total_rows=None,
                dropped_rows=None,
                actual_max_zoom=0,
                header_max_zoom=0,
                observed_max_tile_rows=0,
                declared_max_tile_rows=None,
                max_compressed_tile_bytes=0,
                max_compressed_tile_coord=None,
                warnings=[],
                errors=[f"Failed to memory-map archive: {exc}"],
            )

        source = lambda offset, length: archive_mmap[offset : offset + length]  # noqa: E731
        try:
            reader = Reader(source)
            header = dict(reader.header())
            metadata = reader.metadata()
        except Exception as exc:
            archive_mmap.close()
            return ValidationResult(
                path=str(archive_path),
                ok=False,
                is_legacy=False,
                spec_version=None,
                tile_count=0,
                total_rows=0,
                declared_total_rows=None,
                dropped_rows=None,
                actual_max_zoom=0,
                header_max_zoom=0,
                observed_max_tile_rows=0,
                declared_max_tile_rows=None,
                max_compressed_tile_bytes=0,
                max_compressed_tile_coord=None,
                warnings=[],
                errors=[f"Failed to read PMTiles header/metadata: {exc}"],
            )

        # 1. PMTiles v3 Header Checks
        if header.get("version") != 3:
            errors.append(f"PMTiles SpecVersion must be 3, found {header.get('version')}")
        if header.get("tile_type") != TileType.UNKNOWN:
            errors.append(
                f"PMTiles TileType must be UNKNOWN (0), found {header.get('tile_type')}"
            )
        if header.get("tile_compression") != Compression.ZSTD:
            errors.append(
                f"PMTiles TileCompression must be ZSTD (4), found {header.get('tile_compression')}"
            )
        if not header.get("clustered", False):
            errors.append("PMTiles archive must have clustered=True")
        if header.get("min_zoom") != 0:
            errors.append(f"PMTiles min_zoom must be 0, found {header.get('min_zoom')}")

        header_max_zoom = int(header.get("max_zoom", 0))

        if not isinstance(metadata, dict):
            errors.append("PMTiles metadata is not a JSON object")
            metadata = {}

        # 2. Format & Version Detection
        fmt = metadata.get("format")
        ver = metadata.get("version")
        is_legacy = False
        spec_version: str | None = None

        if fmt is None and ver is None:
            is_legacy = True
            warnings_list.append(
                "Legacy v0.0 archive: missing 'format' and 'version' metadata"
            )
        else:
            if fmt != "arrowtiles":
                errors.append(f"Invalid metadata.format {fmt!r} (expected 'arrowtiles')")
            if not isinstance(ver, str):
                errors.append(f"Invalid metadata.version {ver!r} (expected '<major>.<minor>')")
            else:
                parts = ver.split(".")
                if (
                    len(parts) != 2
                    or not parts[0].isascii()
                    or not parts[1].isascii()
                    or not parts[0].isdigit()
                    or not parts[1].isdigit()
                ):
                    errors.append(f"Invalid metadata.version {ver!r} (expected '<major>.<minor>')")
                else:
                    spec_version = ver
                    major = int(parts[0])
                    minor = int(parts[1])
                    if major != 0:
                        errors.append(
                            f"Unsupported ArrowTiles major version {ver!r} (validator supports 0.x up to '0.1')"
                        )
                    elif minor > 1:
                        errors.append(
                            f"Unsupported ArrowTiles minor version {ver!r} (validator supports up to '0.1')"
                        )

        declared_total_rows: int | None = None
        dropped_rows: int | None = None
        declared_max_tile_rows: int | None = None
        nominal_max_zoom: int | None = None
        tile_capacity: int | None = None
        sampling_mode: str | None = None
        grid_size: int | None = None

        if not is_legacy:
            tiling_val = metadata.get("tiling")
            if tiling_val is not None and tiling_val != "quadtree-2d":
                errors.append(
                    f"Unsupported metadata.tiling {tiling_val!r} (v0.1 validator supports 'quadtree-2d')"
                )

            req_features = metadata.get("required_features")
            if req_features is not None:
                if not isinstance(req_features, list) or not all(
                    isinstance(f, str) for f in req_features
                ):
                    errors.append(
                        f"Invalid metadata.required_features {req_features!r} (expected list of strings)"
                    )
                elif len(req_features) > 0:
                    errors.append(
                        f"Unsupported metadata.required_features {req_features!r} (v0.1 validator supports none)"
                    )

            for req_key in REQUIRED_V01_METADATA_KEYS:
                if req_key not in metadata:
                    errors.append(f"Missing required v0.1 metadata key '{req_key}'")

            bounds = metadata.get("bounds")
            if isinstance(bounds, dict):
                for bk in ("min_x", "max_x", "min_y", "max_y"):
                    bv = bounds.get(bk)
                    if not isinstance(bv, (int, float)) or not math.isfinite(float(bv)):
                        errors.append(f"bounds.{bk} must be a finite number, got {bv!r}")
                if (
                    isinstance(bounds.get("min_x"), (int, float))
                    and isinstance(bounds.get("max_x"), (int, float))
                    and float(bounds["min_x"]) > float(bounds["max_x"])
                ):
                    errors.append("bounds.min_x must be <= bounds.max_x")
                if (
                    isinstance(bounds.get("min_y"), (int, float))
                    and isinstance(bounds.get("max_y"), (int, float))
                    and float(bounds["min_y"]) > float(bounds["max_y"])
                ):
                    errors.append("bounds.min_y must be <= bounds.max_y")
            elif "bounds" in metadata:
                errors.append("metadata.bounds must be a JSON object")

            priority = metadata.get("priority")
            if isinstance(priority, dict):
                pkind = priority.get("kind")
                if pkind == "random":
                    if not isinstance(priority.get("seed"), int):
                        errors.append("priority.seed must be an integer when kind='random'")
                elif pkind == "column":
                    if not isinstance(priority.get("column"), str) or priority.get("order") not in (
                        "asc",
                        "desc",
                    ):
                        errors.append(
                            "priority with kind='column' requires string 'column' and order in ('asc', 'desc')"
                        )
                else:
                    errors.append(f"Invalid priority.kind {pkind!r}")
            elif "priority" in metadata:
                errors.append("metadata.priority must be a JSON object")

            sampling_val = metadata.get("sampling")
            if sampling_val in ("even_coverage", "proportional"):
                sampling_mode = str(sampling_val)
            elif "sampling" in metadata:
                errors.append(f"Invalid metadata.sampling {sampling_val!r}")

            if isinstance(metadata.get("grid_size"), int):
                grid_size = int(metadata["grid_size"])
                if not (16 <= grid_size <= 512):
                    errors.append(f"metadata.grid_size ({grid_size}) out of range 16..512")

            if isinstance(metadata.get("nominal_max_zoom"), int):
                nominal_max_zoom = int(metadata["nominal_max_zoom"])
                if not (0 <= nominal_max_zoom <= 20):
                    errors.append(
                        f"metadata.nominal_max_zoom ({nominal_max_zoom}) out of range 0..20"
                    )

            if isinstance(metadata.get("tile_capacity"), int):
                tile_capacity = int(metadata["tile_capacity"])
                if tile_capacity < 1:
                    errors.append(f"metadata.tile_capacity ({tile_capacity}) must be >= 1")

            if isinstance(metadata.get("max_tile_rows"), int):
                declared_max_tile_rows = int(metadata["max_tile_rows"])
                if tile_capacity is not None and declared_max_tile_rows < tile_capacity:
                    errors.append(
                        f"metadata.max_tile_rows ({declared_max_tile_rows}) < tile_capacity ({tile_capacity})"
                    )

            if isinstance(metadata.get("total_rows"), int):
                declared_total_rows = int(metadata["total_rows"])
                if declared_total_rows < 0:
                    errors.append("metadata.total_rows must be >= 0")

            if isinstance(metadata.get("dropped_rows"), int):
                dropped_rows = int(metadata["dropped_rows"])
                if dropped_rows < 0:
                    errors.append("metadata.dropped_rows must be >= 0")

            stats = metadata.get("stats")
            if isinstance(stats, dict):
                for col_name, col_stat in stats.items():
                    if not isinstance(col_stat, dict):
                        errors.append(f"stats['{col_name}'] must be a JSON object")
                        continue
                    st_type = col_stat.get("type")
                    if st_type == "numeric":
                        for nk in ("min", "max"):
                            nv = col_stat.get(nk)
                            if not isinstance(nv, (int, float)) or not math.isfinite(float(nv)):
                                errors.append(
                                    f"stats['{col_name}'].{nk} must be a finite number, got {nv!r}"
                                )
                        if not isinstance(col_stat.get("null_count"), int) or col_stat["null_count"] < 0:
                            errors.append(f"stats['{col_name}'].null_count must be a non-negative integer")
                    elif st_type == "categorical":
                        cats = col_stat.get("categories")
                        if (
                            not isinstance(cats, list)
                            or len(cats) == 0
                            or len(cats) > 65_535
                            or not all(isinstance(c, str) for c in cats)
                        ):
                            errors.append(
                                f"stats['{col_name}'].categories must be a non-empty list of <= 65535 strings"
                            )
                        if not isinstance(col_stat.get("null_count"), int) or col_stat["null_count"] < 0:
                            errors.append(f"stats['{col_name}'].null_count must be a non-negative integer")
                    else:
                        errors.append(f"stats['{col_name}'].type {st_type!r} invalid")
            elif "stats" in metadata:
                errors.append("metadata.stats must be a JSON object")

        # 3. Shared Arrow Schema Checks
        schema: pa.Schema | None = None
        schema_bytes = b""
        b64_schema = metadata.get("arrow_schema")
        if not isinstance(b64_schema, str) or not b64_schema:
            errors.append("Missing or non-string metadata.arrow_schema")
        else:
            try:
                schema_bytes = base64.b64decode(b64_schema)
                if len(schema_bytes) == 0 or len(schema_bytes) % 8 != 0:
                    errors.append(
                        f"Decoded arrow_schema length ({len(schema_bytes)}) is not 8-byte aligned"
                    )
                if len(schema_bytes) >= 8 and schema_bytes[-8:] == b"\xff\xff\xff\xff\x00\x00\x00\x00":
                    errors.append("Decoded arrow_schema must not end with an 8-byte EOS marker")
                schema = ipc.RecordBatchStreamReader(schema_bytes).schema
            except Exception as exc:
                errors.append(f"Failed to decode arrow_schema: {exc}")

        has_row_id = False
        categorical_limits: dict[str, int] = {}
        if schema is not None:
            required_cols: dict[str, pa.DataType] = {
                "x_u16": pa.uint16(),
                "y_u16": pa.uint16(),
                "z": pa.uint8(),
            }
            if not is_legacy:
                required_cols["row_id"] = pa.uint64()

            for req_col, req_type in required_cols.items():
                idx = schema.get_field_index(req_col)
                if idx < 0:
                    errors.append(f"Required column '{req_col}' missing from arrow_schema")
                else:
                    fld = schema.field(idx)
                    if fld.type != req_type:
                        errors.append(
                            f"Column '{req_col}' must have type {req_type}, found {fld.type}"
                        )
                    if not is_legacy and fld.nullable:
                        errors.append(f"Column '{req_col}' must be non-nullable in v0.1")

            has_row_id = schema.get_field_index("row_id") >= 0
            if not is_legacy:
                for fld in schema:
                    if pa.types.is_dictionary(fld.type):
                        errors.append(
                            f"Column '{fld.name}' uses DictionaryType, which is forbidden in v0.1"
                        )
                    if fld.name == "final_tile_id" or fld.name.startswith("__at_"):
                        errors.append(
                            f"Internal column '{fld.name}' leaked into exported arrow_schema"
                        )

                if "dropped_columns" in metadata:
                    dcols = metadata["dropped_columns"]
                    if not isinstance(dcols, list) or not all(isinstance(c, str) for c in dcols):
                        errors.append("metadata.dropped_columns must be a list of strings")
                    else:
                        for dc in dcols:
                            if schema.get_field_index(dc) >= 0:
                                errors.append(
                                    f"Column '{dc}' listed in metadata.dropped_columns is still present in arrow_schema"
                                )

                # Verify categorical columns in stats match UInt8 / UInt16 in schema
                stats_obj = metadata.get("stats")
                if isinstance(stats_obj, dict):
                    for col_name, col_stat in stats_obj.items():
                        if isinstance(col_stat, dict) and col_stat.get("type") == "categorical":
                            c_idx = schema.get_field_index(col_name)
                            if c_idx < 0:
                                errors.append(
                                    f"Categorical stats column '{col_name}' missing from arrow_schema"
                                )
                            else:
                                cats = col_stat.get("categories", [])
                                if isinstance(cats, list) and len(cats) > 0:
                                    categorical_limits[col_name] = len(cats)
                                expected_pa = (
                                    pa.uint8() if len(cats) <= 256 else pa.uint16()
                                )
                                actual_pa = schema.field(c_idx).type
                                if actual_pa != expected_pa:
                                    errors.append(
                                        f"Categorical column '{col_name}' ({len(cats)} categories) "
                                        f"must have type {expected_pa}, found {actual_pa}"
                                    )

        # 4. Streaming Tile Payload & Invariant Verification
        tile_count = 0
        total_rows = 0
        actual_max_zoom = 0
        observed_max_tile_rows = 0
        max_compressed_tile_bytes = 0
        max_compressed_tile_coord: tuple[int, int, int] | None = None
        last_tid: int | None = None

        exact_rowid_mode = (
            not is_legacy
            and has_row_id
            and max_tiles_to_scan is None
            and (declared_total_rows is None or declared_total_rows <= max_exact_rowid_check)
        )
        rowid_chunks: list[pa.Array] = []
        sampled_rowid_chunks: list[pa.Array] = []

        if schema is not None:
            for (z, x, y), raw_tile in all_tiles(source):
                if max_tiles_to_scan is not None and tile_count >= max_tiles_to_scan:
                    warnings_list.append(
                        f"Stopped tile scan after {max_tiles_to_scan} tiles (partial scan requested)"
                    )
                    break

                tile_count += 1
                z_int, x_int, y_int = int(z), int(x), int(y)
                if z_int > actual_max_zoom:
                    actual_max_zoom = z_int

                tid = zxy_to_tileid(z_int, x_int, y_int)
                if last_tid is not None and tid <= last_tid:
                    errors.append(
                        f"Tiles are not strictly ordered by Hilbert tile_id: {tid} after {last_tid}"
                    )
                last_tid = tid

                comp_len = len(raw_tile)
                if comp_len > max_compressed_tile_bytes:
                    max_compressed_tile_bytes = comp_len
                    max_compressed_tile_coord = (z_int, x_int, y_int)

                try:
                    decompressed = zstd_decompress(raw_tile)
                except Exception as exc:
                    errors.append(f"Zstd decompression failed on tile {z_int}/{x_int}/{y_int}: {exc}")
                    continue

                if len(decompressed) < 8 or decompressed[:4] != b"\xff\xff\xff\xff":
                    errors.append(
                        f"Tile {z_int}/{x_int}/{y_int} uncompressed payload missing 0xFFFFFFFF IPC continuation marker"
                    )
                    continue

                if not is_legacy and decompressed[-8:] != b"\xff\xff\xff\xff\x00\x00\x00\x00":
                    errors.append(
                        f"Tile {z_int}/{x_int}/{y_int} uncompressed payload missing trailing 8-byte EOS marker"
                    )

                try:
                    reader_ipc = ipc.open_stream(schema_bytes + decompressed)
                    batches = list(reader_ipc)
                    if not is_legacy and len(batches) != 1:
                        errors.append(
                            f"Tile {z_int}/{x_int}/{y_int} must contain exactly 1 RecordBatch in v0.1, found {len(batches)}"
                        )
                    table = pa.Table.from_batches(batches, schema=schema)
                except Exception as exc:
                    errors.append(
                        f"Arrow IPC parse failed on tile {z_int}/{x_int}/{y_int}: {exc}"
                    )
                    continue

                nrows = table.num_rows
                if nrows == 0:
                    errors.append(f"Empty (0-row) tile written at {z_int}/{x_int}/{y_int}")
                    continue

                total_rows += nrows
                if nrows > observed_max_tile_rows:
                    observed_max_tile_rows = nrows

                if not is_legacy:
                    if declared_max_tile_rows is not None and nrows > declared_max_tile_rows:
                        errors.append(
                            f"Tile {z_int}/{x_int}/{y_int} has {nrows} rows > declared max_tile_rows ({declared_max_tile_rows})"
                        )
                    if nominal_max_zoom is not None and z_int < nominal_max_zoom:
                        if (
                            sampling_mode == "even_coverage"
                            and grid_size is not None
                            and z_int <= 6
                        ):
                            if nrows > grid_size * grid_size:
                                errors.append(
                                    f"Even-coverage coarse tile {z_int}/{x_int}/{y_int} has {nrows} rows > grid_size^2 ({grid_size * grid_size})"
                                )
                        elif tile_capacity is not None and nrows > tile_capacity:
                            errors.append(
                                f"Non-leaf tile {z_int}/{x_int}/{y_int} has {nrows} rows > tile_capacity ({tile_capacity})"
                            )

                    # Verify z column matches tile z
                    z_col = table["z"]
                    if z_col.null_count > 0 or not pc.all(pc.equal(z_col, z_int)).as_py():
                        errors.append(
                            f"Tile {z_int}/{x_int}/{y_int} contains row(s) with mismatched 'z' column value"
                        )

                    # Verify all categorical codes satisfy 0 <= code < len(categories)
                    for cat_col_name, cat_len in categorical_limits.items():
                        cat_col = table[cat_col_name]
                        if cat_col.null_count < nrows:
                            mm = pc.min_max(cat_col).as_py()
                            c_min = mm.get("min")
                            c_max = mm.get("max")
                            if c_min is not None and c_max is not None and (
                                int(c_min) < 0 or int(c_max) >= cat_len
                            ):
                                errors.append(
                                    f"Tile {z_int}/{x_int}/{y_int} categorical column '{cat_col_name}' "
                                    f"has out-of-range code(s) [{c_min}, {c_max}] (expected 0..{cat_len - 1})"
                                )

                    if has_row_id:
                        rid_col = table["row_id"]
                        if rid_col.null_count > 0:
                            errors.append(f"Tile {z_int}/{x_int}/{y_int} contains NULL row_id")
                        elif exact_rowid_mode:
                            if len(rowid_chunks) + len(rid_col.chunks) and (total_rows <= max_exact_rowid_check):
                                rowid_chunks.extend(rid_col.chunks)
                            else:
                                exact_rowid_mode = False
                                rowid_chunks.clear()
                        else:
                            # Per-tile uniqueness + deterministic 1/64th cross-tile sample
                            if pc.count_distinct(rid_col, mode="only_valid").as_py() != nrows:
                                errors.append(
                                    f"Duplicate row_id detected within tile {z_int}/{x_int}/{y_int}"
                                )
                            mask = pc.equal(pc.bit_wise_and(rid_col, 63), 0)
                            sampled = pc.filter(rid_col, mask)
                            if len(sampled) > 0:
                                sampled_rowid_chunks.extend(sampled.chunks)

        # 5. Cross-tile & Header Post-Checks
        if max_compressed_tile_bytes > EXPLICIT_RANGE_MAX_BYTES:
            msg = (
                f"Largest compressed tile ({max_compressed_tile_bytes:,} bytes at {max_compressed_tile_coord}) "
                f"exceeds 64 MiB hard ceiling ({EXPLICIT_RANGE_MAX_BYTES:,} bytes)"
            )
            if is_legacy:
                warnings_list.append(msg)
            else:
                errors.append(msg)
        elif max_compressed_tile_bytes > RANGE_WARN_BYTES:
            warnings_list.append(
                f"Largest compressed tile ({max_compressed_tile_bytes:,} bytes at {max_compressed_tile_coord}) "
                f"exceeds 16 MiB advisory threshold ({RANGE_WARN_BYTES:,} bytes)"
            )

        if max_tiles_to_scan is None:
            if tile_count == 0:
                errors.append("Archive contains 0 tiles")
            elif header_max_zoom != actual_max_zoom:
                msg = (
                    f"PMTiles header max_zoom ({header_max_zoom}) != deepest written zoom ({actual_max_zoom})"
                )
                if is_legacy:
                    warnings_list.append(f"Legacy header mismatch: {msg}")
                else:
                    errors.append(msg)

            if not is_legacy:
                if declared_total_rows is not None and total_rows != declared_total_rows:
                    errors.append(
                        f"Sum of tile rows ({total_rows}) != metadata.total_rows ({declared_total_rows})"
                    )
                if (
                    expected_input_rows is not None
                    and declared_total_rows is not None
                    and dropped_rows is not None
                    and (declared_total_rows + dropped_rows) != int(expected_input_rows)
                ):
                    errors.append(
                        f"total_rows ({declared_total_rows}) + dropped_rows ({dropped_rows}) != "
                        f"expected_input_rows ({expected_input_rows})"
                    )

                if exact_rowid_mode and rowid_chunks:
                    all_rids = pa.chunked_array(rowid_chunks, type=pa.uint64())
                    distinct_rids = int(pc.count_distinct(all_rids, mode="only_valid").as_py())
                    if distinct_rids != total_rows:
                        errors.append(
                            f"Global row_id uniqueness violated: {distinct_rids} distinct row_ids across {total_rows} rows"
                        )
                elif sampled_rowid_chunks:
                    sampled_rids = pa.chunked_array(sampled_rowid_chunks, type=pa.uint64())
                    distinct_sampled = int(
                        pc.count_distinct(sampled_rids, mode="only_valid").as_py()
                    )
                    if distinct_sampled != len(sampled_rids):
                        errors.append(
                            f"Sampled cross-tile row_id uniqueness violated: "
                            f"{distinct_sampled} distinct out of {len(sampled_rids)} sampled row_ids"
                        )

        archive_mmap.close()

    return ValidationResult(
        path=str(archive_path),
        ok=(len(errors) == 0),
        is_legacy=is_legacy,
        spec_version=spec_version,
        tile_count=tile_count,
        total_rows=total_rows,
        declared_total_rows=declared_total_rows,
        dropped_rows=dropped_rows,
        actual_max_zoom=actual_max_zoom,
        header_max_zoom=header_max_zoom,
        observed_max_tile_rows=observed_max_tile_rows,
        declared_max_tile_rows=declared_max_tile_rows,
        max_compressed_tile_bytes=max_compressed_tile_bytes,
        max_compressed_tile_coord=max_compressed_tile_coord,
        warnings=warnings_list,
        errors=errors,
    )
