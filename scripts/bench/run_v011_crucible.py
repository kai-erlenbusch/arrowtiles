"""Step 2 Progressive v0.1.1 Hardware Crucible & Validation Ladder (2.84M -> 100M -> 500M -> 1.35B).

Pins all DuckDB/Python temporary spill files strictly to `--scratch-dir` on D: (never C:),
measures Pass 1 / Pass 2 wall-clock, peak OS Working Set RSS, and peak D: scratch footprint,
runs full SPEC v0.1 `validate_file` checks on every rung, deletes intermediate ephemeral
archives before advancing, and extracts ground-truth `row_id > 1,000,000,000` reference stars
cross-checked against raw `s3_cache` Parquet for Playwright dual-GPU picking parity.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import math
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

import arrowtiles
from arrowtiles import ArrowTilesReader, build_gaia, build_generic, validate_file

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_PARENT = REPO_ROOT.parent
_DEFAULT_VIEWER_DIR = (
    WORKSPACE_PARENT / "deepgraph"
    if (WORKSPACE_PARENT / "deepgraph").is_dir()
    else WORKSPACE_PARENT / "deepgraph-arrowtiles-sandbox"
)
DEFAULT_SCRATCH_DIR = WORKSPACE_PARENT / "_scratch_crucible"


# Windows PSAPI PeakWorkingSetSize / WorkingSetSize query (zero external dependency)
class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def get_process_rss_bytes() -> tuple[int, int]:
    """Return `(current_rss_bytes, os_peak_rss_bytes)` for the current process."""
    if os.name == "nt":
        pmc = _PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        get_current = ctypes.windll.kernel32.GetCurrentProcess
        get_current.argtypes = []
        get_current.restype = wintypes.HANDLE
        get_mem_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_mem_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        get_mem_info.restype = wintypes.BOOL
        handle = get_current()
        ok = get_mem_info(handle, ctypes.byref(pmc), pmc.cb)
        if ok:
            return int(pmc.WorkingSetSize), int(pmc.PeakWorkingSetSize)
    return 0, 0


def dir_size_bytes(root: Path) -> int:
    """Safely sum bytes under `root`, ignoring transient files unlinked concurrently by DuckDB."""
    if not root.exists():
        return 0
    total = 0
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


class BuildTelemetrySampler:
    """Polls process RSS and scratch-directory disk usage at 400 ms intervals during a build."""

    def __init__(self, temp_dir: Path, output_path: Path, poll_sec: float = 0.4) -> None:
        self.temp_dir = temp_dir
        self.output_path = output_path
        self.output_tmp_path = Path(f"{output_path}.tmp")
        self.poll_sec = poll_sec
        self.peak_rss_bytes = 0
        self.peak_temp_dir_bytes = 0
        self.peak_combined_disk_bytes = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _sample_once(self) -> None:
        cur_rss, _os_peak = get_process_rss_bytes()
        if cur_rss > self.peak_rss_bytes:
            self.peak_rss_bytes = cur_rss

        tmp_bytes = dir_size_bytes(self.temp_dir)
        if tmp_bytes > self.peak_temp_dir_bytes:
            self.peak_temp_dir_bytes = tmp_bytes

        out_bytes = 0
        for p in (self.output_tmp_path, self.output_path):
            try:
                if p.is_file():
                    out_bytes += p.stat().st_size
            except OSError:
                pass
        combined = tmp_bytes + out_bytes
        if combined > self.peak_combined_disk_bytes:
            self.peak_combined_disk_bytes = combined

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sample_once()
            self._stop.wait(self.poll_sec)

    def __enter__(self) -> BuildTelemetrySampler:
        self._sample_once()
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)
        self._sample_once()


def disk_free_gib(drive_or_path: str | Path) -> float:
    return shutil.disk_usage(str(drive_or_path)).free / (1024.0**3)


def system_drive_free_gib() -> float:
    sys_root = "C:/" if os.name == "nt" and Path("C:/").exists() else "/"
    return disk_free_gib(sys_root)


def hammer_gal_from_icrs_deg(ra_deg: float, dec_deg: float) -> tuple[float, float]:
    """Exact clean-room ICRS (deg) -> Galactic Hammer `(x, y)` matching `build_gaia` SQL."""
    ra_rad = math.radians(ra_deg)
    dec_rad = math.radians(dec_deg)
    a_g = math.radians(192.85948)
    d_g = math.radians(27.12825)
    l_ncp = math.radians(122.93192)

    sin_b = math.sin(d_g) * math.sin(dec_rad) + math.cos(d_g) * math.cos(dec_rad) * math.cos(
        ra_rad - a_g
    )
    b_rad = math.asin(max(-1.0, min(1.0, sin_b)))
    l_rad_raw = l_ncp - math.atan2(
        math.cos(dec_rad) * math.sin(ra_rad - a_g),
        math.cos(d_g) * math.sin(dec_rad)
        - math.sin(d_g) * math.cos(dec_rad) * math.cos(ra_rad - a_g),
    )
    l_rad = math.fmod(l_rad_raw + 5.0 * math.pi, 2.0 * math.pi) - math.pi
    cos_b = math.cos(b_rad)
    denom = max(math.sqrt(max(0.0, 1.0 + cos_b * math.cos(l_rad * 0.5))), 1e-12)
    x_h = (-2.0 * math.sqrt(2.0) * cos_b * math.sin(l_rad * 0.5)) / denom
    y_h = (math.sqrt(2.0) * math.sin(b_rad)) / denom
    return x_h, y_h


def extract_billion_rowid_reference_stars(
    archive_path: Path, gaia_glob: str, max_targets: int = 5
) -> list[dict[str, Any]]:
    """Find stars with `row_id > 1,000,000,000` in overview tiles and cross-check raw Parquet."""
    reader = ArrowTilesReader(archive_path)
    meta = reader.metadata()
    bounds = meta["bounds"]
    min_x, max_x = float(bounds["min_x"]), float(bounds["max_x"])
    min_y, max_y = float(bounds["min_y"]), float(bounds["max_y"])

    candidates: list[dict[str, Any]] = []
    # Scan Z=0..2 overview tiles for bright stars originating from batch_031+ (row_id > 1e9)
    coords_to_scan = [(0, 0, 0)] + [(1, x, y) for x in range(2) for y in range(2)] + [
        (2, x, y) for x in range(4) for y in range(4)
    ]
    seen_ids: set[int] = set()
    for z, tx, ty in coords_to_scan:
        tbl = reader.read_tile(z, tx, ty, decode_coords=False)
        if tbl is None or tbl.num_rows == 0:
            continue
        rids = tbl.column("row_id").to_pylist()
        xs = tbl.column("x_u16").to_pylist()
        ys = tbl.column("y_u16").to_pylist()
        mags = tbl.column("phot_g_mean_mag").to_pylist()
        bprps = tbl.column("bp_rp").to_pylist()
        plxs = tbl.column("parallax").to_pylist()
        scale = 2.0 ** (-z)
        for idx, rid in enumerate(rids):
            rid_int = int(rid)
            if rid_int <= 1_000_000_000 or rid_int in seen_ids:
                continue
            mag_val = mags[idx]
            if mag_val is None or not math.isfinite(float(mag_val)):
                continue
            # Ensure well-isolated in u16 space within this tile so GPU pickAt is 100% unambiguous
            xi, yi = int(xs[idx]), int(ys[idx])
            too_close = False
            for j in range(max(0, idx - 64), idx):
                if abs(int(xs[j]) - xi) <= 3 and abs(int(ys[j]) - yi) <= 3:
                    too_close = True
                    break
            if too_close:
                continue
            seen_ids.add(rid_int)
            gx = (tx + float(xs[idx]) / 65535.0) * scale
            gy = (ty + float(ys[idx]) / 65535.0) * scale
            data_x = min_x + gx * (max_x - min_x)
            data_y = max_y - gy * (max_y - min_y)
            candidates.append(
                {
                    "row_id": rid_int,
                    "tile_z": z,
                    "tile_x": tx,
                    "tile_y": ty,
                    "raw_row_idx": idx,
                    "x_u16": int(xs[idx]),
                    "y_u16": int(ys[idx]),
                    "data_x": data_x,
                    "data_y": data_y,
                    "tile_phot_g_mean_mag": float(mag_val),
                    "tile_bp_rp": float(bprps[idx]) if bprps[idx] is not None else None,
                    "tile_parallax": float(plxs[idx]) if plxs[idx] is not None else None,
                }
            )
            if len(candidates) >= max_targets * 6:
                break
        if len(candidates) >= max_targets * 6:
            break

    reader.close()
    candidates.sort(key=lambda c: (c["tile_z"], c["tile_phot_g_mean_mag"], c["row_id"]))
    chosen = candidates[:max_targets]
    if not chosen:
        raise RuntimeError("No reference stars with row_id > 1,000,000,000 found in Z=0..2!")

    # Cross-check each chosen row_id directly against raw s3_cache Parquet!
    con = duckdb.connect()
    glob_posix = Path(gaia_glob).as_posix() if "*" not in gaia_glob else gaia_glob.replace("\\", "/")
    meta_rows = con.execute(
        f"SELECT file_name, CAST(num_rows AS BIGINT) FROM parquet_file_metadata('{glob_posix}')"
    ).fetchall()
    sorted_files = sorted(
        (Path(str(fn)).resolve().as_posix(), int(nr)) for fn, nr in meta_rows
    )

    verified: list[dict[str, Any]] = []
    for item in chosen:
        target_rid = item["row_id"]
        running = 0
        matched_file: str | None = None
        local_row_num = -1
        for fpath, nrows in sorted_files:
            if running + nrows > target_rid:
                matched_file = fpath
                local_row_num = target_rid - running
                break
            running += nrows
        if matched_file is None:
            raise RuntimeError(f"row_id {target_rid} exceeded total Parquet rows {running}")

        pq_row = con.execute(
            f"""
            SELECT ra, dec, magnitude, bv, parallax, teff_gspphot
            FROM read_parquet('{matched_file}', file_row_number=true)
            WHERE file_row_number = {int(local_row_num)}
            """
        ).fetchone()
        if pq_row is None:
            raise RuntimeError(
                f"Failed to locate file_row_number={local_row_num} in {matched_file}"
            )
        ra_deg, dec_deg, mag_pq, bv_pq, plx_pq, teff_pq = pq_row
        xh, yh = hammer_gal_from_icrs_deg(float(ra_deg), float(dec_deg))
        # Verify u16 quantization accuracy (~4*sqrt(2)/65535 = 8.6e-5 at Z=0)
        max_quant_step = (max_x - min_x) / (65535.0 * (2**item["tile_z"])) * 1.5
        if abs(item["data_x"] - xh) > max_quant_step or abs(item["data_y"] - yh) > max_quant_step:
            raise RuntimeError(
                f"Coordinate mismatch on row_id={target_rid}: tile=({item['data_x']}, {item['data_y']}) "
                f"vs Parquet Hammer=({xh}, {yh})"
            )
        if abs(item["tile_phot_g_mean_mag"] - float(mag_pq)) > 1e-4:
            raise RuntimeError(
                f"Magnitude mismatch on row_id={target_rid}: {item['tile_phot_g_mean_mag']} vs {mag_pq}"
            )

        verified.append(
            {
                **item,
                "parquet_file": os.path.basename(matched_file),
                "parquet_file_row_number": int(local_row_num),
                "parquet_ra": float(ra_deg),
                "parquet_dec": float(dec_deg),
                "parquet_hammer_x": xh,
                "parquet_hammer_y": yh,
                "parquet_magnitude": float(mag_pq),
                "parquet_bv": float(bv_pq) if bv_pq is not None else None,
                "parquet_parallax": float(plx_pq) if plx_pq is not None else None,
                "parquet_teff_gspphot": float(teff_pq) if teff_pq is not None else None,
            }
        )
    con.close()
    return verified


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ArrowTiles v0.1.1 Hardware Crucible")
    parser.add_argument(
        "--gaia-glob",
        default=str(_DEFAULT_VIEWER_DIR / "s3_cache" / "batch_*.parquet"),
    )
    parser.add_argument(
        "--lmsys-parquet",
        default=str(WORKSPACE_PARENT / "lmsys.parquet"),
    )
    parser.add_argument(
        "--scratch-dir",
        default=str(DEFAULT_SCRATCH_DIR),
    )
    parser.add_argument(
        "--out-gaia",
        default=str(_DEFAULT_VIEWER_DIR / "public" / "gaia_v011_full.arrowtiles"),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting an existing gaia_full.arrowtiles when passed to --out-gaia.",
    )
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument(
        "--report-json",
        default=None,
    )
    parser.add_argument("--rungs", default="1,2,3,4")
    args = parser.parse_args()

    scratch_dir = Path(args.scratch_dir).resolve()
    tmp_env_dir = scratch_dir / "tmp"
    tmp_env_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(tmp_env_dir)
    os.environ["TMP"] = str(tmp_env_dir)
    tempfile.tempdir = str(tmp_env_dir)

    out_gaia = Path(args.out_gaia).resolve()
    enabled_rungs = {int(x.strip()) for x in args.rungs.split(",") if x.strip()}
    if (
        4 in enabled_rungs
        and out_gaia.name.lower() == "gaia_full.arrowtiles"
        and out_gaia.exists()
        and not args.overwrite
    ):
        raise ValueError(
            "Refusing to overwrite existing gaia_full.arrowtiles without --overwrite!"
        )

    report_path = (
        Path(args.report_json).resolve()
        if args.report_json
        else (scratch_dir / "crucible_v011_results.json")
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)

    existing_report: dict[str, Any] = {}
    if report_path.is_file():
        try:
            existing_report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            existing_report = {}

    c_free_initial = system_drive_free_gib()
    d_free_initial = disk_free_gib(scratch_dir)
    print(
        f"[Crucible Init] TEMP={os.environ['TEMP']} | sys free={c_free_initial:.2f} GiB | "
        f"scratch free={d_free_initial:.2f} GiB | memory_limit={args.memory_limit}",
        flush=True,
    )
    if c_free_initial < 12.0:
        raise RuntimeError(f"System drive free space dangerously low ({c_free_initial:.2f} GiB)")

    results: dict[str, Any] = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "python_version": sys.version.split()[0],
            "arrowtiles_version": arrowtiles.__version__,
            "duckdb_version": duckdb.__version__,
            "pyarrow_version": pa.__version__,
            "memory_limit": args.memory_limit,
            "c_free_initial_gib": round(c_free_initial, 3),
            "d_free_initial_gib": round(d_free_initial, 3),
        },
        "rungs": existing_report.get("rungs", {}),
    }

    def save_checkpoint() -> None:
        report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # =========================================================================
    # RUNG 1: 2.84M Wide LMSys (39 columns)
    # =========================================================================
    if 1 in enabled_rungs:
        lmsys_pq = Path(args.lmsys_parquet).resolve()
        if not lmsys_pq.is_file():
            raise FileNotFoundError(f"LMSys Parquet not found: {lmsys_pq}")
        rung1_out = scratch_dir / "lmsys_v011.arrowtiles"
        rung1_tmp = scratch_dir / "tmp_rung1_lmsys"
        shutil.rmtree(rung1_tmp, ignore_errors=True)
        if rung1_out.exists():
            rung1_out.unlink()

        print("\n=== [Rung 1] Building 2.84M Wide LMSys (lmsys.parquet) ===", flush=True)
        t0 = time.perf_counter()
        try:
            with BuildTelemetrySampler(rung1_tmp, rung1_out) as sampler:
                build_res = build_generic(
                    input_parquet=lmsys_pq,
                    output_path=rung1_out,
                    x_col="x_umap",
                    y_col="y_umap",
                    sort_col="num_of_tokens",
                    sort_dir="DESC",
                    categorical_cols=["clusters_07", "clusters_14", "clusters_28"],
                    max_capacity=100_000,
                    max_zoom=14,
                    memory_limit=args.memory_limit,
                    temp_dir=rung1_tmp,
                    custom_config=json.dumps(
                        {
                            "colorField": "model",
                            "sizeField": "num_of_tokens",
                            "colorScale": "viridis",
                        }
                    ),
                    show_progress=False,
                )
            wall_sec = time.perf_counter() - t0
            out_size = rung1_out.stat().st_size

            t_val0 = time.perf_counter()
            expected_in = int(build_res["total_rows"]) + int(build_res["dropped_rows"])
            val = validate_file(rung1_out, expected_input_rows=expected_in)
            val_sec = time.perf_counter() - t_val0
            if not val.ok:
                raise RuntimeError(f"Rung 1 validation failed: {val.errors}")

            with ArrowTilesReader(rung1_out) as rdr:
                root_tbl = rdr.read_tile(0, 0, 0, decode_coords=True, decode_categories=True)
                assert root_tbl is not None and root_tbl.num_rows > 0
                stats_meta = rdr.metadata().get("stats", {})
                assert "model" in stats_meta and len(stats_meta["model"].get("categories", [])) > 5
                assert (
                    "clusters_14" in stats_meta
                    and len(stats_meta["clusters_14"].get("categories", [])) == 14
                )
                f32_cols = [
                    f.name for f in rdr.schema() if str(f.type) == "float"
                ]

            results["rungs"]["rung1_lmsys_2_84m"] = {
                "input_rows": expected_in,
                "retained_rows": int(build_res["total_rows"]),
                "dropped_rows": int(build_res["dropped_rows"]),
                "dropped_columns": build_res["dropped_columns"],
                "float32_downcast_cols_count": len(f32_cols),
                "wall_seconds": round(wall_sec, 3),
                "pass1_seconds": build_res.get("pass1_seconds"),
                "pass2_seconds": build_res.get("pass2_seconds"),
                "rows_per_sec": round(int(build_res["total_rows"]) / max(1e-6, wall_sec), 1),
                "archive_bytes": out_size,
                "archive_mib": round(out_size / (1024.0**2), 2),
                "peak_rss_gib": round(sampler.peak_rss_bytes / (1024.0**3), 3),
                "peak_scratch_gib": round(sampler.peak_temp_dir_bytes / (1024.0**3), 3),
                "validate_seconds": round(val_sec, 3),
                "validation": val.to_dict(),
                "c_free_after_gib": round(system_drive_free_gib(), 3),
            }
            save_checkpoint()
            print(
                f"[Rung 1 PASS] {build_res['total_rows']:,} rows in {wall_sec:.2f}s "
                f"({out_size / 1024**2:.2f} MiB, peak RSS={sampler.peak_rss_bytes / 1024**3:.2f} GiB, "
                f"tiles={val.tile_count:,})",
                flush=True,
            )
        finally:
            shutil.rmtree(rung1_tmp, ignore_errors=True)
            if rung1_out.exists():
                rung1_out.unlink()

    # =========================================================================
    # RUNG 2: 100M Real Gaia DR3 Stars
    # =========================================================================
    if 2 in enabled_rungs:
        rung2_out = scratch_dir / "gaia_100m_v011.arrowtiles"
        rung2_tmp = scratch_dir / "tmp_rung2_100m"
        shutil.rmtree(rung2_tmp, ignore_errors=True)
        if rung2_out.exists():
            rung2_out.unlink()

        print("\n=== [Rung 2] Building 100,000,000 Real Gaia Stars ===", flush=True)
        t0 = time.perf_counter()
        try:
            with BuildTelemetrySampler(rung2_tmp, rung2_out) as sampler:
                build_res = build_gaia(
                    input_parquet=args.gaia_glob,
                    output_path=rung2_out,
                    row_limit=100_000_000,
                    memory_limit=args.memory_limit,
                    temp_dir=rung2_tmp,
                    show_progress=False,
                )
            wall_sec = time.perf_counter() - t0
            out_size = rung2_out.stat().st_size

            t_val0 = time.perf_counter()
            val = validate_file(rung2_out, expected_input_rows=100_000_000)
            val_sec = time.perf_counter() - t_val0
            if not val.ok:
                raise RuntimeError(f"Rung 2 validation failed: {val.errors}")

            results["rungs"]["rung2_gaia_100m"] = {
                "input_rows": 100_000_000,
                "retained_rows": int(build_res["total_rows"]),
                "dropped_rows": int(build_res["dropped_rows"]),
                "wall_seconds": round(wall_sec, 3),
                "pass1_seconds": build_res.get("pass1_seconds"),
                "pass2_seconds": build_res.get("pass2_seconds"),
                "rows_per_sec": round(int(build_res["total_rows"]) / max(1e-6, wall_sec), 1),
                "archive_bytes": out_size,
                "archive_gib": round(out_size / (1024.0**3), 3),
                "peak_rss_gib": round(sampler.peak_rss_bytes / (1024.0**3), 3),
                "peak_scratch_gib": round(sampler.peak_temp_dir_bytes / (1024.0**3), 3),
                "peak_combined_disk_gib": round(sampler.peak_combined_disk_bytes / (1024.0**3), 3),
                "validate_seconds": round(val_sec, 3),
                "validation": val.to_dict(),
                "c_free_after_gib": round(system_drive_free_gib(), 3),
            }
            save_checkpoint()
            print(
                f"[Rung 2 PASS] 100M rows in {wall_sec:.2f}s (P1={build_res.get('pass1_seconds')}s, "
                f"P2={build_res.get('pass2_seconds')}s, size={out_size / 1024**3:.2f} GiB, "
                f"peak scratch={sampler.peak_temp_dir_bytes / 1024**3:.2f} GiB, "
                f"peak RSS={sampler.peak_rss_bytes / 1024**3:.2f} GiB, tiles={val.tile_count:,})",
                flush=True,
            )
        finally:
            shutil.rmtree(rung2_tmp, ignore_errors=True)
            if rung2_out.exists():
                rung2_out.unlink()

    # =========================================================================
    # RUNG 3: 500M Real Gaia DR3 Stars (+ Extrapolation Guard Before 1.35B)
    # =========================================================================
    if 3 in enabled_rungs:
        rung3_out = scratch_dir / "gaia_500m_v011.arrowtiles"
        rung3_tmp = scratch_dir / "tmp_rung3_500m"
        shutil.rmtree(rung3_tmp, ignore_errors=True)
        if rung3_out.exists():
            rung3_out.unlink()

        print("\n=== [Rung 3] Building 500,000,000 Real Gaia Stars ===", flush=True)
        t0 = time.perf_counter()
        try:
            with BuildTelemetrySampler(rung3_tmp, rung3_out) as sampler:
                build_res = build_gaia(
                    input_parquet=args.gaia_glob,
                    output_path=rung3_out,
                    row_limit=500_000_000,
                    memory_limit=args.memory_limit,
                    temp_dir=rung3_tmp,
                    show_progress=False,
                )
            wall_sec = time.perf_counter() - t0
            out_size = rung3_out.stat().st_size

            t_val0 = time.perf_counter()
            val = validate_file(rung3_out, expected_input_rows=500_000_000)
            val_sec = time.perf_counter() - t_val0
            if not val.ok:
                raise RuntimeError(f"Rung 3 validation failed: {val.errors}")

            peak_scratch_gib = sampler.peak_temp_dir_bytes / (1024.0**3)
            extrapolated_135b_scratch_gib = peak_scratch_gib * (1_348_176_623.0 / 500_000_000.0)

            results["rungs"]["rung3_gaia_500m"] = {
                "input_rows": 500_000_000,
                "retained_rows": int(build_res["total_rows"]),
                "dropped_rows": int(build_res["dropped_rows"]),
                "wall_seconds": round(wall_sec, 3),
                "pass1_seconds": build_res.get("pass1_seconds"),
                "pass2_seconds": build_res.get("pass2_seconds"),
                "rows_per_sec": round(int(build_res["total_rows"]) / max(1e-6, wall_sec), 1),
                "archive_bytes": out_size,
                "archive_gib": round(out_size / (1024.0**3), 3),
                "peak_rss_gib": round(sampler.peak_rss_bytes / (1024.0**3), 3),
                "peak_scratch_gib": round(peak_scratch_gib, 3),
                "extrapolated_135b_scratch_gib": round(extrapolated_135b_scratch_gib, 3),
                "peak_combined_disk_gib": round(sampler.peak_combined_disk_bytes / (1024.0**3), 3),
                "validate_seconds": round(val_sec, 3),
                "validation": val.to_dict(),
                "c_free_after_gib": round(system_drive_free_gib(), 3),
            }
            save_checkpoint()
            print(
                f"[Rung 3 PASS] 500M rows in {wall_sec:.2f}s (P1={build_res.get('pass1_seconds')}s, "
                f"P2={build_res.get('pass2_seconds')}s, size={out_size / 1024**3:.2f} GiB, "
                f"peak scratch={peak_scratch_gib:.2f} GiB -> extrap 1.35B={extrapolated_135b_scratch_gib:.2f} GiB, "
                f"peak RSS={sampler.peak_rss_bytes / 1024**3:.2f} GiB, tiles={val.tile_count:,})",
                flush=True,
            )
            if extrapolated_135b_scratch_gib > 220.0:
                raise RuntimeError(
                    f"Extrapolated 1.35B peak scratch ({extrapolated_135b_scratch_gib:.2f} GiB) "
                    "exceeds 220 GiB safety ceiling — aborting before Rung 4!"
                )
        finally:
            shutil.rmtree(rung3_tmp, ignore_errors=True)
            if rung3_out.exists():
                rung3_out.unlink()

    # =========================================================================
    # RUNG 4: Full 1,348,176,623 Real Gaia DR3 Stars -> public/gaia_v011_full.arrowtiles
    # =========================================================================
    if 4 in enabled_rungs:
        rung4_tmp = scratch_dir / "tmp_rung4_135b"
        shutil.rmtree(rung4_tmp, ignore_errors=True)
        out_gaia.parent.mkdir(parents=True, exist_ok=True)
        if out_gaia.exists():
            out_gaia.unlink()

        d_free_before_r4 = disk_free_gib(scratch_dir)
        print(
            f"\n=== [Rung 4] Building Full 1,348,176,623 Real Gaia Stars -> {out_gaia} "
            f"(D: free={d_free_before_r4:.2f} GiB) ===",
            flush=True,
        )
        t0 = time.perf_counter()
        try:
            with BuildTelemetrySampler(rung4_tmp, out_gaia) as sampler:
                build_res = build_gaia(
                    input_parquet=args.gaia_glob,
                    output_path=out_gaia,
                    row_limit=None,
                    memory_limit=args.memory_limit,
                    temp_dir=rung4_tmp,
                    show_progress=False,
                )
            wall_sec = time.perf_counter() - t0
        finally:
            shutil.rmtree(rung4_tmp, ignore_errors=True)

        out_size = out_gaia.stat().st_size
        legacy_gaia = out_gaia.parent / "gaia_full.arrowtiles"
        legacy_bytes = legacy_gaia.stat().st_size if legacy_gaia.is_file() else None

        print("[Rung 4] Running SPEC v0.1 validate_file on 1.35B archive...", flush=True)
        t_val0 = time.perf_counter()
        val = validate_file(out_gaia, expected_input_rows=1_348_176_623)
        val_sec = time.perf_counter() - t_val0
        if not val.ok:
            raise RuntimeError(f"Rung 4 1.35B validation failed: {val.errors}")

        print("[Rung 4] Cross-checking row_id > 1,000,000,000 stars vs raw s3_cache Parquet...", flush=True)
        ref_stars = extract_billion_rowid_reference_stars(out_gaia, args.gaia_glob, max_targets=5)

        results["rungs"]["rung4_gaia_1_35b"] = {
            "output_path": str(out_gaia),
            "input_rows": 1_348_176_623,
            "retained_rows": int(build_res["total_rows"]),
            "dropped_rows": int(build_res["dropped_rows"]),
            "wall_seconds": round(wall_sec, 3),
            "pass1_seconds": build_res.get("pass1_seconds"),
            "pass2_seconds": build_res.get("pass2_seconds"),
            "rows_per_sec": round(int(build_res["total_rows"]) / max(1e-6, wall_sec), 1),
            "archive_bytes": out_size,
            "archive_gib": round(out_size / (1024.0**3), 3),
            "legacy_v00_archive_gib": (
                round(legacy_bytes / (1024.0**3), 3) if legacy_bytes is not None else None
            ),
            "overview_z0_2_mib": round(int(build_res["overview_z0_2_bytes"]) / (1024.0**2), 3),
            "peak_rss_gib": round(sampler.peak_rss_bytes / (1024.0**3), 3),
            "peak_scratch_gib": round(sampler.peak_temp_dir_bytes / (1024.0**3), 3),
            "peak_combined_disk_gib": round(sampler.peak_combined_disk_bytes / (1024.0**3), 3),
            "validate_seconds": round(val_sec, 3),
            "validation": val.to_dict(),
            "billion_rowid_reference_stars": ref_stars,
            "c_free_after_gib": round(system_drive_free_gib(), 3),
            "d_free_after_gib": round(disk_free_gib(scratch_dir), 3),
        }
        save_checkpoint()
        print(
            f"[Rung 4 PASS] {build_res['total_rows']:,} stars in {wall_sec:.2f}s "
            f"(P1={build_res.get('pass1_seconds')}s, P2={build_res.get('pass2_seconds')}s, "
            f"{int(build_res['total_rows']) / wall_sec:,.0f} rows/s, size={out_size / 1024**3:.2f} GiB, "
            f"peak scratch={sampler.peak_temp_dir_bytes / 1024**3:.2f} GiB, "
            f"peak RSS={sampler.peak_rss_bytes / 1024**3:.2f} GiB, tiles={val.tile_count:,}, "
            f"validate={val_sec:.2f}s)",
            flush=True,
        )

    print(f"\n[Crucible Complete] Saved JSON receipt to {report_path}", flush=True)


if __name__ == "__main__":
    main()
