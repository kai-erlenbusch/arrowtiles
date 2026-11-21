"""ArrowTiles v0.1 2-pass DuckDB + Rust (PyO3) builder (Phase 2 deterministic & single-scan preflight)."""

from __future__ import annotations

import glob
import hashlib
import json
import math
import multiprocessing
import os
import shutil
import time
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.cffi as pc
from tqdm import tqdm

SPEC_FORMAT = "arrowtiles"
SPEC_VERSION = "0.1"
DEFAULT_TILE_CAPACITY = 25_000
DEFAULT_GAIA_TILE_CAPACITY = 100_000
DEFAULT_MAX_TILE_ROWS = 262_144
DEFAULT_NOMINAL_MAX_ZOOM = 14
DEFAULT_RANDOM_SEED = 42
MAX_CATEGORIES_CAP = 65_535
DEFAULT_AUTO_MAX_CATEGORIES = 4_096
OVERVIEW_Z0_2_WARN_BYTES = 10 * 1024 * 1024  # 10 MiB compressed Z=0..2 overview threshold
JS_MAX_SAFE_INTEGER = 9_007_199_254_740_991   # 2^53 - 1

SPLITMIX64_GAMMA = 11400714819323198485  # 0x9E3779B97F4A7C15
SPLITMIX64_MUL1 = 13787848793156543929   # 0xBF58476D1CE4E5B9
SPLITMIX64_MUL2 = 10723151780598845931   # 0x94D049BB133111EB
MASK_U64 = 18446744073709551615          # 0xFFFFFFFFFFFFFFFF


def splitmix64_py(row_id: int, seed: int) -> int:
    """Portable unsigned 64-bit SplitMix64 mix over (row_id, seed) per SPEC.md §6.1."""
    r_u64 = int(row_id) & MASK_U64
    seed_u64 = int(seed) & MASK_U64
    z0 = (r_u64 + seed_u64 + SPLITMIX64_GAMMA) & MASK_U64
    z1 = ((z0 ^ (z0 >> 30)) * SPLITMIX64_MUL1) & MASK_U64
    z2 = ((z1 ^ (z1 >> 27)) * SPLITMIX64_MUL2) & MASK_U64
    return (z2 ^ (z2 >> 31)) & MASK_U64


def _duckdb_splitmix64_sql(row_id_expr: str, seed: int) -> str:
    """Render portable unsigned 64-bit SplitMix64 in DuckDB SQL using UHUGEINT wrapping arithmetic."""
    seed_plus_gamma = ((int(seed) & MASK_U64) + SPLITMIX64_GAMMA) & MASK_U64
    mask_sql = f"CAST({MASK_U64} AS UHUGEINT)"
    r_u128 = f"CAST(CAST({row_id_expr} AS UBIGINT) AS UHUGEINT)"
    z0 = f"(({r_u128} + CAST({seed_plus_gamma} AS UHUGEINT)) & {mask_sql})"
    z1 = f"((xor({z0}, ({z0} >> 30)) * CAST({SPLITMIX64_MUL1} AS UHUGEINT)) & {mask_sql})"
    z2 = f"((xor({z1}, ({z1} >> 27)) * CAST({SPLITMIX64_MUL2} AS UHUGEINT)) & {mask_sql})"
    return f"CAST(xor({z2}, ({z2} >> 31)) AS UBIGINT)"

RESERVED_COLUMN_NAMES = frozenset({"row_id", "x_u16", "y_u16", "z", "final_tile_id"})

RESERVED_METADATA_KEYS = frozenset(
    {
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
        "dropped_columns",
        "stats",
        "tile_stats",
        "view",
        "layers",
        "edges",
    }
)

DUCKDB_INTEGER_TYPES = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "INT",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
    }
)

DUCKDB_NUMERIC_TYPES = DUCKDB_INTEGER_TYPES | frozenset(
    {"FLOAT", "REAL", "DOUBLE", "DECIMAL", "NUMERIC"}
)


def _reject_non_finite_json(constant: str) -> Any:
    raise ValueError(
        f"Invalid JSON constant '{constant}': NaN and Infinity are forbidden in RFC 8259 metadata"
    )


