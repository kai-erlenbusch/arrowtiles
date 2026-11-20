"""PMTiles metadata & embedded Arrow schema verification (adapted from archive/tests/read_meta_pmtiles.py & read_meta.py)."""

from __future__ import annotations

import base64
from pathlib import Path

import pyarrow.ipc as ipc
import pytest
from pmtiles.reader import MmapSource, Reader

VIEWER_PUBLIC = Path(r"D:\exploratory\duckdb-extension\deepgraph-arrowtiles-sandbox\public")
LMSYS_ARROWTILES = VIEWER_PUBLIC / "lmsys_full.arrowtiles"
GAIA_ARROWTILES = VIEWER_PUBLIC / "gaia_full.arrowtiles"


@pytest.mark.skipif(
    not LMSYS_ARROWTILES.is_file(),
    reason=f"Requires local archive {LMSYS_ARROWTILES}",
)
def test_read_lmsys_pmtiles_metadata_and_schema() -> None:
    with open(LMSYS_ARROWTILES, "rb") as fh:
        reader = Reader(MmapSource(fh))
        header = reader.header()
        assert header["version"] == 3
        metadata = reader.metadata()
        assert "arrow_schema" in metadata
        schema_bytes = base64.b64decode(metadata["arrow_schema"])
        schema = ipc.RecordBatchStreamReader(schema_bytes).schema
        assert "x_u16" in schema.names
        assert "y_u16" in schema.names


@pytest.mark.skipif(
    not GAIA_ARROWTILES.is_file(),
    reason=f"Requires local archive {GAIA_ARROWTILES}",
)
def test_read_gaia_pmtiles_metadata_and_schema() -> None:
    with open(GAIA_ARROWTILES, "rb") as fh:
        reader = Reader(MmapSource(fh))
        header = reader.header()
        assert header["version"] == 3
        metadata = reader.metadata()
        assert "arrow_schema" in metadata
        schema_bytes = base64.b64decode(metadata["arrow_schema"])
        schema = ipc.RecordBatchStreamReader(schema_bytes).schema
        assert {"x_u16", "y_u16", "abs_m", "bp_rp"}.issubset(set(schema.names))
