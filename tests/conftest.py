"""Pytest configuration and portable helpers for arrowtiles.

Ensures:
1. `arrowtiles._core` is loaded exclusively from the local editable package (`arrowtiles/`),
   active `.venv`, or an explicitly tested wheel (`ARROWTILES_TEST_INSTALLED_WHEEL=1`).
2. Zstd decompression works across Python 3.10–3.14+.
3. Local dataset paths resolve from the sibling workspace layout when present, and fall back
   to deterministic synthetic fixtures in `tmp_path_factory` so CI and isolated wheel tests
   run 100% of the test suite (`0 skipped`).
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.cffi as pc_ffi
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_PARENT = REPO_ROOT.parent
DEFAULT_VENV_DIR = REPO_ROOT / ".venv"

if os.environ.get("ARROWTILES_TEST_INSTALLED_WHEEL") == "1":
    cleaned_sys_path: list[str] = []
    for entry in sys.path:
        resolved_entry = Path(entry if entry else os.getcwd()).resolve()
        pkg_init = resolved_entry / "arrowtiles" / "__init__.py"
        has_compiled_core = any(
            (resolved_entry / "arrowtiles").glob("_core*")
        ) if pkg_init.is_file() else False
        if pkg_init.is_file() and not has_compiled_core:
            continue
        cleaned_sys_path.append(entry)
    sys.path[:] = cleaned_sys_path
elif (
    (REPO_ROOT / "arrowtiles").is_dir()
    and str(REPO_ROOT) not in sys.path
):
    sys.path.insert(0, str(REPO_ROOT))

from arrowtiles._zstd import zstd_decompress  # noqa: E402


def _verify_fresh_core_extension() -> None:
    if (REPO_ROOT / "arrowtiles_core.pyd").exists():
        raise RuntimeError(
            f"Stale root binary {REPO_ROOT / 'arrowtiles_core.pyd'} must not exist."
        )

    import arrowtiles  # noqa: PLC0415
    from arrowtiles import _core  # noqa: PLC0415

    if _core is None or not getattr(_core, "__file__", None):
        raise RuntimeError(
            "Native extension 'arrowtiles._core' is not built. Run `maturin develop --release`."
        )

    loaded_path = Path(_core.__file__).resolve()
    if os.environ.get("ARROWTILES_TEST_INSTALLED_WHEEL") == "1":
        if (REPO_ROOT / "arrowtiles").is_dir() and loaded_path.is_relative_to(
            (REPO_ROOT / "arrowtiles").resolve()
        ):
            raise RuntimeError(
                f"Expected installed wheel, but loaded source tree binary at {loaded_path}"
            )
        assert getattr(arrowtiles, "_core", None) is _core
        return

    allowed_roots = [
        (REPO_ROOT / "arrowtiles").resolve(),
    ]
    if Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve():
        allowed_roots.append(Path(sys.prefix).resolve())
    elif DEFAULT_VENV_DIR.is_dir():
        allowed_roots.append(DEFAULT_VENV_DIR.resolve())
    for key in ("platlib", "purelib"):
        sp = sysconfig.get_path(key)
        if sp:
            allowed_roots.append(Path(sp).resolve())

    if not any(loaded_path.is_relative_to(root) for root in allowed_roots):
        raise RuntimeError(
            f"Refusing to run tests against unexpected arrowtiles._core at {loaded_path} "
            f"(expected inside {allowed_roots})."
        )
    assert getattr(arrowtiles, "_core", None) is _core


_verify_fresh_core_extension()


def _resolve_optional_file(env_var: str, default_rel: Path) -> Path | None:
    override = os.environ.get(env_var)
    candidate = Path(override) if override else (WORKSPACE_PARENT / default_rel)
    if candidate.is_file():
        return candidate
    return None


def _sibling_viewer_dir() -> Path:
    preferred = WORKSPACE_PARENT / "deepgraph"
    if preferred.is_dir():
        return preferred
    return WORKSPACE_PARENT / "deepgraph-arrowtiles-sandbox"


def _build_legacy_v00_fixture(out_path: Path) -> Path:
    """Create a deterministic legacy v0.0 archive (omitting format & version keys)."""
    from arrowtiles import _core  # noqa: PLC0415

    schema_in = pa.schema(
        [
            pa.field("x_u16", pa.uint16(), nullable=False),
            pa.field("y_u16", pa.uint16(), nullable=False),
            pa.field("z", pa.uint8(), nullable=False),
            pa.field("num_of_tokens", pa.float32(), nullable=True),
            pa.field("final_tile_id", pa.uint64(), nullable=False),
        ]
    )
    empty_reader = pa.RecordBatchReader.from_batches(schema_in, [])
    c_schema = pc_ffi.ffi.new("struct ArrowArrayStream*")
    ptr_schema = int(pc_ffi.ffi.cast("uintptr_t", c_schema))
    empty_reader._export_to_c(ptr_schema)

    packer = _core.ArrowTilesPacker(
        str(out_path),
        ptr_schema,
        10_000,
        0,
        1_000,
        '{"bounds":{"min_x":-10.0,"max_x":10.0,"min_y":-10.0,"max_y":10.0}}',
        None,
    )

    n = 64
    batch = pa.RecordBatch.from_arrays(
        [
            pa.array([int((i * 997) % 65535) for i in range(n)], type=pa.uint16()),
            pa.array([int((i * 1999) % 65535) for i in range(n)], type=pa.uint16()),
            pa.array([0] * n, type=pa.uint8()),
            pa.array([float(i * 10 + 1) for i in range(n)], type=pa.float32()),
            pa.array([0] * n, type=pa.uint64()),
        ],
        schema=schema_in,
    )
    data_reader = pa.RecordBatchReader.from_batches(schema_in, [batch])
    c_data = pc_ffi.ffi.new("struct ArrowArrayStream*")
    ptr_data = int(pc_ffi.ffi.cast("uintptr_t", c_data))
    data_reader._export_to_c(ptr_data)
    packer.process_batch(ptr_data)
    packer.finalize()
    return out_path


@pytest.fixture(scope="session")
def _synthetic_fixtures_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("arrowtiles_ci_fixtures")


@pytest.fixture
def lmsys_arrowtiles_path(_synthetic_fixtures_dir: Path) -> Path:
    found = _resolve_optional_file(
        "ARROWTILES_LMSYS_ARCHIVE",
        _sibling_viewer_dir().relative_to(WORKSPACE_PARENT) / "public" / "lmsys_full.arrowtiles",
    )
    if found is not None:
        return found
    fallback = _synthetic_fixtures_dir / "synthetic_legacy_lmsys.arrowtiles"
    if not fallback.is_file():
        _build_legacy_v00_fixture(fallback)
    return fallback


@pytest.fixture
def gaia_arrowtiles_path(_synthetic_fixtures_dir: Path) -> Path:
    found = _resolve_optional_file(
        "ARROWTILES_GAIA_ARCHIVE",
        _sibling_viewer_dir().relative_to(WORKSPACE_PARENT) / "public" / "gaia_full.arrowtiles",
    )
    if found is not None:
        return found
    fallback = _synthetic_fixtures_dir / "synthetic_gaia.arrowtiles"
    if not fallback.is_file():
        from arrowtiles import ArrowTilesBuilder  # noqa: PLC0415

        tdir = _synthetic_fixtures_dir / "gaia_fb_temp"
        with ArrowTilesBuilder(memory_limit="512MB", temp_dir=tdir, show_progress=False) as b:
            b.build(
                input_query="""
                    SELECT
                        CAST(i AS UBIGINT) AS row_id,
                        CAST((i % 32) / 32.0 AS DOUBLE) AS x_norm,
                        CAST((i // 32) / 32.0 AS DOUBLE) AS y_norm,
                        CAST(5.0 + (i % 15) * 0.5 AS FLOAT) AS abs_m,
                        CAST(-0.2 + (i % 10) * 0.3 AS FLOAT) AS bp_rp
                    FROM range(128) t(i)
                """,
                output_path=fallback,
                sort_col="abs_m",
                x_col="x_norm",
                y_col="y_norm",
                id_col="row_id",
                max_capacity=64,
                max_zoom=4,
            )
    return fallback


@pytest.fixture
def mock_lmsys_parquet_path(_synthetic_fixtures_dir: Path) -> Path:
    found = _resolve_optional_file(
        "ARROWTILES_MOCK_LMSYS_PARQUET",
        Path("mock_lmsys.parquet"),
    )
    if found is not None:
        return found
    fallback = _synthetic_fixtures_dir / "synthetic_mock_lmsys.parquet"
    if not fallback.is_file():
        con = duckdb.connect()
        con.execute(
            f"""
            COPY (
                SELECT
                    CAST(sin(i * 0.01) * 10.0 AS DOUBLE) AS x,
                    CAST(cos(i * 0.013) * 10.0 AS DOUBLE) AS y,
                    CASE (i % 4)
                        WHEN 0 THEN 'gpt-4'
                        WHEN 1 THEN 'claude-3'
                        WHEN 2 THEN 'llama-3'
                        ELSE 'vicuna-13b'
                    END AS model,
                    CAST(16 + (i * 7) % 2048 AS INTEGER) AS num_of_tokens
                FROM range(5200) t(i)
            ) TO '{fallback.as_posix()}' (FORMAT PARQUET)
            """
        )
        con.close()
    return fallback


@pytest.fixture
def full_lmsys_parquet_path(_synthetic_fixtures_dir: Path) -> Path:
    found = _resolve_optional_file(
        "ARROWTILES_FULL_LMSYS_PARQUET",
        Path("lmsys.parquet"),
    )
    if found is not None:
        return found
    fallback = _synthetic_fixtures_dir / "synthetic_full_lmsys_schema.parquet"
    if not fallback.is_file():
        con = duckdb.connect()
        con.execute(
            f"""
            COPY (
                SELECT
                    CAST(i * 0.1 AS DOUBLE) AS x_umap,
                    CAST(i * -0.1 AS DOUBLE) AS y_umap,
                    CAST(32 + i AS INTEGER) AS num_of_tokens,
                    'gpt-4' AS model
                FROM range(64) t(i)
            ) TO '{fallback.as_posix()}' (FORMAT PARQUET)
            """
        )
        con.close()
    return fallback


@pytest.fixture
def gaia_batch0_parquet_path(_synthetic_fixtures_dir: Path) -> Path:
    found = _resolve_optional_file(
        "ARROWTILES_GAIA_BATCH0_PARQUET",
        _sibling_viewer_dir().relative_to(WORKSPACE_PARENT) / "s3_cache" / "batch_000.parquet",
    )
    if found is not None:
        return found
    fallback = _synthetic_fixtures_dir / "synthetic_gaia_batch0.parquet"
    if not fallback.is_file():
        con = duckdb.connect()
        con.execute(
            f"""
            COPY (
                SELECT
                    CAST((i * 137.507764) % 360.0 AS DOUBLE) AS ra,
                    CAST(-89.5 + ((i * 73.13) % 179.0) AS DOUBLE) AS dec,
                    CAST(6.0 + (i % 140) * 0.1 AS FLOAT) AS magnitude,
                    CAST(-0.3 + (i % 40) * 0.1 AS FLOAT) AS bv,
                    CAST(0.5 + (i % 20) * 0.2 AS FLOAT) AS parallax,
                    CAST((i % 50) - 25.0 AS FLOAT) AS pmra,
                    CAST((i % 40) - 20.0 AS FLOAT) AS pmdec,
                    CAST((i % 100) - 50.0 AS FLOAT) AS radial_velocity,
                    CAST(3200.0 + (i % 80) * 100.0 AS FLOAT) AS teff_gspphot
                FROM range(5200) t(i)
            ) TO '{fallback.as_posix()}' (FORMAT PARQUET)
            """
        )
        con.close()
    return fallback


__all__ = ["REPO_ROOT", "WORKSPACE_PARENT", "zstd_decompress"]