def parse_strict_json_object(raw_json: str, label: str = "JSON") -> dict[str, Any]:
    """Parse a JSON string strictly (rejecting NaN/Infinity) and require a top-level object."""
    try:
        parsed = json.loads(raw_json, parse_constant=_reject_non_finite_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Invalid {label}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object, got {type(parsed).__name__}")
    return parsed


def _load_core_module():
    try:
        from arrowtiles import _core

        return _core
    except ImportError:
        try:
            import arrowtiles_core as _core  # type: ignore[no-redef]

            return _core
        except ImportError as exc:
            raise ImportError(
                "Native engine 'arrowtiles._core' not found. "
                "Run `maturin develop --release` inside the project virtualenv."
            ) from exc


def _compute_files_fingerprint(sorted_paths: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p_str in sorted_paths:
        st = os.stat(p_str)
        out.append(
            {
                "path": p_str,
                "size": int(st.st_size),
                "mtime_ns": int(st.st_mtime_ns),
            }
        )
    return out


class ArrowTilesBuilder:
    """Two-pass out-of-core DuckDB + Rust ArrowTiles v0.1 builder."""

    def __init__(
        self,
        memory_limit: str = "40GB",
        temp_dir: str | os.PathLike[str] | None = None,
        threads: int | None = None,
        show_progress: bool = True,
    ) -> None:
        if threads is None:
            total_threads = max(2, (multiprocessing.cpu_count() or 4) - 2)
        else:
            total_threads = max(2, int(threads))
        duckdb_threads = max(1, int(total_threads * 0.6))
        rayon_threads = max(1, total_threads - duckdb_threads)

        os.environ["RAYON_NUM_THREADS"] = str(rayon_threads)
        self.rayon_threads = rayon_threads
        self.show_progress = show_progress

        resolved_temp = Path(temp_dir) if temp_dir is not None else Path("./duckdb_temp")
        resolved_temp.mkdir(parents=True, exist_ok=True)
        self.temp_dir = str(resolved_temp.resolve())

        self.con: duckdb.DuckDBPyConnection | None = duckdb.connect(
            config={
                "temp_directory": self.temp_dir,
                "max_memory": memory_limit,
                "threads": str(duckdb_threads),
            }
        )
        self.con.execute("PRAGMA max_temp_directory_size='400GB';")
        if show_progress:
            self.con.execute("PRAGMA enable_progress_bar;")
            self.con.execute("PRAGMA enable_print_progress_bar;")

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        if self.con is not None:
            self.con.close()
            self.con = None

    def __enter__(self) -> ArrowTilesBuilder:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    @staticmethod
    def format_time(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m}m {s}s"
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"

    def get_engine_path(self) -> str:
        return "NATIVE_PYO3"

    @staticmethod
    def _quote_ident(ident: str) -> str:
        return '"' + str(ident).replace('"', '""') + '"'

    @staticmethod
    def _sql_str(value: str | os.PathLike[str]) -> str:
        text = str(value).replace("'", "''")
        return f"'{text}'"

    @classmethod
    def _sql_path_expr(cls, input_parquet: str | os.PathLike[str] | list[str]) -> str:
        if isinstance(input_parquet, (list, tuple)):
            if not input_parquet:
                raise ValueError("input_parquet list must not be empty")
            items = [cls._sql_str(Path(p).as_posix()) for p in input_parquet]
            return "[" + ", ".join(items) + "]"
        norm = str(input_parquet).replace("\\", "/")
        return cls._sql_str(norm)

    @staticmethod
    def _base_duckdb_type(type_str: str) -> str:
        return str(type_str).split("(")[0].strip().upper()

    def _single_pass_preflight_direct(
        self,
        input_query: str,
        x_col: str,
        y_col: str,
        id_col: str,
        retained_col_types: list[tuple[str, str]],
        categorical_columns: dict[str, list[str]],
        need_stats: bool,
    ) -> tuple[int, int, dict[str, dict[str, Any]]]:
        """Run a single SQL scan over `input_query` for row counts, id_col checks, and optional stats."""
        assert self.con is not None
        q = self._quote_ident
        q_x = f"src.{q(x_col)}"
        q_y = f"src.{q(y_col)}"
        q_id = f"src.{q(id_col)}"
        finite_pred = (
            f"{q_x} IS NOT NULL AND {q_y} IS NOT NULL "
            f"AND isfinite(CAST({q_x} AS DOUBLE)) AND isfinite(CAST({q_y} AS DOUBLE))"
        )

        aggs: list[str] = [
            "COUNT(*) AS total_in",
            f"COUNT(*) FILTER (WHERE {finite_pred}) AS valid_in",
            f"COUNT(*) FILTER (WHERE {finite_pred} AND {q_id} IS NULL) AS null_ids",
            f"COUNT(*) FILTER (WHERE {finite_pred} AND {q_id} < 0) AS neg_ids",
            f"MAX(CAST({q_id} AS UBIGINT)) FILTER (WHERE {finite_pred} AND {q_id} IS NOT NULL AND {q_id} >= 0) AS max_id",
        ]
        meta_plan: list[tuple[str, str]] = []

        if need_stats:
            for col_name, col_type in retained_col_types:
                qc = f"src.{q(col_name)}"
                if col_name in categorical_columns:
                    aggs.append(f"COUNT(*) FILTER (WHERE {finite_pred} AND {qc} IS NULL)")
                    meta_plan.append((col_name, "categorical"))
                elif self._base_duckdb_type(col_type) in DUCKDB_NUMERIC_TYPES:
                    aggs.append(
                        f"MIN(CAST({qc} AS DOUBLE)) FILTER (WHERE {finite_pred} AND {qc} IS NOT NULL AND isfinite(CAST({qc} AS DOUBLE)))"
                    )
                    aggs.append(
                        f"MAX(CAST({qc} AS DOUBLE)) FILTER (WHERE {finite_pred} AND {qc} IS NOT NULL AND isfinite(CAST({qc} AS DOUBLE)))"
                    )
                    aggs.append(f"COUNT(*) FILTER (WHERE {finite_pred} AND {qc} IS NULL)")
                    meta_plan.append((col_name, "numeric"))

        row = self.con.execute(
            f"SELECT {', '.join(aggs)} FROM ({input_query}) AS src"
        ).fetchone()
        assert row is not None

        query_total_in = int(row[0] or 0)
        query_valid_in = int(row[1] or 0)
        null_ids = int(row[2] or 0)
        neg_ids = int(row[3] or 0)
        max_id_val = int(row[4] or 0)
        if null_ids > 0:
            raise ValueError(f"id_col '{id_col}' contains {null_ids} NULL value(s)")
        if neg_ids > 0:
            raise ValueError(f"id_col '{id_col}' contains {neg_ids} negative value(s)")
        if query_valid_in == 0:
            raise ValueError("Input contains 0 rows with finite (x, y) coordinates")
        if max_id_val > JS_MAX_SAFE_INTEGER:
            print(
                f"[ArrowTiles] Warning: id_col '{id_col}' has values > 2^53 - 1 (max={max_id_val}); "
                f"stored losslessly as UInt64, but JavaScript consumers should inspect rowIdBigInt for exact precision.",
                flush=True,
            )

        stats: dict[str, dict[str, Any]] = {}
        idx = 5
        for col_name, kind in meta_plan:
            if kind == "categorical":
                null_count = int(row[idx] or 0)
                idx += 1
                stats[col_name] = {
                    "type": "categorical",
                    "categories": list(categorical_columns[col_name]),
                    "null_count": null_count,
                }
            else:
                raw_min, raw_max, raw_null = row[idx], row[idx + 1], row[idx + 2]
                idx += 3
                min_f = float(raw_min) if raw_min is not None and math.isfinite(float(raw_min)) else 0.0
                max_f = float(raw_max) if raw_max is not None and math.isfinite(float(raw_max)) else 0.0
                stats[col_name] = {
                    "type": "numeric",
                    "min": min_f,
                    "max": max_f,
                    "null_count": int(raw_null or 0),
                }

        return query_valid_in, (query_total_in - query_valid_in), stats

    def build(
        self,
        input_query: str,
        output_path: str | os.PathLike[str],
        sort_col: str | None = None,
        x_col: str = "x_norm",
        y_col: str = "y_norm",
        sort_dir: str = "ASC",
        max_capacity: int = DEFAULT_TILE_CAPACITY,
        max_zoom: int = DEFAULT_NOMINAL_MAX_ZOOM,
        max_tile_rows: int | None = None,
        sampling: str = "proportional",
        grid_size: int | None = None,
        seed: int = DEFAULT_RANDOM_SEED,
        id_col: str | None = None,
        allow_oversize_leaves: bool = False,
        resume: bool = False,
        z_buffer_limit: int = 100_000,
        chunk_buffer_limit: int = 500_000,
        custom_metadata: str | None = None,
        categorical_columns: dict[str, list[str]] | None = None,
        bounds: dict[str, float] | None = None,
        stats: dict[str, dict[str, Any]] | None = None,
        view: dict[str, Any] | None = None,
        dropped_columns: list[str] | None = None,
        pre_dropped_rows: int = 0,
        _prevalidated_counts: tuple[int, int] | None = None,
        _source_fingerprint: Any = None,
        _pass1_only: bool = False,
    ) -> dict[str, Any]:
        """Execute the 2-pass DuckDB + Rust ArrowTiles v0.1 pipeline."""
        if self.con is None:
            raise RuntimeError("ArrowTilesBuilder connection is already closed")

        if id_col is None or not str(id_col).strip():
            raise ValueError(
                "ArrowTiles v0.1 requires an explicit deterministic integer 'id_col' "
                "(e.g. id_col='row_id') when calling ArrowTilesBuilder.build()."
            )

        if sampling not in ("even_coverage", "proportional"):
            raise ValueError(
                f"Unsupported sampling mode '{sampling}': expected 'even_coverage' or 'proportional'"
            )

        tile_capacity = max(1, int(max_capacity))
        configured_max_tile_rows = (
            max(tile_capacity, int(max_tile_rows))
            if max_tile_rows is not None
            else max(tile_capacity, DEFAULT_MAX_TILE_ROWS)
        )
        nominal_max_zoom = int(max_zoom)
        if not (0 <= nominal_max_zoom <= 20):
            raise ValueError(f"max_zoom must be between 0 and 20, got {nominal_max_zoom}")

        if grid_size is None:
            computed_grid = math.isqrt(tile_capacity)
            eff_grid_size = max(16, min(512, computed_grid))
        else:
            eff_grid_size = int(grid_size)
            if not (16 <= eff_grid_size <= 512):
                raise ValueError(f"grid_size must be between 16 and 512, got {eff_grid_size}")

        # Strictly validate custom_metadata upfront before Pass 1 spends compute
        normalized_custom_metadata: str | None = None
        if custom_metadata is not None and custom_metadata.strip():
            parsed_custom = parse_strict_json_object(custom_metadata, label="custom_metadata")
            colliding_keys = sorted(RESERVED_METADATA_KEYS.intersection(parsed_custom.keys()))
            if colliding_keys:
                raise ValueError(
                    f"custom_metadata contains reserved ArrowTiles key(s): {', '.join(colliding_keys)}"
                )
            normalized_custom_metadata = json.dumps(
                parsed_custom, allow_nan=False, sort_keys=True
            )

        core = _load_core_module()
        core.init_threadpool(self.rayon_threads)

        q = self._quote_ident
        desc_rows = self.con.execute(
            f"DESCRIBE SELECT * FROM ({input_query}) AS __at_in"
        ).fetchall()
        schema_map: dict[str, str] = {str(r[0]): str(r[1]) for r in desc_rows}
        col_order: list[str] = [str(r[0]) for r in desc_rows]

        if x_col not in schema_map:
            raise ValueError(f"x_col '{x_col}' not found in input query columns: {col_order}")
        if y_col not in schema_map:
            raise ValueError(f"y_col '{y_col}' not found in input query columns: {col_order}")
        if id_col not in schema_map:
            raise ValueError(f"id_col '{id_col}' not found in input query columns: {col_order}")
        if self._base_duckdb_type(schema_map[id_col]) not in DUCKDB_INTEGER_TYPES:
            raise ValueError(
                f"id_col '{id_col}' must have an integer type, got '{schema_map[id_col]}'"
            )
        if sort_col is not None and sort_col not in schema_map:
            raise ValueError(
                f"sort_col '{sort_col}' not found in input query columns: {col_order}"
            )

        internal_xy = {x_col, y_col}
        for col in col_order:
            if col in internal_xy or col == id_col:
                continue
            if col in RESERVED_COLUMN_NAMES or col.startswith("__at_"):
                raise ValueError(
                    f"Input column '{col}' collides with reserved ArrowTiles column name"
                )

        cat_cols = dict(categorical_columns or {})
        cat_lookup_tables: dict[str, tuple[str, str]] = {}
        for idx, (cat_col, categories) in enumerate(cat_cols.items()):
            if cat_col not in schema_map:
                raise ValueError(f"Categorical column '{cat_col}' not found in input query")
            if len(categories) == 0:
                raise ValueError(f"Categorical column '{cat_col}' must have at least 1 category")
            if len(categories) > MAX_CATEGORIES_CAP:
                raise ValueError(
                    f"Categorical column '{cat_col}' has {len(categories)} categories "
                    f"(max supported in v0.1 is {MAX_CATEGORIES_CAP})"
                )
            code_sql_type = "UTINYINT" if len(categories) <= 256 else "USMALLINT"
            pa_code_type = pa.uint8() if len(categories) <= 256 else pa.uint16()
            tbl_name = f"__at_cat_lookup_{idx}"
            lookup_arrow = pa.table(
                {
                    "label": pa.array([str(v) for v in categories], type=pa.string()),
                    "code": pa.array(list(range(len(categories))), type=pa_code_type),
                }
            )
            self.con.execute(f"DROP TABLE IF EXISTS {q(tbl_name)}")
            self.con.register("__at_tmp_cat_arrow", lookup_arrow)
            self.con.execute(
                f"CREATE TEMP TABLE {q(tbl_name)} AS "
                f"SELECT label, CAST(code AS {code_sql_type}) AS code FROM __at_tmp_cat_arrow"
            )
            self.con.unregister("__at_tmp_cat_arrow")
            cat_lookup_tables[cat_col] = (tbl_name, code_sql_type)

        q_x = q(x_col)
        q_y = q(y_col)
        q_id = q(id_col)

        sort_dir_clean = "DESC" if str(sort_dir).upper() == "DESC" else "ASC"
        if sort_col is not None:
            q_sort_src = f"src.{q(sort_col)}"
            if self._base_duckdb_type(schema_map[sort_col]) in DUCKDB_NUMERIC_TYPES:
                sort_key_expr = (
                    f"CASE WHEN {q_sort_src} IS NULL OR isnan(CAST({q_sort_src} AS DOUBLE)) "
                    f"THEN NULL ELSE {q_sort_src} END"
                )
            else:
                sort_key_expr = q_sort_src
            priority_meta: dict[str, Any] = {
                "kind": "column",
                "column": sort_col,
                "order": sort_dir_clean.lower(),
            }
            order_dir_pass = f"{sort_dir_clean} NULLS LAST"
        else:
            sort_key_expr = _duckdb_splitmix64_sql(f"src.{q_id}", int(seed))
            priority_meta = {"kind": "random", "seed": int(seed)}
            order_dir_pass = "ASC NULLS LAST"

        select_exprs: list[str] = [f"CAST(src.{q_id} AS UBIGINT) AS \"row_id\""]
        join_clauses: list[str] = []
        retained_col_types: list[tuple[str, str]] = []
        source_col_types_for_stats: list[tuple[str, str]] = []

        for join_idx, col in enumerate(col_order):
            if col == id_col or col in internal_xy:
                continue
            qc = q(col)
            source_col_types_for_stats.append((col, schema_map[col]))
            if col in cat_lookup_tables:
                tbl_name, code_sql_type = cat_lookup_tables[col]
                alias = f"__at_cj_{join_idx}"
                join_clauses.append(
                    f"LEFT JOIN {q(tbl_name)} AS {alias} ON CAST(src.{qc} AS VARCHAR) = {alias}.label"
                )
                select_exprs.append(f"{alias}.code AS {qc}")
                retained_col_types.append((col, code_sql_type))
            else:
                select_exprs.append(f"src.{qc} AS {qc}")
                retained_col_types.append((col, schema_map[col]))

        select_exprs.append(f"CAST(src.{q_x} AS DOUBLE) AS \"__at_x_norm\"")
        select_exprs.append(f"CAST(src.{q_y} AS DOUBLE) AS \"__at_y_norm\"")
        select_exprs.append(f"{sort_key_expr} AS \"__at_sort_key\"")

        finite_pred = (
            f"src.{q_x} IS NOT NULL AND src.{q_y} IS NOT NULL "
            f"AND isfinite(CAST(src.{q_x} AS DOUBLE)) AND isfinite(CAST(src.{q_y} AS DOUBLE))"
        )

        # Single-pass preflight ONLY when not already computed by build_generic / build_gaia
        if _prevalidated_counts is not None and stats is not None:
            _valid_in, total_dropped_rows = int(_prevalidated_counts[0]), int(_prevalidated_counts[1])
            computed_stats = stats
        else:
            _valid_in, query_dropped, direct_stats = self._single_pass_preflight_direct(
                input_query=input_query,
                x_col=x_col,
                y_col=y_col,
                id_col=id_col,
                retained_col_types=source_col_types_for_stats,
                categorical_columns=cat_cols,
                need_stats=(stats is None),
            )
            total_dropped_rows = int(pre_dropped_rows) + query_dropped
            computed_stats = stats if stats is not None else direct_stats

        valid_projected_sql = f"""
            SELECT {', '.join(select_exprs)}
            FROM ({input_query}) AS src
            {' '.join(join_clauses)}
            WHERE {finite_pred}
        """

        bounds_meta = bounds or {
            "min_x": 0.0,
            "max_x": 1.0,
            "min_y": 0.0,
            "max_y": 1.0,
        }
        for bk in ("min_x", "max_x", "min_y", "max_y"):
            if bk not in bounds_meta or not math.isfinite(float(bounds_meta[bk])):
                raise ValueError(f"bounds['{bk}'] must be a finite float")

        dropped_cols_list = [str(c) for c in (dropped_columns or [])]

        # Compute full SHA-256 build fingerprint for --resume safety
        fingerprint_payload = {
            "source": _source_fingerprint if _source_fingerprint is not None else {"query": input_query},
            "nominal_max_zoom": int(nominal_max_zoom),
            "tile_capacity": int(tile_capacity),
            "configured_max_tile_rows": int(configured_max_tile_rows),
            "sampling": sampling,
            "grid_size": int(eff_grid_size),
            "priority": priority_meta,
            "id_col": id_col,
            "retained_columns": [c for c, _ in retained_col_types],
            "categorical_columns": cat_cols,
            "dropped_columns": dropped_cols_list,
            "allow_oversize_leaves": bool(allow_oversize_leaves),
        }
        manifest_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, allow_nan=False).encode("utf-8")
        ).hexdigest()

        t_global = time.time()
        output_path_str = str(output_path)
        temp_partition_dir = os.path.join(self.temp_dir, "partitions")
        manifest_path = os.path.join(temp_partition_dir, "manifest.json")
        os.makedirs(temp_partition_dir, exist_ok=True)

        def _get_z(filepath: str) -> int:
            basename = os.path.basename(filepath)
            try:
                return int(basename.split("_")[1].split(".")[0])
            except (IndexError, ValueError):
                return 0

        try:
            # ==========================================
            # PASS 1: DuckDB Priority Sort -> Rust 2-Stage Bucketer
            # ==========================================
            resumed_pass1 = False
            actual_max_z = 0
            observed_z20 = 0
            bucketed_rows = 0

            existing_partitions = glob.glob(os.path.join(temp_partition_dir, "z_*.parquet"))
            if resume and existing_partitions and os.path.isfile(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        manifest = json.load(mf)
                except Exception:
                    manifest = {}

                expected_deepest = os.path.join(
                    temp_partition_dir, f"z_{int(manifest.get('actual_max_z', -1))}.parquet"
                )
                if (
                    manifest.get("format") == "arrowtiles-partitions-v2"
                    and manifest.get("fingerprint") == manifest_fingerprint
                    and os.path.isfile(expected_deepest)
                ):
                    actual_max_z = int(manifest["actual_max_z"])
                    observed_z20 = int(manifest["observed_z20"])
                    bucketed_rows = int(manifest["total_rows"])
                    total_dropped_rows = int(manifest.get("dropped_rows", total_dropped_rows))
                    resumed_pass1 = True
                else:
                    print(
                        "[ArrowTiles] --resume manifest fingerprint mismatch or incomplete partitions; "
                        "invalidating stale partitions and re-running Pass 1.",
                        flush=True,
                    )

            if not resumed_pass1:
                for stale_file in glob.glob(os.path.join(temp_partition_dir, "*")):
                    if os.path.isfile(stale_file):
                        os.remove(stale_file)

                query_pass1 = f"""
                    SELECT *
                    FROM ({valid_projected_sql}) AS __at_p1
                    ORDER BY "__at_sort_key" {order_dir_pass}, "row_id" ASC
                """
                reader_pass1 = self.con.execute(query_pass1).to_arrow_reader(100_000)

                c_stream_pass1 = pc.ffi.new("struct ArrowArrayStream*")
                ptr_pass1 = int(pc.ffi.cast("uintptr_t", c_stream_pass1))
                reader_pass1._export_to_c(ptr_pass1)

                actual_max_z, observed_z20, bucketed_rows = core.run_bucketer(
                    ptr_pass1,
                    temp_partition_dir,
                    int(nominal_max_zoom),
                    int(tile_capacity),
                    int(configured_max_tile_rows),
                    int(eff_grid_size),
                    sampling,
                    bool(allow_oversize_leaves),
                    "__at_x_norm",
                    "__at_y_norm",
                    int(z_buffer_limit),
                )

                manifest_payload = {
                    "format": "arrowtiles-partitions-v2",
                    "fingerprint": manifest_fingerprint,
                    "actual_max_z": int(actual_max_z),
                    "observed_z20": int(observed_z20),
                    "total_rows": int(bucketed_rows),
                    "dropped_rows": int(total_dropped_rows),
                    "dropped_columns": dropped_cols_list,
                    "nominal_max_zoom": int(nominal_max_zoom),
                    "tile_capacity": int(tile_capacity),
                    "max_tile_rows": int(configured_max_tile_rows),
                    "sampling": sampling,
                    "grid_size": int(eff_grid_size),
                }
                with open(manifest_path, "w", encoding="utf-8") as mf:
                    json.dump(manifest_payload, mf, allow_nan=False, sort_keys=True, indent=2)

            if _pass1_only:
                for tbl_name, _ in cat_lookup_tables.values():
                    self.con.execute(f"DROP TABLE IF EXISTS {q(tbl_name)}")
                return {
                    "output_path": output_path_str,
                    "total_rows": int(bucketed_rows),
                    "dropped_rows": int(total_dropped_rows),
                    "dropped_columns": dropped_cols_list,
                    "actual_max_zoom": int(actual_max_z),
                    "resumed_pass1": resumed_pass1,
                    "pass1_only": True,
                    "fingerprint": manifest_fingerprint,
                    "elapsed_seconds": time.time() - t_global,
                }

            # ==========================================
            # PASS 2: DuckDB Hilbert Sort -> Rust Packer
            # ==========================================
            partitions = sorted(
                glob.glob(os.path.join(temp_partition_dir, "z_*.parquet")),
                key=_get_z,
            )
            if not partitions:
                raise RuntimeError("No partition files were produced in Pass 1")

            effective_max_tile_rows = (
                max(configured_max_tile_rows, int(observed_z20))
                if allow_oversize_leaves
                else configured_max_tile_rows
            )

            spec_metadata: dict[str, Any] = {
                "format": SPEC_FORMAT,
                "version": SPEC_VERSION,
                "bounds": {
                    "min_x": float(bounds_meta["min_x"]),
                    "max_x": float(bounds_meta["max_x"]),
                    "min_y": float(bounds_meta["min_y"]),
                    "max_y": float(bounds_meta["max_y"]),
                },
                "priority": priority_meta,
                "sampling": sampling,
                "grid_size": int(eff_grid_size),
                "nominal_max_zoom": int(nominal_max_zoom),
                "tile_capacity": int(tile_capacity),
                "max_tile_rows": int(effective_max_tile_rows),
                "total_rows": int(bucketed_rows),
                "dropped_rows": int(total_dropped_rows),
                "dropped_columns": dropped_cols_list,
                "stats": computed_stats,
            }
            if view:
                spec_metadata["view"] = view

            spec_metadata_json = json.dumps(spec_metadata, allow_nan=False, sort_keys=True)

            first_part_sql = self._sql_str(Path(partitions[0]).as_posix())
            first_part_schema = (
                self.con.execute(f"SELECT * FROM read_parquet({first_part_sql}) LIMIT 0")
                .to_arrow_table()
                .schema
            )
            empty_table = pa.Table.from_arrays(
                [pa.array([], type=t) for t in first_part_schema.types],
                schema=first_part_schema,
            )
            dummy_reader = pa.RecordBatchReader.from_batches(
                first_part_schema, empty_table.to_batches()
            )

            c_schema_stream = pc.ffi.new("struct ArrowArrayStream*")
            ptr_schema = int(pc.ffi.cast("uintptr_t", c_schema_stream))
            dummy_reader._export_to_c(ptr_schema)

            packer = core.ArrowTilesPacker(
                output_path_str,
                ptr_schema,
                int(chunk_buffer_limit),
                int(actual_max_z),
                int(effective_max_tile_rows),
                spec_metadata_json,
                normalized_custom_metadata,
            )

            part_iter = (
                tqdm(partitions, desc="Packing Tiles") if self.show_progress else partitions
            )
            for part in part_iter:
                part_sql = self._sql_str(Path(part).as_posix())
                query_pass2 = f"""
                    SELECT *
                    FROM read_parquet({part_sql})
                    ORDER BY final_tile_id ASC, "__at_sort_key" {order_dir_pass}, "row_id" ASC
                """
                reader_pass2 = self.con.execute(query_pass2).to_arrow_reader(100_000)

                c_stream_pass2 = pc.ffi.new("struct ArrowArrayStream*")
                ptr_pass2 = int(pc.ffi.cast("uintptr_t", c_stream_pass2))
                reader_pass2._export_to_c(ptr_pass2)

                packer.process_batch(ptr_pass2)

            (
                packed_rows,
                observed_max_rows,
                max_compressed_bytes,
                overview_z0_2_bytes,
            ) = packer.finalize()

            if int(overview_z0_2_bytes) > OVERVIEW_Z0_2_WARN_BYTES:
                ov_mib = int(overview_z0_2_bytes) / (1024.0 * 1024.0)
                print(
                    f"[ArrowTiles] Warning: Z=0..2 overview tiles total {ov_mib:.2f} MiB "
                    f"(> 10.0 MiB). On wide tables, pass --columns (or columns=[...]) to retain "
                    f"only active visual columns for faster initial streaming.",
                    flush=True,
                )

            for tbl_name, _ in cat_lookup_tables.values():
                self.con.execute(f"DROP TABLE IF EXISTS {q(tbl_name)}")

            try:
                if os.path.exists(temp_partition_dir):
                    shutil.rmtree(temp_partition_dir)
            except OSError:
                pass

            return {
                "output_path": output_path_str,
                "total_rows": int(packed_rows),
                "dropped_rows": int(total_dropped_rows),
                "dropped_columns": dropped_cols_list,
                "actual_max_zoom": int(actual_max_z),
                "observed_max_tile_rows": int(observed_max_rows),
                "max_compressed_tile_bytes": int(max_compressed_bytes),
                "overview_z0_2_bytes": int(overview_z0_2_bytes),
                "resumed_pass1": resumed_pass1,
                "fingerprint": manifest_fingerprint,
                "elapsed_seconds": time.time() - t_global,
            }
        except Exception:
            raise


def _prepare_parquet_files_and_offsets(
    con: duckdb.DuckDBPyConnection,
    input_parquet: str | os.PathLike[str] | list[str],
    row_limit: int | None = None,
) -> tuple[list[str], int, str]:
    """Resolve Parquet files deterministically, sort lexicographically, and register base offsets."""
    src_expr = ArrowTilesBuilder._sql_path_expr(input_parquet)
    meta_rows = con.execute(
        f"SELECT file_name, CAST(num_rows AS BIGINT) FROM parquet_file_metadata({src_expr})"
    ).fetchall()
    if not meta_rows:
        raise ValueError(f"No Parquet files matched '{input_parquet}'")

    normalized_files: list[tuple[str, int]] = []
    for raw_name, nrows in meta_rows:
        posix_path = Path(str(raw_name)).resolve().as_posix()
        normalized_files.append((posix_path, int(nrows or 0)))
    normalized_files.sort(key=lambda item: item[0])

    sorted_paths: list[str] = []
    offset_paths: list[str] = []
    base_offsets: list[int] = []
    running_offset = 0
    for posix_path, nrows in normalized_files:
        if row_limit is not None and running_offset >= row_limit:
            break
        sorted_paths.append(posix_path)
        offset_paths.append(posix_path)
        base_offsets.append(running_offset)
        running_offset += nrows

    total_input_rows = min(running_offset, row_limit) if row_limit is not None else running_offset

    offsets_table = pa.table(
        {
            "file_path": pa.array(offset_paths, type=pa.string()),
            "base_offset": pa.array(base_offsets, type=pa.uint64()),
        }
    )
    con.execute('DROP TABLE IF EXISTS "__at_file_offsets"')
    con.register("__at_tmp_offsets", offsets_table)
    con.execute('CREATE TEMP TABLE "__at_file_offsets" AS SELECT * FROM __at_tmp_offsets')
    con.unregister("__at_tmp_offsets")

    files_sql = ArrowTilesBuilder._sql_path_expr(sorted_paths)
    return sorted_paths, total_input_rows, files_sql


def build_generic(
    input_parquet: str | os.PathLike[str] | list[str],
    output_path: str | os.PathLike[str],
    x_col: str,
    y_col: str,
    sort_col: str | None = None,
    sort_dir: str = "ASC",
    id_col: str | None = None,
    columns: list[str] | None = None,
    categorical_cols: list[str] | None = None,
    keep_source_xy: bool = False,
    max_capacity: int = DEFAULT_TILE_CAPACITY,
    max_zoom: int = DEFAULT_NOMINAL_MAX_ZOOM,
    max_tile_rows: int | None = None,
    sampling: str = "proportional",
    grid_size: int | None = None,
    seed: int = DEFAULT_RANDOM_SEED,
    max_categories: int = DEFAULT_AUTO_MAX_CATEGORIES,
    allow_oversize_leaves: bool = False,
    row_limit: int | None = None,
    resume: bool = False,
    memory_limit: str = "40GB",
    temp_dir: str | os.PathLike[str] | None = None,
    threads: int | None = None,
    custom_config: str | None = None,
    show_progress: bool = True,
    _pass1_only: bool = False,
) -> dict[str, Any]:
    """Build a spec-compliant v0.1 .arrowtiles archive from Parquet file(s) or glob."""
    if not (1 <= int(max_categories) <= MAX_CATEGORIES_CAP):
        raise ValueError(f"max_categories must be in 1..{MAX_CATEGORIES_CAP}, got {max_categories}")

    with ArrowTilesBuilder(
        memory_limit=memory_limit,
        temp_dir=temp_dir,
        threads=threads,
        show_progress=show_progress,
    ) as builder:
        assert builder.con is not None
        con = builder.con
        q = ArrowTilesBuilder._quote_ident

        sorted_paths, _meta_rows, files_sql = _prepare_parquet_files_and_offsets(
            con, input_parquet, row_limit=row_limit
        )
        source_fp = {
            "files": _compute_files_fingerprint(sorted_paths),
            "row_limit": int(row_limit) if row_limit is not None else None,
            "x_col": x_col,
            "y_col": y_col,
            "keep_source_xy": bool(keep_source_xy),
            "max_categories": int(max_categories),
            "categorical_cols": sorted(categorical_cols) if categorical_cols else [],
        }

        schema_rows = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet({files_sql})"
        ).fetchall()
        all_cols = [str(r[0]) for r in schema_rows]
        col_type_map = {str(r[0]): str(r[1]) for r in schema_rows}

        if x_col not in col_type_map:
            raise ValueError(f"x_col '{x_col}' not found in Parquet columns: {all_cols}")
        if y_col not in col_type_map:
            raise ValueError(f"y_col '{y_col}' not found in Parquet columns: {all_cols}")
        if sort_col is not None and sort_col not in col_type_map:
            raise ValueError(f"sort_col '{sort_col}' not found in Parquet columns: {all_cols}")
        if id_col is not None and id_col not in col_type_map:
            raise ValueError(f"id_col '{id_col}' not found in Parquet columns: {all_cols}")

        explicit_cols_set: set[str] | None = None
        if columns is not None:
            missing_req = [c for c in columns if c not in col_type_map]
            if missing_req:
                raise ValueError(f"Requested column(s) not found in Parquet schema: {missing_req}")
            explicit_cols_set = set(columns)
            payload_cols = list(dict.fromkeys(columns))
            if sort_col is not None and sort_col not in payload_cols and sort_col not in (x_col, y_col, id_col):
                payload_cols.append(sort_col)
        else:
            payload_cols = [
                c
                for c in all_cols
                if c != id_col and (keep_source_xy or c not in (x_col, y_col))
            ]

        if keep_source_xy:
            for c in (x_col, y_col):
                if c != id_col and c not in payload_cols:
                    payload_cols.append(c)
        else:
            payload_cols = [
                c for c in payload_cols if c not in (x_col, y_col) or c == sort_col
            ]
            if sort_col in (x_col, y_col) and sort_col != id_col and sort_col not in payload_cols:
                payload_cols.append(sort_col)

        for c in payload_cols:
            if c in RESERVED_COLUMN_NAMES or c.startswith("__at_"):
                raise ValueError(
                    f"Input column '{c}' collides with reserved ArrowTiles column name"
                )

        needed_src_cols = list(
            dict.fromkeys(
                [
                    *payload_cols,
                    x_col,
                    y_col,
                    *([id_col] if id_col else []),
                    *([sort_col] if sort_col else []),
                ]
            )
        )
        src_proj = ", ".join(f"src.{q(c)}" for c in needed_src_cols)
        if id_col is not None:
            row_id_expr = f"src.{q(id_col)} AS \"__at_row_id\""
            join_offsets_sql = ""
            read_pq_sql = f"read_parquet({files_sql})"
        else:
            row_id_expr = 'CAST(off.base_offset + src.file_row_number AS UBIGINT) AS "__at_row_id"'
            join_offsets_sql = (
                "INNER JOIN \"__at_file_offsets\" AS off "
                "ON replace(src.filename, '\\', '/') = off.file_path"
            )
            read_pq_sql = f"read_parquet({files_sql}, filename=true, file_row_number=true)"

        limit_clause = (
            f'ORDER BY "__at_row_id" ASC LIMIT {int(row_limit)}'
            if row_limit is not None
            else ""
        )
        raw_source_sql = f"""
            SELECT {row_id_expr}, {src_proj}
            FROM {read_pq_sql} AS src
            {join_offsets_sql}
            {limit_clause}
        """

        q_x = q(x_col)
        q_y = q(y_col)
        finite_xy = (
            f"{q_x} IS NOT NULL AND {q_y} IS NOT NULL "
            f"AND isfinite(CAST({q_x} AS DOUBLE)) AND isfinite(CAST({q_y} AS DOUBLE))"
        )

        explicit_cat_set = set(categorical_cols or [])
        missing_cats = [c for c in explicit_cat_set if c not in col_type_map]
        if missing_cats:
            raise ValueError(f"categorical_cols not found in Parquet schema: {sorted(missing_cats)}")

        # Single-pass aggregation over raw_source_sql: counts, id_col uniqueness, bounds, numeric stats, string/explicit-cat distincts
        numeric_payload = [
            c
            for c in payload_cols
            if c not in explicit_cat_set
            and ArrowTilesBuilder._base_duckdb_type(col_type_map[c]) in DUCKDB_NUMERIC_TYPES
        ]
        string_payload = [
            c
            for c in payload_cols
            if c in explicit_cat_set
            or ArrowTilesBuilder._base_duckdb_type(col_type_map[c]) in ("VARCHAR", "STRING", "TEXT")
        ]

        agg_items = [
            "COUNT(*) AS input_rows",
            f"COUNT(*) FILTER (WHERE {finite_xy}) AS valid_rows",
            f"MIN(CAST({q_x} AS DOUBLE)) FILTER (WHERE {finite_xy}) AS min_x",
            f"MAX(CAST({q_x} AS DOUBLE)) FILTER (WHERE {finite_xy}) AS max_x",
            f"MIN(CAST({q_y} AS DOUBLE)) FILTER (WHERE {finite_xy}) AS min_y",
            f"MAX(CAST({q_y} AS DOUBLE)) FILTER (WHERE {finite_xy}) AS max_y",
        ]
        if id_col is not None:
            agg_items.extend(
                [
                    'COUNT("__at_row_id") AS id_non_null',
                    'COUNT(DISTINCT "__at_row_id") AS id_distinct',
                    'COUNT(*) FILTER (WHERE "__at_row_id" < 0) AS id_neg',
                    'MAX(CAST("__at_row_id" AS UBIGINT)) FILTER (WHERE "__at_row_id" IS NOT NULL AND "__at_row_id" >= 0) AS id_max',
                ]
            )
        for col in numeric_payload:
            qc = q(col)
            agg_items.append(
                f"MIN(CAST({qc} AS DOUBLE)) FILTER (WHERE {finite_xy} AND {qc} IS NOT NULL AND isfinite(CAST({qc} AS DOUBLE)))"
            )
            agg_items.append(
                f"MAX(CAST({qc} AS DOUBLE)) FILTER (WHERE {finite_xy} AND {qc} IS NOT NULL AND isfinite(CAST({qc} AS DOUBLE)))"
            )
            agg_items.append(
                f"COUNT(*) FILTER (WHERE {finite_xy} AND {qc} IS NULL)"
            )
        for col in string_payload:
            qc = q(col)
            agg_items.append(
                f"COUNT(DISTINCT {qc}) FILTER (WHERE {finite_xy} AND {qc} IS NOT NULL)"
            )
            agg_items.append(
                f"COUNT(*) FILTER (WHERE {finite_xy} AND {qc} IS NULL)"
            )

        agg_row = con.execute(
            f"SELECT {', '.join(agg_items)} FROM ({raw_source_sql}) AS raw_src"
        ).fetchone()
        assert agg_row is not None

        input_rows = int(agg_row[0] or 0)
        valid_rows = int(agg_row[1] or 0)
        cursor = 6
        if id_col is not None:
            id_non_null = int(agg_row[cursor] or 0)
            id_distinct = int(agg_row[cursor + 1] or 0)
            id_neg = int(agg_row[cursor + 2] or 0)
            id_max = int(agg_row[cursor + 3] or 0)
            cursor += 4
            if id_non_null != input_rows:
                raise ValueError(f"id_col '{id_col}' contains NULL values")
            if id_neg > 0:
                raise ValueError(f"id_col '{id_col}' contains negative values")
            if id_distinct != input_rows:
                raise ValueError(
                    f"id_col '{id_col}' is not unique ({id_distinct} distinct values across {input_rows} rows)"
                )
            if id_max > JS_MAX_SAFE_INTEGER:
                print(
                    f"[ArrowTiles] Warning: id_col '{id_col}' has values > 2^53 - 1 (max={id_max}); "
                    f"stored losslessly as UInt64, but JavaScript consumers should inspect rowIdBigInt for exact precision.",
                    flush=True,
                )

        if valid_rows == 0:
            raise ValueError("Input Parquet contains 0 rows with finite (x, y) coordinates")
        dropped_rows = input_rows - valid_rows

        min_x = float(agg_row[2])
        max_x = float(agg_row[3])
        min_y = float(agg_row[4])
        max_y = float(agg_row[5])
        span_x = (max_x - min_x) if (max_x - min_x) != 0.0 else 1.0
        span_y = (max_y - min_y) if (max_y - min_y) != 0.0 else 1.0

        bounds_dict = {
            "min_x": min_x,
            "max_x": max_x,
            "min_y": min_y,
            "max_y": max_y,
        }

        stats_dict: dict[str, dict[str, Any]] = {}
        for col in numeric_payload:
            rmin, rmax, rnull = agg_row[cursor], agg_row[cursor + 1], agg_row[cursor + 2]
            cursor += 3
            stats_dict[col] = {
                "type": "numeric",
                "min": float(rmin) if rmin is not None and math.isfinite(float(rmin)) else 0.0,
                "max": float(rmax) if rmax is not None and math.isfinite(float(rmax)) else 0.0,
                "null_count": int(rnull or 0),
            }

        categorical_columns: dict[str, list[str]] = {}
        dropped_columns: list[str] = []
        for col in string_payload:
            dist_cnt = int(agg_row[cursor] or 0)
            null_cnt = int(agg_row[cursor + 1] or 0)
            cursor += 2
            if 0 < dist_cnt <= int(max_categories):
                qc = q(col)
                dist_rows = con.execute(
                    f"""
                    SELECT DISTINCT {qc}
                    FROM ({raw_source_sql}) AS raw_src
                    WHERE {finite_xy} AND {qc} IS NOT NULL
                    ORDER BY {qc} ASC
                    """
                ).fetchall()
                vals = [str(v[0]) for v in dist_rows]
                categorical_columns[col] = vals
                stats_dict[col] = {
                    "type": "categorical",
                    "categories": vals,
                    "null_count": null_cnt,
                }
            elif dist_cnt > int(max_categories):
                # D7a: drop unrequested high-cardinality free-text columns by default unless named in columns=
                explicitly_requested = (
                    explicit_cols_set is not None and col in explicit_cols_set
                ) or (col == sort_col)
                if not explicitly_requested:
                    payload_cols = [c for c in payload_cols if c != col]
                    dropped_columns.append(col)
                    print(
                        f"[ArrowTiles] Dropping high-cardinality string column '{col}' "
                        f"({dist_cnt:,} distinct values > max_categories={max_categories}); "
                        f"pass --columns to retain.",
                        flush=True,
                    )

        default_visual_field = (
            sort_col
            if (sort_col is not None and sort_col in payload_cols)
            else (
                numeric_payload[0]
                if numeric_payload
                else (payload_cols[0] if payload_cols else "x_u16")
            )
        )
        field_stats = stats_dict.get(default_visual_field, {})
        c_min = float(field_stats.get("min", 0.0))
        c_max = float(field_stats.get("max", 100.0))

        view_dict: dict[str, Any] = {
            "mode": "Chart Mode",
            "colorField": default_visual_field,
            "colorMin": c_min,
            "colorMax": c_max,
            "sizeField": default_visual_field,
            "sizeMin": c_min,
            "sizeMax": c_max,
            "colorScale": "viridis",
            "preserveAspect": True,
        }

        extra_custom_json: str | None = None
        if custom_config is not None and custom_config.strip():
            parsed_cfg = parse_strict_json_object(custom_config, label="custom_config")
            colliding = sorted(RESERVED_METADATA_KEYS.intersection(parsed_cfg.keys()))
            if colliding:
                raise ValueError(
                    f"custom_config contains reserved ArrowTiles key(s): {', '.join(colliding)}"
                )
            for vk in (
                "mode",
                "colorField",
                "colorMin",
                "colorMax",
                "sizeField",
                "sizeMin",
                "sizeMax",
                "colorScale",
                "preserveAspect",
            ):
                if vk in parsed_cfg:
                    view_dict[vk] = parsed_cfg[vk]
            extra_custom_json = json.dumps(parsed_cfg, allow_nan=False, sort_keys=True)

        retained_selects = ['"__at_row_id" AS "row_id"', *(q(col) for col in payload_cols)]

        generic_query = f"""
            SELECT
                {', '.join(retained_selects)},
                LEAST(GREATEST((CAST({q_x} AS DOUBLE) - ({min_x!r})) / ({span_x!r}), 0.0), 1.0) AS "__at_in_x",
                LEAST(GREATEST((({max_y!r}) - CAST({q_y} AS DOUBLE)) / ({span_y!r}), 0.0), 1.0) AS "__at_in_y"
            FROM ({raw_source_sql}) AS raw_src
            WHERE {finite_xy}
        """

        return builder.build(
            input_query=generic_query,
            output_path=output_path,
            sort_col=sort_col,
            x_col="__at_in_x",
            y_col="__at_in_y",
            sort_dir=sort_dir,
            max_capacity=max_capacity,
            max_zoom=max_zoom,
            max_tile_rows=max_tile_rows,
            sampling=sampling,
            grid_size=grid_size,
            seed=seed,
            id_col="row_id",
            allow_oversize_leaves=allow_oversize_leaves,
            resume=resume,
            custom_metadata=extra_custom_json,
            categorical_columns=categorical_columns,
            bounds=bounds_dict,
            stats=stats_dict,
            view=view_dict,
            dropped_columns=dropped_columns,
            pre_dropped_rows=dropped_rows,
            _prevalidated_counts=(valid_rows, dropped_rows),
            _source_fingerprint=source_fp,
            _pass1_only=_pass1_only,
        )


