"""CLI entry point for `python -m arrowtiles` (`build`, `validate`, `inspect`)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from arrowtiles.builder import (
    DEFAULT_AUTO_MAX_CATEGORIES,
    DEFAULT_GAIA_TILE_CAPACITY,
    DEFAULT_MAX_TILE_ROWS,
    DEFAULT_NOMINAL_MAX_ZOOM,
    DEFAULT_RANDOM_SEED,
    DEFAULT_TILE_CAPACITY,
    build_gaia,
    build_generic,
)
from arrowtiles.reader import ArrowTilesReader
from arrowtiles.validator import validate_file


def _flatten_column_args(raw: str | Sequence[str] | None) -> list[str] | None:
    if not raw:
        return None
    tokens = [raw] if isinstance(raw, str) else list(raw)
    out = [c.strip() for tok in tokens for c in tok.split(",") if c.strip()]
    return out or None


def _cmd_build(args: argparse.Namespace) -> int:
    preset = args.preset or args.dataset
    if preset == "gaia":
        summary = build_gaia(
            input_parquet=args.input,
            output_path=args.output,
            row_limit=args.row_limit,
            max_capacity=args.tile_capacity if args.tile_capacity is not None else DEFAULT_GAIA_TILE_CAPACITY,
            max_zoom=args.max_zoom,
            max_tile_rows=args.max_tile_rows,
            sampling=args.sampling if args.sampling is not None else "even_coverage",
            grid_size=args.grid_size,
            allow_oversize_leaves=args.allow_oversize_leaves,
            custom_config=args.config,
            resume=args.resume,
            memory_limit=args.memory_limit,
            temp_dir=args.temp_dir,
            threads=args.threads,
        )
    else:
        if not args.x_col or not args.y_col:
            print("Error: --x-col and --y-col are required for generic builds.", file=sys.stderr)
            return 2
        cols = _flatten_column_args(args.columns)
        cat_cols = _flatten_column_args(args.categorical_cols)
        summary = build_generic(
            input_parquet=args.input,
            output_path=args.output,
            x_col=args.x_col,
            y_col=args.y_col,
            sort_col=args.sort_col,
            sort_dir=args.sort_dir,
            id_col=args.id_col,
            columns=cols,
            categorical_cols=cat_cols,
            keep_source_xy=args.keep_source_xy,
            max_capacity=args.tile_capacity if args.tile_capacity is not None else DEFAULT_TILE_CAPACITY,
            max_zoom=args.max_zoom,
            max_tile_rows=args.max_tile_rows,
            sampling=args.sampling if args.sampling is not None else "proportional",
            grid_size=args.grid_size,
            seed=args.seed,
            max_categories=args.max_categories,
            allow_oversize_leaves=args.allow_oversize_leaves,
            row_limit=args.row_limit,
            resume=args.resume,
            memory_limit=args.memory_limit,
            temp_dir=args.temp_dir,
            threads=args.threads,
            custom_config=args.config,
        )

    print(json.dumps(summary, indent=2))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    res = validate_file(
        args.file,
        expected_input_rows=args.expected_input_rows,
        max_tiles_to_scan=args.max_tiles,
    )
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        status = "PASS (legacy v0.0)" if (res.ok and res.is_legacy) else ("PASS" if res.ok else "FAIL")
        max_mb = res.max_compressed_tile_bytes / (1024 * 1024)
        print(f"[{status}] {res.path}")
        print(
            f"  spec={res.spec_version or 'v0.0-legacy'}  tiles={res.tile_count:,}  "
            f"rows={res.total_rows:,}  dropped={res.dropped_rows}  "
            f"zoom=0..{res.actual_max_zoom} (header={res.header_max_zoom})"
        )
        print(
            f"  max_tile_rows={res.observed_max_tile_rows:,} (declared={res.declared_max_tile_rows})  "
            f"max_compressed_tile={res.max_compressed_tile_bytes:,} B ({max_mb:.2f} MiB at {res.max_compressed_tile_coord})"
        )
        for w in res.warnings:
            print(f"  WARN: {w}")
        for err in res.errors:
            print(f"  ERROR: {err}", file=sys.stderr)
    return 0 if res.ok else 1


def _cmd_inspect(args: argparse.Namespace) -> int:
    with ArrowTilesReader(args.file) as reader:
        meta = dict(reader.metadata())
        if not args.include_schema_b64:
            meta.pop("arrow_schema", None)
        out = {
            "header": {k: str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v for k, v in reader.header().items()},
            "schema": [{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in reader.schema()],
            "metadata": meta,
        }
        print(json.dumps(out, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arrowtiles",
        description="ArrowTiles v0.1 builder, validator, and inspector",
    )
    sub = parser.add_subparsers(dest="command")

    p_build = sub.add_parser("build", help="Build a v0.1 .arrowtiles archive")
    p_build.add_argument("--input", required=True, help="Input Parquet file or glob")
    p_build.add_argument("--output", required=True, help="Output .arrowtiles path")
    p_build.add_argument("--preset", choices=["gaia"], default=None, help="Named dataset preset")
    p_build.add_argument(
        "--dataset",
        choices=["gaia", "generic"],
        default="generic",
        help="Dataset pipeline (legacy alias for --preset)",
    )
    p_build.add_argument("--x-col", default=None, help="Source X column name")
    p_build.add_argument("--y-col", default=None, help="Source Y column name")
    p_build.add_argument("--sort-col", default=None, help="Optional priority sort column (default: seeded random)")
    p_build.add_argument("--sort-dir", choices=["ASC", "DESC", "asc", "desc"], default="ASC")
    p_build.add_argument("--id-col", default=None, help="Optional unique integer row ID column")
    p_build.add_argument(
        "--columns",
        nargs="+",
        default=None,
        help="Space- or comma-separated subset of payload columns to retain",
    )
    p_build.add_argument(
        "--categorical-cols",
        nargs="+",
        default=None,
        help="Space- or comma-separated columns (including integer cluster IDs) to encode as v0.1 categoricals",
    )
    p_build.add_argument("--keep-source-xy", action="store_true", help="Retain raw source X/Y columns in tiles")
    p_build.add_argument(
        "--tile-capacity",
        type=int,
        default=None,
        help="Per-tile capacity at z < nominal_max_zoom (default: 25,000 generic / 100,000 --preset gaia)",
    )
    p_build.add_argument("--max-tile-rows", type=int, default=DEFAULT_MAX_TILE_ROWS)
    p_build.add_argument("--max-zoom", type=int, default=DEFAULT_NOMINAL_MAX_ZOOM)
    p_build.add_argument(
        "--sampling",
        choices=["even_coverage", "proportional"],
        default=None,
        help="Pyramid sampling mode (default: proportional for generic / even_coverage for --preset gaia)",
    )
    p_build.add_argument("--grid-size", type=int, default=None)
    p_build.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    p_build.add_argument("--max-categories", type=int, default=DEFAULT_AUTO_MAX_CATEGORIES)
    p_build.add_argument("--allow-oversize-leaves", action="store_true")
    p_build.add_argument("--row-limit", type=int, default=None, help="Optional deterministic row limit")
    p_build.add_argument("--config", default=None, help="Optional JSON view/custom metadata overrides")
    p_build.add_argument("--resume", action="store_true")
    p_build.add_argument("--memory-limit", default="40GB")
    p_build.add_argument("--temp-dir", default=None)
    p_build.add_argument("--threads", type=int, default=None)
    p_build.set_defaults(func=_cmd_build)

    p_val = sub.add_parser("validate", help="Validate an .arrowtiles archive against SPEC.md v0.1")
    p_val.add_argument("file", help="Path to .arrowtiles archive")
    p_val.add_argument("--expected-input-rows", type=int, default=None)
    p_val.add_argument("--max-tiles", type=int, default=None, help="Optional limit on tiles scanned")
    p_val.add_argument("--json", action="store_true", help="Emit machine-readable JSON report")
    p_val.set_defaults(func=_cmd_validate)

    p_insp = sub.add_parser("inspect", help="Print header, schema, and metadata of an .arrowtiles archive")
    p_insp.add_argument("file", help="Path to .arrowtiles archive")
    p_insp.add_argument("--include-schema-b64", action="store_true")
    p_insp.set_defaults(func=_cmd_inspect)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
