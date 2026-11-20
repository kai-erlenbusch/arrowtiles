"""Cross-version Zstd decompression helper (Python 3.10–3.14+)."""

from __future__ import annotations

import pyarrow as pa

try:
    import compression.zstd as _stdlib_zstd  # Python 3.14+ (PEP 784)
except ImportError:
    _stdlib_zstd = None


def zstd_decompress(raw: bytes | memoryview) -> bytes:
    """Decompress a single Zstd frame into raw bytes."""
    if _stdlib_zstd is not None:
        return _stdlib_zstd.decompress(raw)
    return pa.input_stream(pa.py_buffer(raw), compression="zstd").read()
