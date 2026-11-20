"""ArrowTiles v0.1 Python package: builder, reference reader, and archive validator."""

from __future__ import annotations

import sys

from arrowtiles._zstd import zstd_decompress
from arrowtiles.builder import (
    SPEC_FORMAT,
    SPEC_VERSION,
    ArrowTilesBuilder,
    build_gaia,
    build_generic,
)
from arrowtiles.reader import ArrowTilesReader
from arrowtiles.validator import ValidationResult, validate_file

try:
    from arrowtiles import _core

    sys.modules["arrowtiles_core"] = _core
except ImportError:
    _core = None  # type: ignore[assignment]

__version__ = "0.1.0"

__all__ = [
    "SPEC_FORMAT",
    "SPEC_VERSION",
    "ArrowTilesBuilder",
    "ArrowTilesReader",
    "ValidationResult",
    "__version__",
    "build_gaia",
    "build_generic",
    "validate_file",
    "zstd_decompress",
]
