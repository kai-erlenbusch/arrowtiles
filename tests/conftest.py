"""Pytest configuration and portable helpers for duckdb-arrowtiles.

Ensures:
1. `arrowtiles_core` is loaded exclusively from the active virtualenv (`.venv`),
   verified by file path (not `hasattr`, which stale July `.pyd` builds also pass).
2. Zstd decompression works across Python 3.10–3.14+ (`compression.zstd` on 3.14+,
   falling back to `pyarrow` streaming Zstd).
3. Local dataset paths are resolved relative to the sibling workspace layout (with
   environment variable overrides) and skip cleanly when absent.
"""

from __future__ import annotations

import importlib.util
import os
import site
import sys
from pathlib import Path

import pyarrow as pa
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_PARENT = REPO_ROOT.parent
DEFAULT_VENV_DIR = REPO_ROOT / ".venv"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _expected_venv_root() -> Path:
    if Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve():
        return Path(sys.prefix).resolve()
    if DEFAULT_VENV_DIR.is_dir():
        return DEFAULT_VENV_DIR.resolve()
    raise RuntimeError(
        f"Tests must run with a virtualenv containing arrowtiles_core (expected {DEFAULT_VENV_DIR})."
    )


def _load_and_verify_venv_arrowtiles_core() -> None:
    venv_root = _expected_venv_root()
    candidate_dirs = [
        venv_root / "Lib" / "site-packages",
        *map(Path, site.getsitepackages()),
    ]
    for sp in candidate_dirs:
        sp_resolved = sp.resolve()
        if not sp_resolved.is_relative_to(venv_root):
            continue
        pkg_init = sp_resolved / "arrowtiles_core" / "__init__.py"
        if pkg_init.is_file():
            spec = importlib.util.spec_from_file_location(
                "arrowtiles_core",
                pkg_init,
                submodule_search_locations=[str(pkg_init.parent)],
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules["arrowtiles_core"] = mod
                spec.loader.exec_module(mod)
                break

    import arrowtiles_core  # noqa: PLC0415

    loaded_path = Path(arrowtiles_core.__file__).resolve()
    if not loaded_path.is_relative_to(venv_root):
        raise RuntimeError(
            f"Refusing to run tests against non-venv arrowtiles_core at {loaded_path} "
            f"(expected inside {venv_root})."
        )


_load_and_verify_venv_arrowtiles_core()

try:
    import compression.zstd as _stdlib_zstd  # Python 3.14+ (PEP 784)
except ImportError:
    _stdlib_zstd = None


def zstd_decompress(raw: bytes) -> bytes:
    """Decompress a Zstd frame portably across Python 3.10–3.14+."""
    if _stdlib_zstd is not None:
        return _stdlib_zstd.decompress(raw)
    return pa.input_stream(pa.py_buffer(raw), compression="zstd").read()


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
