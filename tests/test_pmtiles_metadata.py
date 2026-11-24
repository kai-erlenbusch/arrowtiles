"""PMTiles metadata & embedded Arrow schema verification (portable fixtures, no hardcoded drive paths)."""

from __future__ import annotations

import base64
from pathlib import Path

import pyarrow.ipc as ipc
from pmtiles.reader import MmapSource, Reader


def test_read_lmsys_pmtiles_metadata_and_schema(lmsys_arrowtiles_path: Path) -> None:
    with open(lmsys_arrowtiles_path, "rb") as fh:
        reader = Reader(MmapSource(fh))
        header = reader.header()
        assert header["version"] == 3
        metadata = reader.metadata()
        assert "arrow_schema" in metadata
        schema_bytes = base64.b64decode(metadata["arrow_schema"])
        schema = ipc.RecordBatchStreamReader(schema_bytes).schema
        assert "x_u16" in schema.names
        assert "y_u16" in schema.names


def test_read_gaia_pmtiles_metadata_and_schema(gaia_arrowtiles_path: Path) -> None:
    with open(gaia_arrowtiles_path, "rb") as fh:
        reader = Reader(MmapSource(fh))
        header = reader.header()
        assert header["version"] == 3
        metadata = reader.metadata()
        assert "arrow_schema" in metadata
        schema_bytes = base64.b64decode(metadata["arrow_schema"])
        schema = ipc.RecordBatchStreamReader(schema_bytes).schema
        names = set(schema.names)
        assert {"x_u16", "y_u16", "bp_rp"}.issubset(names)
        assert "phot_g_mean_mag" in names or "abs_m" in names
