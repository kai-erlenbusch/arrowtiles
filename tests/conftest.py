"""Pytest configuration and portable helpers for duckdb-arrowtiles.

Ensures:
1. `arrowtiles._core` is loaded exclusively from the local editable package (`arrowtiles/`)
   or active `.venv`, never from a stale root `.pyd` or global system Python.
2. Zstd decompression works across Python 3.10–3.14+.
3. Local dataset paths are resolved relative to the sibling workspace layout (with
   environment variable overrides) and skip cleanly when absent.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_PARENT = REPO_ROOT.parent
DEFAULT_VENV_DIR = REPO_ROOT / ".venv"

if str(REPO_ROOT) not in sys.path:
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
    allowed_roots = [
        (REPO_ROOT / "arrowtiles").resolve(),
    ]
    if Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve():
        allowed_roots.append(Path(sys.prefix).resolve())
    elif DEFAULT_VENV_DIR.is_dir():
        allowed_roots.append(DEFAULT_VENV_DIR.resolve())

    if not any(loaded_path.is_relative_to(root) for root in allowed_roots):
        raise RuntimeError(
            f"Refusing to run tests against unexpected arrowtiles._core at {loaded_path} "
            f"(expected inside {allowed_roots})."
        )
    assert getattr(arrowtiles, "_core", None) is _core


_verify_fresh_core_extension()


def _resolve_optional_file(env_var: str, default_rel: Path, description: str) -> Path:
    override = os.environ.get(env_var)
    candidate = Path(override) if override else (WORKSPACE_PARENT / default_rel)
    if not candidate.is_file():
        pytest.skip(f"Requires local {description} at {candidate} (or ${env_var})")
    return candidate


@pytest.fixture
def lmsys_arrowtiles_path() -> Path:
    return _resolve_optional_file(
        "ARROWTILES_LMSYS_ARCHIVE",
        Path("deepgraph-arrowtiles-sandbox") / "public" / "lmsys_full.arrowtiles",
        "LMSys archive",
    )


@pytest.fixture
def gaia_arrowtiles_path() -> Path:
    return _resolve_optional_file(
        "ARROWTILES_GAIA_ARCHIVE",
        Path("deepgraph-arrowtiles-sandbox") / "public" / "gaia_full.arrowtiles",
        "Gaia archive",
    )


@pytest.fixture
def mock_lmsys_parquet_path() -> Path:
    return _resolve_optional_file(
        "ARROWTILES_MOCK_LMSYS_PARQUET",
        Path("mock_lmsys.parquet"),
        "LMSys sample parquet",
    )


@pytest.fixture
def full_lmsys_parquet_path() -> Path:
    return _resolve_optional_file(
        "ARROWTILES_FULL_LMSYS_PARQUET",
        Path("duckdb-cosmograph-oss") / "lmsys.parquet",
        "full LMSys parquet",
    )


@pytest.fixture
def gaia_batch0_parquet_path() -> Path:
    return _resolve_optional_file(
        "ARROWTILES_GAIA_BATCH0_PARQUET",
        Path("deepgraph-arrowtiles-sandbox") / "s3_cache" / "batch_000.parquet",
        "Gaia s3_cache batch_000.parquet",
    )


__all__ = ["REPO_ROOT", "WORKSPACE_PARENT", "zstd_decompress"]
