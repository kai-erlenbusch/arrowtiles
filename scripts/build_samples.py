"""Generate local gitignored v0.1 sample archives (< 20 MB each) under `samples/`.

Per D6, binary `.arrowtiles` files are never committed to Git. Run:
    python scripts/build_samples.py
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import duckdb

from arrowtiles import build_gaia, build_generic, validate_file

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_PARENT = REPO_ROOT.parent
DEFAULT_SAMPLES_DIR = REPO_ROOT / "samples"
MAX_SAMPLE_BYTES = 20 * 1024 * 1024  # 20 MiB


def _find_gaia_sources() -> list[Path]:
    override = os.environ.get("ARROWTILES_GAIA_BATCH0_PARQUET")
    if override:
        p = Path(override)
        return [p] if p.is_file() else []
    s3_dir = WORKSPACE_PARENT / "deepgraph-arrowtiles-sandbox" / "s3_cache"
    if s3_dir.is_dir():
        batches = sorted(s3_dir.glob("batch_*.parquet"))
        if batches:
            return batches
    return []


def _find_lmsys_source() -> Path | None:
    override = os.environ.get("ARROWTILES_MOCK_LMSYS_PARQUET")
    candidate = Path(override) if override else WORKSPACE_PARENT / "mock_lmsys.parquet"
    return candidate if candidate.is_file() else None


def _find_full_lmsys_source() -> Path | None:
    override = os.environ.get("ARROWTILES_FULL_LMSYS_PARQUET")
    candidate = (
        Path(override)
        if override
        else WORKSPACE_PARENT / "duckdb-cosmograph-oss" / "lmsys.parquet"
    )
    return candidate if candidate.is_file() else None


def build_all_samples(
    output_dir: Path = DEFAULT_SAMPLES_DIR,
    *,
    include_lmsys_full: bool = False,
    build_d7_comparison: bool = False,
) -> dict[str, dict]:
    import hashlib
    import shutil

    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}

    gaia_sources = _find_gaia_sources()
    if gaia_sources:
        gaia_out = output_dir / "gaia_sample.arrowtiles"
        tmp_dir = output_dir / "_tmp_gaia_sample"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            sampled_pq = tmp_dir / "gaia_fullsky_sample.parquet"
            files_sql = "[" + ", ".join(f"'{p.resolve().as_posix()}'" for p in gaia_sources) + "]"
            con = duckdb.connect()
            actual_rows = con.execute(
                f"""
                COPY (
                    WITH bright AS (
                        SELECT ra, dec, parallax, magnitude, bv, pmra, pmdec, radial_velocity, teff_gspphot
                        FROM read_parquet({files_sql})
                        WHERE magnitude IS NOT NULL AND magnitude <= 11.5
                        ORDER BY magnitude ASC
                        LIMIT 120000
                    ),
                    faint_mix AS (
                        SELECT ra, dec, parallax, magnitude, bv, pmra, pmdec, radial_velocity, teff_gspphot
                        FROM read_parquet({files_sql}, filename=true, file_row_number=true)
                        WHERE file_row_number < {max(1, 30000 // len(gaia_sources) + 1)}
                          AND (magnitude IS NULL OR magnitude > 11.5)
                        ORDER BY filename ASC, file_row_number ASC
                        LIMIT 30000
                    )
                    SELECT * FROM bright
                    UNION ALL
                    SELECT * FROM faint_mix
                ) TO '{sampled_pq.as_posix()}' (FORMAT PARQUET)
                """
            ).fetchone()[0]
            con.close()

            build_gaia(
                input_parquet=sampled_pq,
                output_path=gaia_out,
                max_capacity=25_000,
                max_zoom=7,
                memory_limit="4GB",
                temp_dir=str(tmp_dir / "duck_tmp"),
                show_progress=False,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        val = validate_file(gaia_out, expected_input_rows=int(actual_rows))
        size_bytes = gaia_out.stat().st_size
        if not val.ok:
            raise RuntimeError(f"gaia_sample validation failed: {val.errors}")
        if size_bytes >= MAX_SAMPLE_BYTES:
            raise RuntimeError(
                f"gaia_sample.arrowtiles ({size_bytes:,} B) exceeds 20 MiB limit"
            )
        results["gaia_sample"] = {
            "path": str(gaia_out),
            "size_bytes": size_bytes,
            "validation": val.to_dict(),
        }
    else:
        results["gaia_sample"] = {"skipped": True, "reason": "Gaia s3_cache batch_*.parquet not present"}

    lmsys_src = _find_lmsys_source()
    if lmsys_src is not None:
        lmsys_out = output_dir / "lmsys_sample.arrowtiles"
        tmp_dir = output_dir / "_tmp_lmsys_sample"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            build_generic(
                input_parquet=lmsys_src,
                output_path=lmsys_out,
                x_col="x",
                y_col="y",
                sort_col=None,
                seed=42,
                columns=["model", "num_of_tokens"],
                row_limit=100_000,
                max_capacity=20_000,
                max_zoom=8,
                memory_limit="4GB",
                temp_dir=str(tmp_dir),
                custom_config=json.dumps(
                    {
                        "colorField": "model",
                        "sizeField": "num_of_tokens",
                        "colorScale": "viridis",
                    }
                ),
                show_progress=False,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        val = validate_file(lmsys_out, expected_input_rows=100_000)
        size_bytes = lmsys_out.stat().st_size
        if not val.ok:
            raise RuntimeError(f"lmsys_sample validation failed: {val.errors}")
        if size_bytes >= MAX_SAMPLE_BYTES:
            raise RuntimeError(
                f"lmsys_sample.arrowtiles ({size_bytes:,} B) exceeds 20 MiB limit"
            )
        results["lmsys_sample"] = {
            "path": str(lmsys_out),
            "size_bytes": size_bytes,
            "validation": val.to_dict(),
        }
    else:
        results["lmsys_sample"] = {"skipped": True, "reason": "mock_lmsys.parquet not present"}

    if include_lmsys_full:
        full_src = _find_full_lmsys_source()
        if full_src is not None:
            full_out = output_dir / "lmsys_full_v01.arrowtiles"
            duck_tmp = output_dir / "_tmp_lmsys_full"
            try:
                build_res = build_generic(
                    input_parquet=full_src,
                    output_path=full_out,
                    x_col="x_umap",
                    y_col="y_umap",
                    sort_col="num_of_tokens",
                    sort_dir="DESC",
                    max_capacity=100_000,
                    max_zoom=14,
                    memory_limit="16GB",
                    temp_dir=duck_tmp,
                    custom_config=json.dumps(
                        {
                            "colorField": "model",
                            "sizeField": "num_of_tokens",
                            "colorScale": "viridis",
                        }
                    ),
                    show_progress=False,
                )
            finally:
                import shutil

                shutil.rmtree(duck_tmp, ignore_errors=True)

            expected_in = build_res["total_rows"] + build_res["dropped_rows"]
            val_full = validate_file(full_out, expected_input_rows=expected_in)
            if not val_full.ok:
                raise RuntimeError(f"lmsys_full_v01 validation failed: {val_full.errors}")
            results["lmsys_full_v01"] = {
                "path": str(full_out),
                "size_bytes": full_out.stat().st_size,
                "dropped_columns": build_res["dropped_columns"],
                "validation": val_full.to_dict(),
            }
        else:
            results["lmsys_full_v01"] = {"skipped": True, "reason": "lmsys.parquet not present"}

    if build_d7_comparison:
        full_src = _find_full_lmsys_source()
        if full_src is not None:
            for mode in ("even_coverage", "proportional"):
                d7_out = output_dir / f"lmsys_d7_{mode}.arrowtiles"
                duck_tmp = output_dir / f"_tmp_lmsys_d7_{mode}"
                shutil.rmtree(duck_tmp, ignore_errors=True)
                try:
                    build_res = build_generic(
                        input_parquet=full_src,
                        output_path=d7_out,
                        x_col="x_umap",
                        y_col="y_umap",
                        sort_col=None,
                        seed=42,
                        sampling=mode,
                        max_capacity=100_000,
                        max_zoom=14,
                        memory_limit="16GB",
                        temp_dir=duck_tmp,
                        custom_config=json.dumps(
                            {
                                "colorField": "model",
                                "sizeField": "num_of_tokens",
                                "colorScale": "viridis",
                            }
                        ),
                        show_progress=False,
                    )
                finally:
                    shutil.rmtree(duck_tmp, ignore_errors=True)

                expected_in = build_res["total_rows"] + build_res["dropped_rows"]
                val_d7 = validate_file(d7_out, expected_input_rows=expected_in)
                if not val_d7.ok:
                    raise RuntimeError(f"lmsys_d7_{mode} validation failed: {val_d7.errors}")
                digest = hashlib.sha256()
                with open(d7_out, "rb") as fh:
                    for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                        digest.update(chunk)
                results[f"lmsys_d7_{mode}"] = {
                    "path": str(d7_out),
                    "size_bytes": d7_out.stat().st_size,
                    "sha256": digest.hexdigest(),
                    "sampling": mode,
                    "dropped_columns": build_res["dropped_columns"],
                    "validation": val_d7.to_dict(),
                }
        else:
            results["lmsys_d7"] = {"skipped": True, "reason": "lmsys.parquet not present"}

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local v0.1 sample .arrowtiles archives")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_SAMPLES_DIR,
        help="Directory for generated sample archives (default: ./samples)",
    )
    parser.add_argument(
        "--include-lmsys-full",
        action="store_true",
        help="Also build full 2.84M-row samples/lmsys_full_v01.arrowtiles (testing D7a free-text drop)",
    )
    parser.add_argument(
        "--build-d7-comparison",
        action="store_true",
        help="Build full 2.84M-row LMSys D7 comparison pair (even_coverage vs proportional, random seed=42)",
    )
    args = parser.parse_args()
    summary = build_all_samples(
        args.output_dir,
        include_lmsys_full=args.include_lmsys_full,
        build_d7_comparison=args.build_d7_comparison,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