def build_gaia(
    input_parquet: str | os.PathLike[str] | list[str],
    output_path: str | os.PathLike[str],
    row_limit: int | None = None,
    max_capacity: int = DEFAULT_GAIA_TILE_CAPACITY,
    max_zoom: int = DEFAULT_NOMINAL_MAX_ZOOM,
    max_tile_rows: int | None = None,
    sampling: str = "even_coverage",
    grid_size: int | None = None,
    allow_oversize_leaves: bool = False,
    custom_config: str | None = None,
    resume: bool = False,
    memory_limit: str = "40GB",
    temp_dir: str | os.PathLike[str] | None = None,
    threads: int | None = None,
    show_progress: bool = True,
    _pass1_only: bool = False,
) -> dict[str, Any]:
    """Build a spec-compliant v0.1 Gaia Hammer-projection .arrowtiles archive (`phot_g_mean_mag ASC`)."""
    hammer_half_w = 2.0 * math.sqrt(2.0)  # 2.8284271247461903
    hammer_half_h = math.sqrt(2.0)  # 1.4142135623730951

    with ArrowTilesBuilder(
        memory_limit=memory_limit,
        temp_dir=temp_dir,
        threads=threads,
        show_progress=show_progress,
    ) as builder:
        assert builder.con is not None
        con = builder.con
        q = builder._quote_ident

        sorted_paths, _meta_rows, files_sql = _prepare_parquet_files_and_offsets(
            con, input_parquet, row_limit=row_limit
        )
        source_fp = {
            "preset": "gaia",
            "files": _compute_files_fingerprint(sorted_paths),
            "row_limit": int(row_limit) if row_limit is not None else None,
        }

        # Inspect input Parquet columns so both raw ESA Gaia DR3 names (phot_g_mean_mag, bp_rp)
        # and local s3_cache names (magnitude, bv) are accepted seamlessly.
        src_desc = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet({files_sql})"
        ).fetchall()
        src_cols = {str(r[0]) for r in src_desc}

        if "ra" not in src_cols or "dec" not in src_cols:
            raise ValueError(
                f"Gaia preset requires 'ra' and 'dec' columns in input Parquet; found {sorted(src_cols)}"
            )

        if "phot_g_mean_mag" in src_cols:
            mag_src_expr = f"src.{q('phot_g_mean_mag')}"
        elif "magnitude" in src_cols:
            mag_src_expr = f"src.{q('magnitude')}"
        elif "abs_m" in src_cols:
            mag_src_expr = f"src.{q('abs_m')}"
        else:
            raise ValueError(
                "Gaia preset requires a brightness column ('phot_g_mean_mag' or 'magnitude') "
                f"in input Parquet; found {sorted(src_cols)}"
            )

        if "bp_rp" in src_cols:
            bprp_src_expr = f"src.{q('bp_rp')}"
        elif "bv" in src_cols:
            bprp_src_expr = f"src.{q('bv')}"
        else:
            bprp_src_expr = "CAST(NULL AS FLOAT)"

        opt_exprs: dict[str, str] = {}
        for opt_col in ("parallax", "pmra", "pmdec", "radial_velocity", "teff_gspphot"):
            opt_exprs[opt_col] = (
                f"src.{q(opt_col)}" if opt_col in src_cols else "CAST(NULL AS FLOAT)"
            )

        limit_clause = (
            f'ORDER BY "row_id" ASC LIMIT {int(row_limit)}'
            if row_limit is not None
            else ""
        )
        raw_gaia_sql = f"""
            SELECT
                CAST(off.base_offset + src.file_row_number AS UBIGINT) AS "row_id",
                src.{q('ra')} AS ra,
                src.{q('dec')} AS dec,
                {mag_src_expr} AS phot_g_mean_mag,
                {bprp_src_expr} AS bp_rp,
                {opt_exprs['parallax']} AS parallax,
                {opt_exprs['pmra']} AS pmra,
                {opt_exprs['pmdec']} AS pmdec,
                {opt_exprs['radial_velocity']} AS radial_velocity,
                {opt_exprs['teff_gspphot']} AS teff_gspphot
            FROM read_parquet({files_sql}, filename=true, file_row_number=true) AS src
            INNER JOIN "__at_file_offsets" AS off
                ON replace(src.filename, '\\', '/') = off.file_path
            {limit_clause}
        """

        finite_ra_dec = (
            "ra IS NOT NULL AND dec IS NOT NULL "
            "AND isfinite(CAST(ra AS DOUBLE)) AND isfinite(CAST(dec AS DOUBLE))"
        )

        # Single-pass preflight for row counts + all 7 Gaia float column stats
        gaia_out_cols = [
            "phot_g_mean_mag",
            "bp_rp",
            "parallax",
            "pmra",
            "pmdec",
            "radial_velocity",
            "teff_gspphot",
        ]
        gaia_aggs = [
            "COUNT(*) AS total_in",
            f"COUNT(*) FILTER (WHERE {finite_ra_dec}) AS valid_in",
        ]
        for out_name in gaia_out_cols:
            f_expr = f"CAST({out_name} AS FLOAT)"
            gaia_aggs.append(
                f"MIN(CAST({f_expr} AS DOUBLE)) FILTER (WHERE {finite_ra_dec} AND {out_name} IS NOT NULL AND isfinite(CAST({f_expr} AS DOUBLE)))"
            )
            gaia_aggs.append(
                f"MAX(CAST({f_expr} AS DOUBLE)) FILTER (WHERE {finite_ra_dec} AND {out_name} IS NOT NULL AND isfinite(CAST({f_expr} AS DOUBLE)))"
            )
            gaia_aggs.append(
                f"COUNT(*) FILTER (WHERE {finite_ra_dec} AND {out_name} IS NULL)"
            )

        preflight_row = con.execute(
            f"SELECT {', '.join(gaia_aggs)} FROM ({raw_gaia_sql}) AS g"
        ).fetchone()
        assert preflight_row is not None
        total_in, valid_in = int(preflight_row[0] or 0), int(preflight_row[1] or 0)
        if valid_in == 0:
            raise ValueError("Gaia input contains 0 rows with finite (ra, dec)")
        dropped_rows = total_in - valid_in

        gaia_stats: dict[str, dict[str, Any]] = {}
        g_cur = 2
        for out_name in gaia_out_cols:
            rmin, rmax, rnull = preflight_row[g_cur], preflight_row[g_cur + 1], preflight_row[g_cur + 2]
            g_cur += 3
            gaia_stats[out_name] = {
                "type": "numeric",
                "min": float(rmin) if rmin is not None and math.isfinite(float(rmin)) else 0.0,
                "max": float(rmax) if rmax is not None and math.isfinite(float(rmax)) else 0.0,
                "null_count": int(rnull or 0),
            }

        gaia_query = f"""
            WITH raw_data AS (
                SELECT
                    "row_id",
                    ra, dec, phot_g_mean_mag, bp_rp, parallax, pmra, pmdec, radial_velocity, teff_gspphot,
                    RADIANS(CAST(ra AS DOUBLE)) AS ra_rad,
                    RADIANS(CAST(dec AS DOUBLE)) AS dec_rad,
                    RADIANS(192.85948) AS a_g,
                    RADIANS(27.12825) AS d_g,
                    RADIANS(122.93192) AS l_ncp
                FROM ({raw_gaia_sql}) AS g
                WHERE {finite_ra_dec}
            ),
            galactic AS (
                SELECT
                    *,
                    ASIN(LEAST(GREATEST(SIN(d_g)*SIN(dec_rad) + COS(d_g)*COS(dec_rad)*COS(ra_rad - a_g), -1.0), 1.0)) AS b_rad,
                    l_ncp - ATAN2(
                        COS(dec_rad)*SIN(ra_rad - a_g),
                        COS(d_g)*SIN(dec_rad) - SIN(d_g)*COS(dec_rad)*COS(ra_rad - a_g)
                    ) AS l_rad_raw
                FROM raw_data
            ),
            wrapped AS (
                SELECT
                    *,
                    ((l_rad_raw + 5*PI()) % (2*PI())) - PI() AS l_rad
                FROM galactic
            ),
            projected AS (
                SELECT
                    "row_id",
                    ((-2.0 * sqrt(2.0) * cos(b_rad) * sin(l_rad / 2.0)) / GREATEST(sqrt(1.0 + cos(b_rad) * cos(l_rad / 2.0)), 1e-12)) AS x_h,
                    ((sqrt(2.0) * sin(b_rad)) / GREATEST(sqrt(1.0 + cos(b_rad) * cos(l_rad / 2.0)), 1e-12)) AS y_h,
                    CAST(phot_g_mean_mag AS FLOAT) AS phot_g_mean_mag,
                    CAST(bp_rp AS FLOAT) AS bp_rp,
                    CAST(parallax AS FLOAT) AS parallax,
                    CAST(pmra AS FLOAT) AS pmra,
                    CAST(pmdec AS FLOAT) AS pmdec,
                    CAST(radial_velocity AS FLOAT) AS radial_velocity,
                    CAST(teff_gspphot AS FLOAT) AS teff_gspphot
                FROM wrapped
            )
            SELECT
                "row_id",
                LEAST(GREATEST((x_h + {hammer_half_w!r}) / {2.0 * hammer_half_w!r}, 0.0), 1.0) AS "__at_in_x",
                LEAST(GREATEST(({hammer_half_h!r} - y_h) / {2.0 * hammer_half_h!r}, 0.0), 1.0) AS "__at_in_y",
                phot_g_mean_mag,
                bp_rp,
                parallax,
                pmra,
                pmdec,
                radial_velocity,
                teff_gspphot
            FROM projected
        """

        bounds_dict = {
            "min_x": -hammer_half_w,
            "max_x": hammer_half_w,
            "min_y": -hammer_half_h,
            "max_y": hammer_half_h,
        }
        gaia_view: dict[str, Any] = {
            "mode": "Gaia Baseline",
            "colorField": "bp_rp",
            "colorMin": -0.5,
            "colorMax": 4.0,
            "sizeField": "phot_g_mean_mag",
            "sizeMin": 0.0,
            "sizeMax": 20.0,
            "colorScale": "viridis",
            "preserveAspect": True,
        }

        extra_custom_json: str | None = None
        if custom_config is not None and custom_config.strip():
            parsed_cfg = parse_strict_json_object(custom_config, label="custom_config")
            colliding = sorted(RESERVED_METADATA_KEYS.intersection(parsed_cfg.keys()))
            if colliding:
                raise ValueError(
                    f"custom_config contains reserved ArrowTiles key(s): {', '.join(colliding)}"
                )
            for vk in (
                "mode",
                "colorField",
                "colorMin",
                "colorMax",
                "sizeField",
                "sizeMin",
                "sizeMax",
                "colorScale",
                "preserveAspect",
            ):
                if vk in parsed_cfg:
                    gaia_view[vk] = parsed_cfg[vk]
            extra_custom_json = json.dumps(parsed_cfg, allow_nan=False, sort_keys=True)

        return builder.build(
            input_query=gaia_query,
            output_path=output_path,
            sort_col="phot_g_mean_mag",
            x_col="__at_in_x",
            y_col="__at_in_y",
            sort_dir="ASC",
            max_capacity=max_capacity,
            max_zoom=max_zoom,
            max_tile_rows=max_tile_rows,
            sampling=sampling,
            grid_size=grid_size,
            id_col="row_id",
            allow_oversize_leaves=allow_oversize_leaves,
            resume=resume,
            custom_metadata=extra_custom_json,
            bounds=bounds_dict,
            stats=gaia_stats,
            view=gaia_view,
            dropped_columns=[],
            pre_dropped_rows=dropped_rows,
            _prevalidated_counts=(valid_in, dropped_rows),
            _source_fingerprint=source_fp,
            _pass1_only=_pass1_only,
        )
